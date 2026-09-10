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

# ccxt e dependencia base (workspace/requirements.txt) e o CI a instala, entao
# na pratica isto nunca pula la -- estes testes sempre valem nota. Localmente,
# um import duro faria o pytest abortar a COLETA INTEIRA por um modulo, em vez
# de reportar so este; o `reason` mantem o pulo visivel.
ccxt = pytest.importorskip(
    "ccxt", reason="ccxt e dependencia base; ausente so em ambiente local incompleto"
)

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
    with pytest.raises(VenueCapabilityError, match="(?i)confira as ordens abertas"):
        trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)


def test_ordem_confirmada_e_devolvida(monkeypatch) -> None:
    trader = _make(monkeypatch, {"id": "sl-1", "status": "open"})
    assert trader.place_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, is_long=True)["id"] == "sl-1"


def test_falha_apos_o_cancelamento_avisa_que_a_posicao_ficou_nua(monkeypatch) -> None:
    """`replace_stop_loss` cancela o stop vivo antes de criar o novo.

    Se a criacao falhar, a posicao fica sem stop nenhum. O erro precisa dizer
    isso: o chamador loga a mensagem e e por ela que o operador descobre.
    """
    trader = _make(monkeypatch, {"status": "rejected", "id": "x"})
    cancelados = []
    trader.cancel_order = lambda order_id, symbol=None: cancelados.append(order_id)

    with pytest.raises(VenueCapabilityError, match="(?i)sem stop|desprotegida"):
        trader.replace_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, previous_order_ref={"id": "old-sl"})
    assert cancelados == ["old-sl"], "o cancelamento ocorreu; o aviso tem de refletir isso"


def test_substituicao_bem_sucedida_nao_alarma(monkeypatch) -> None:
    trader = _make(monkeypatch, {"id": "sl-2", "status": "open"})
    trader.cancel_order = lambda order_id, symbol=None: None
    resultado = trader.replace_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, previous_order_ref={"id": "old-sl"})
    assert resultado["cancelled"] is True and resultado["order"]["id"] == "sl-2"


@pytest.mark.parametrize("erro", ["RequestTimeout", "NetworkError", "ExchangeError", "InvalidOrder", "InsufficientFunds"])
def test_erro_cru_do_ccxt_apos_cancelamento_tambem_avisa(monkeypatch, erro) -> None:
    """O aviso de posicao nua nao pode cobrir so a rejeicao estruturada.

    `create_order` levanta excecao crua do CCXT muito mais vezes do que
    devolve dict de rejeicao. Se o aviso so cobre o caso raro, o caminho
    dominante segue silencioso -- que era o proposito da correcao.
    """
    trader = _make(monkeypatch, {"id": "ok", "status": "open"})
    trader.cancel_order = lambda order_id, symbol=None: None

    def explode(*_a, **_k):
        raise getattr(ccxt, erro)("falha de rede")

    trader.client.create_order = explode
    with pytest.raises(VenueCapabilityError, match="(?i)sem stop|desprotegida"):
        trader.replace_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, previous_order_ref={"id": "old-sl"})


def test_ordem_sem_id_nao_manda_retentar_por_cima_de_stop_vivo(monkeypatch) -> None:
    """Sem id, a ordem PODE ter sido criada. Mandar tentar de novo empilharia
    um segundo stop reduce-only sobre um vivo e irrastreavel."""
    trader = _make(monkeypatch, {"status": "open"})
    trader.cancel_order = lambda order_id, symbol=None: None
    with pytest.raises(VenueCapabilityError) as exc:
        trader.replace_stop_loss("ETH/USDT:USDT", 1.0, 2000.0, previous_order_ref={"id": "old-sl"})
    msg = str(exc.value).lower()
    assert "pode ter sido criada" in msg
    assert "sem stop" not in msg, "nao pode afirmar ausencia e possivel existencia na mesma linha"
    assert "confira" in msg or "verifique" in msg
