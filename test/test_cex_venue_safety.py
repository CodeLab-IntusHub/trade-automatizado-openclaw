"""Seguranca do caminho de CEX generica (qualquer exchange via CCXT).

A skill oferece Kraken, Binance, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io.
So a Kraken tem adapter dedicado; as demais passam pelo `GenericCcxtTrader`.
Estes testes cobrem o que esse caminho declarava sem verificar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ccxt = pytest.importorskip("ccxt")

from workspace.venues.ccxt_cex import GenericCcxtTrader, VenueCapabilityError  # noqa: E402


class _FakeExchange:
    """Exchange CCXT minima, parametrizavel por `has` e por falha de sandbox."""

    has: dict = {}
    sandbox_error: Exception | None = None
    order_response: object = {"id": "ok-1", "status": "open"}

    def __init__(self, config):
        self.config = config
        self.sandbox_calls = []
        self.created = []
        self.markets = {
            "ETH/USDT:USDT": {
                "base": "ETH", "quote": "USDT", "settle": "USDT",
                "swap": True, "contract": True,
                "precision": {"amount": 3}, "limits": {"amount": {"min": 0.001}},
            }
        }

    def set_sandbox_mode(self, enabled):
        self.sandbox_calls.append(enabled)
        if self.sandbox_error is not None:
            raise self.sandbox_error

    def load_markets(self):
        return self.markets

    def market(self, symbol):
        return self.markets[symbol]

    def create_order(self, symbol, order_type, side, quantity, price, params):
        self.created.append({"symbol": symbol, "type": order_type, "side": side, "params": params})
        return self.order_response


def _make(monkeypatch, *, has=None, sandbox_error=None, order_response={"id": "ok-1", "status": "open"}, **kwargs):
    cls = type("FakeEx", (_FakeExchange,), {
        "has": has if has is not None else {},
        "sandbox_error": sandbox_error,
        "order_response": order_response,
    })
    monkeypatch.setattr(ccxt, "fakeexchange", cls, raising=False)
    return GenericCcxtTrader("fakeexchange", "k", "s", load_markets=False, **kwargs)


# --- Gap: sandbox pedido mas indisponivel caia em producao -------------------

def test_sandbox_indisponivel_falha_em_vez_de_operar_ao_vivo(monkeypatch) -> None:
    """Pedir sandbox e receber producao em silencio e o pior desfecho possivel.

    Nem toda CEX tem testnet. O codigo antigo logava um warning e seguia com o
    cliente apontando para producao -- com as chaves reais do usuario.
    """
    with pytest.raises(VenueCapabilityError, match="sandbox"):
        _make(monkeypatch, sandbox_error=ccxt.NotSupported("sem testnet"), sandbox=True)


def test_sandbox_bem_sucedido_ativa_o_modo(monkeypatch) -> None:
    trader = _make(monkeypatch, sandbox=True)
    assert trader.client.sandbox_calls == [True]


def test_sem_sandbox_nao_mexe_no_modo(monkeypatch) -> None:
    trader = _make(monkeypatch, sandbox=False)
    assert trader.client.sandbox_calls == []


# --- Gap: matriz de capacidades declarada sem consultar nada ----------------

def test_capabilities_refletem_o_has_do_ccxt(monkeypatch) -> None:
    sem_sl = _make(monkeypatch, has={"createStopLossOrder": False, "createTakeProfitOrder": False})
    assert sem_sl.capabilities()["native_sl"] is False
    assert sem_sl.capabilities()["native_tp"] is False

    com_sl = _make(monkeypatch, has={"createStopLossOrder": True, "createTakeProfitOrder": True,
                                     "editOrder": True, "cancelOrder": True})
    caps = com_sl.capabilities()
    assert caps["native_sl"] is True and caps["native_tp"] is True
    assert caps["edit_stop"] is True and caps["cancel_trigger"] is True


def test_reduce_only_nao_e_declarado_em_spot(monkeypatch) -> None:
    """`reduceOnly` so existe em derivativo; declarar em spot e mentira."""
    spot = _make(monkeypatch, has={"createStopLossOrder": True}, market_type="spot")
    assert spot.capabilities()["reduce_only"] is False


# --- Gap: SL/TP enviados sem checar suporte e sem validar resposta ----------

def test_stop_loss_recusa_venue_sem_suporte_nativo(monkeypatch) -> None:
    trader = _make(monkeypatch, has={"createStopLossOrder": False})
    with pytest.raises(VenueCapabilityError, match="stop"):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)
    assert trader.client.created == [], "nao pode ter enviado ordem alguma"


def test_take_profit_recusa_venue_sem_suporte_nativo(monkeypatch) -> None:
    trader = _make(monkeypatch, has={"createTakeProfitOrder": False})
    with pytest.raises(VenueCapabilityError):
        trader.place_take_profit("ETH/USDT:USDT", 1.0, 3000.0, is_long=True)


@pytest.mark.parametrize("resposta", [None, {}, {"status": "rejected", "id": "x"}, "texto"])
def test_resposta_invalida_da_corretora_nao_conta_como_protecao(monkeypatch, resposta) -> None:
    """Qualquer objeto nao-None contava como sucesso; rejeicao passava batida."""
    trader = _make(monkeypatch, has={"createStopLossOrder": True}, order_response=resposta)
    with pytest.raises(VenueCapabilityError, match="(?i)resposta|rejeit"):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)


def test_stop_loss_aceito_devolve_a_ordem(monkeypatch) -> None:
    trader = _make(monkeypatch, has={"createStopLossOrder": True},
                   order_response={"id": "sl-1", "status": "open"})
    order = trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)
    assert order["id"] == "sl-1"
    assert trader.client.created[0]["params"]["reduceOnly"] is True


# --- Gap: default de sandbox mandava CEX nao-Kraken direto para producao ----

@pytest.fixture
def _limpa_env_sandbox(monkeypatch):
    for name in ("CEX_SANDBOX", "BYBIT_SANDBOX", "KRAKEN_SANDBOX", "BINANCEUSDM_SANDBOX"):
        monkeypatch.delenv(name, raising=False)


def test_cex_nao_kraken_sem_config_explicita_nao_assume_producao(_limpa_env_sandbox) -> None:
    """O default era `cex_id.startswith("kraken")`: Kraken ia para sandbox e
    todo o resto ia para producao. Quem trocasse de venue herdava dinheiro real
    sem nunca ter dito isso."""
    import workspace.cli as cli

    for loader in (cli._load_cex_sandbox, cli._load_pair_cex_sandbox):
        with pytest.raises(SystemExit, match="(?i)SANDBOX"):
            loader("bybit")


def test_decisao_explicita_e_respeitada(monkeypatch, _limpa_env_sandbox) -> None:
    import workspace.cli as cli

    monkeypatch.setenv("CEX_SANDBOX", "false")
    assert cli._load_cex_sandbox("bybit") is False
    assert cli._load_pair_cex_sandbox("bybit") is False

    monkeypatch.setenv("BYBIT_SANDBOX", "true")
    assert cli._load_cex_sandbox("bybit") is True
    assert cli._load_pair_cex_sandbox("bybit") is True


def test_kraken_mantem_o_default_seguro(_limpa_env_sandbox) -> None:
    """A Kraken ja tinha default seguro e documentado; nao muda."""
    import workspace.cli as cli

    assert cli._load_cex_sandbox("kraken") is True
    assert cli._load_pair_cex_sandbox("kraken-spot") is True


# --- Gap: matriz de capacidades estatica no diagnostico --------------------

def test_venue_capabilities_consulta_o_ccxt_em_vez_de_afirmar() -> None:
    """Os dois ramos do `if` devolviam exatamente a mesma coisa: tudo `True`
    para qualquer CEX, sem consultar nada."""
    from workspace.venues.config import venue_capabilities

    caps = venue_capabilities("cex", "binanceusdm")
    esperado = ccxt.binanceusdm().has
    assert caps["native_sl"] is bool(
        esperado.get("createStopLossOrder") or esperado.get("createStopOrder")
        or esperado.get("createTriggerOrder")
    )


def test_venue_desconhecida_e_conservadora_e_nao_otimista() -> None:
    from workspace.venues.config import venue_capabilities

    caps = venue_capabilities("cex", "exchange-que-nao-existe")
    assert not any(caps.values()), "venue desconhecida nao pode declarar capacidade"


def test_diagnostico_nao_afirma_producao_onde_o_cli_recusa(monkeypatch) -> None:
    """O `venues` reportava `sandbox=false` para uma config que o CLI recusa.

    Dois vereditos para a mesma configuracao e o defeito que essa frente
    inteira ataca; o diagnostico tem de dizer "nao definido".
    """
    from workspace.venues.config import venue_summary

    for name in ("CEX_SANDBOX", "BYBIT_SANDBOX"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CEX_ID", "bybit")

    assert venue_summary()["cex_sandbox"] == "nao_definido"

    monkeypatch.setenv("CEX_SANDBOX", "false")
    assert venue_summary()["cex_sandbox"] == "false"
