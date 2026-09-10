"""Os adapters em uso real tambem precisam confirmar a ordem de protecao.

Hyperliquid e Kraken nao passam pelo `GenericCcxtTrader` -- cada uma tem
adapter proprio. A validacao de resposta entrou primeiro no adapter generico,
que atende as CEXs que o operador nao usa; estes sao os caminhos que ele opera.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ccxt = pytest.importorskip(
    "ccxt", reason="ccxt e dependencia base; ausente so em ambiente local incompleto"
)

from workspace.venues.order_validation import (  # noqa: E402
    UnconfirmedOrderError,
    VenueCapabilityError,
    validate_order_response,
)


# --- validador compartilhado ------------------------------------------------

def test_rejeicao_estruturada_e_recusada() -> None:
    for status in ("canceled", "cancelled", "rejected", "expired", "failed"):
        with pytest.raises(VenueCapabilityError, match="(?i)rejeit"):
            validate_order_response({"id": "x", "status": status}, exchange_id="v", what="stop loss")


def test_status_incomum_porem_aceito_passa() -> None:
    for status in ("open", "active", "triggered", "working", "untriggered", ""):
        assert validate_order_response({"id": "a", "status": status}, exchange_id="v", what="sl")["id"] == "a"


def test_sem_id_e_ambiguo_e_nao_manda_retentar() -> None:
    with pytest.raises(UnconfirmedOrderError) as exc:
        validate_order_response({"status": "open"}, exchange_id="v", what="stop loss")
    msg = str(exc.value).lower()
    assert "pode ter sido criada" in msg and "sem stop" not in msg


def test_resposta_nao_estruturada_e_recusada() -> None:
    for resposta in (None, "texto", 123, []):
        with pytest.raises(VenueCapabilityError):
            validate_order_response(resposta, exchange_id="v", what="sl")


# --- adapters reais ---------------------------------------------------------

def _hyperliquid(monkeypatch, response):
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    adapter = HyperliquidDexTrader(load_markets=False)
    adapter._resolve_market_symbol = lambda _p: "ETH/USDC:USDC"
    adapter.client = type("C", (), {"create_order": lambda *_a, **_k: response})()
    return adapter


def _kraken(monkeypatch, response):
    from workspace.kraken.kraken_integration import KrakenTrader

    adapter = object.__new__(KrakenTrader)
    adapter.venue = "futures"
    adapter.exchange_id = "krakenfutures"
    adapter._resolve_market_symbol = lambda s: s
    adapter.client = type("C", (), {"create_order": lambda *_a, **_k: response})()
    return adapter


@pytest.mark.parametrize("fabrica", [_hyperliquid, _kraken], ids=["hyperliquid", "kraken"])
def test_adapter_em_uso_recusa_rejeicao_da_corretora(monkeypatch, fabrica) -> None:
    """Antes: `return self.client.create_order(...)` cru -- rejeicao contava
    como protecao anexada, porque o chamador so testa `if order is None`."""
    adapter = fabrica(monkeypatch, {"id": "x", "status": "rejected"})
    with pytest.raises(VenueCapabilityError):
        adapter.place_stop_loss("ETH/USDT", 1.0, 2000.0, is_long=True)
    with pytest.raises(VenueCapabilityError):
        adapter.place_take_profit("ETH/USDT", 1.0, 3000.0, is_long=True)


@pytest.mark.parametrize("fabrica", [_hyperliquid, _kraken], ids=["hyperliquid", "kraken"])
def test_adapter_em_uso_aceita_ordem_confirmada(monkeypatch, fabrica) -> None:
    adapter = fabrica(monkeypatch, {"id": "sl-1", "status": "open"})
    assert adapter.place_stop_loss("ETH/USDT", 1.0, 2000.0, is_long=True)["id"] == "sl-1"


def test_hyperliquid_avisa_quando_a_troca_deixa_a_posicao_nua(monkeypatch) -> None:
    """`replace_stop_loss` cancela o stop vivo antes de criar o novo, igual ao
    adapter generico -- e aqui tambem falhava calado."""
    adapter = _hyperliquid(monkeypatch, {"id": "x", "status": "rejected"})
    cancelados = []
    adapter.cancel_order = lambda order_id, product_id=None: cancelados.append(order_id)
    with pytest.raises(VenueCapabilityError, match="(?i)sem stop|desprotegida"):
        adapter.replace_stop_loss("ETH/USDT", 1.0, 2000.0, previous_order_ref={"id": "old"})
    assert cancelados == ["old"]


def test_kraken_avisa_quando_a_troca_deixa_a_posicao_nua(monkeypatch) -> None:
    """Mesmo padrao cancelar->criar do Hyperliquid e do adapter generico."""
    adapter = _kraken(monkeypatch, {"id": "x", "status": "rejected"})
    cancelados = []
    adapter.cancel_order = lambda order_id, symbol=None: cancelados.append(order_id)
    with pytest.raises(VenueCapabilityError, match="(?i)sem stop|desprotegida"):
        adapter.replace_stop_loss("ETH/USDT", 1.0, 2000.0, previous_order_ref={"id": "old"})
    assert cancelados == ["old"]
