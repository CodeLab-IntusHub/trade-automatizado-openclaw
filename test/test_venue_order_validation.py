"""Resposta da corretora para ordem de protecao tem de ser confirmada.

Os chamadores de `place_stop_loss`/`place_take_profit` so testam
`if order is None`, entao qualquer objeto devolvido contava como "protecao
anexada" -- inclusive uma rejeicao estruturada.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ccxt e dependencia base (workspace/requirements.txt). Ausencia e falha de
# ambiente, nao motivo para pular silenciosamente testes de protecao de ordem.
import ccxt  # noqa: E402

from workspace.venues.ccxt_cex import GenericCcxtTrader, VenueCapabilityError  # noqa: E402


class _FakeExchange:
    order_response: object = {"id": "ok-1", "status": "open"}

    def __init__(self, config):
        self.config = config
        self.created = []
        self.markets = {
            "ETH/USDT:USDT": {
                "base": "ETH", "quote": "USDT", "settle": "USDT",
                "swap": True, "contract": True,
                "precision": {"amount": 3}, "limits": {"amount": {"min": 0.001}},
            }
        }

    def load_markets(self):
        return self.markets

    def market(self, symbol):
        return self.markets[symbol]

    def create_order(self, symbol, order_type, side, quantity, price, params):
        self.created.append({"symbol": symbol, "side": side, "params": params})
        return self.order_response


def _make(monkeypatch, response):
    cls = type("FakeEx", (_FakeExchange,), {"order_response": response})
    monkeypatch.setattr(ccxt, "fakeexchange", cls, raising=False)
    return GenericCcxtTrader("fakeexchange", "k", "s", load_markets=False)


@pytest.mark.parametrize("status", ["canceled", "cancelled", "rejected", "expired", "failed"])
def test_rejeicao_estruturada_nao_conta_como_protecao(monkeypatch, status) -> None:
    trader = _make(monkeypatch, {"id": "x", "status": status})
    with pytest.raises(VenueCapabilityError, match="(?i)rejeit"):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)
    with pytest.raises(VenueCapabilityError):
        trader.place_take_profit("ETH/USDT:USDT", 1.0, 3000.0, is_long=True)


@pytest.mark.parametrize("status", ["open", "active", "triggered", "working", "untriggered", "new", ""])
def test_status_incomum_porem_aceito_nao_e_tratado_como_falha(monkeypatch, status) -> None:
    """Uma allowlist rejeitaria ordem aceita: o chamador marcaria a posicao
    como desprotegida e o retry anexaria um segundo stop."""
    trader = _make(monkeypatch, {"id": "sl-9", "status": status})
    assert trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)["id"] == "sl-9"


@pytest.mark.parametrize("resposta", [None, "texto", 123, []])
def test_resposta_nao_estruturada_e_recusada(monkeypatch, resposta) -> None:
    trader = _make(monkeypatch, resposta)
    with pytest.raises(VenueCapabilityError):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)


def test_ordem_sem_id_avisa_que_pode_existir_na_corretora(monkeypatch) -> None:
    """Sem id nao da para cancelar nem substituir depois; tratar como sucesso
    deixaria um stop possivelmente vivo e irrastreavel."""
    trader = _make(monkeypatch, {"status": "open"})
    with pytest.raises(VenueCapabilityError, match="(?i)verifique a posicao"):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)


def test_ordem_confirmada_e_devolvida(monkeypatch) -> None:
    trader = _make(monkeypatch, {"id": "sl-1", "status": "open"})
    assert trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)["id"] == "sl-1"
