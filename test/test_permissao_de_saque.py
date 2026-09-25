"""O `doctor` reprova API key de CEX que pode sacar (ADR 0007, ROADMAP 1.7).

A trava que vale contra um agente com shell esta na exchange: key sem
permissao de saque. Onde a venue expoe a permissao da propria key pela API
(Binance, Bybit, OKX), o `doctor` confere e reprova se ela puder sacar. Onde nao
expoe, diz com franqueza que nao conseguiu verificar. Resposta que nao da para
ler **nao** vira "sem saque": duvida nao e seguranca.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.venues import permissao_de_saque as ps

SEM, PODE, NAO_VERIFICAVEL, ERRO = ps.SEM_SAQUE, ps.PODE_SACAR, ps.NAO_VERIFICAVEL, ps.ERRO
# A consulta real: o conftest a troca por uma sem rede em toda a suite.
CONSULTAR = ps.consultar


@pytest.mark.parametrize(
    ("venue", "resposta", "estado"),
    [
        ("binance", {"enableWithdrawals": False, "enableReading": True}, SEM),
        ("binance", {"enableWithdrawals": True}, PODE),
        ("bybit", {"retCode": 0, "result": {"readOnly": 0, "permissions": {"Wallet": ["AccountTransfer"]}}}, SEM),
        ("bybit", {"retCode": 0, "result": {"permissions": {"Wallet": ["AccountTransfer", "Withdraw"]}}}, PODE),
        ("okx", {"code": "0", "data": [{"perm": "read_only,trade"}]}, SEM),
        ("okx", {"code": "0", "data": [{"perm": "read_only,trade,withdraw"}]}, PODE),
    ],
)
def test_interpreta_a_permissao_de_saque(venue: str, resposta: dict, estado: str) -> None:
    assert ps.interpretar(venue, resposta).estado == estado


@pytest.mark.parametrize(
    ("venue", "resposta"),
    [
        ("binance", {}),
        ("binance", {"enableWithdrawals": "talvez"}),
        ("bybit", {"result": {}}),
        ("okx", {"data": []}),
        ("okx", None),
    ],
)
def test_resposta_ilegivel_nao_vira_sem_saque(venue: str, resposta: object) -> None:
    assert ps.interpretar(venue, resposta).estado == ERRO


@pytest.mark.parametrize("venue", ["kraken", "mexc", "kucoin", "bitget", "gateio"])
def test_venue_que_nao_expoe_a_permissao_e_nao_verificavel(venue: str) -> None:
    veredicto = CONSULTAR(venue, {"api_key": "k", "api_secret": "s", "api_password": ""}, sandbox=False)
    assert veredicto.estado == NAO_VERIFICAVEL
    assert "painel" in veredicto.detalhe


def test_falha_na_consulta_vira_erro_sem_vazar_credencial(monkeypatch: pytest.MonkeyPatch) -> None:
    class Quebra:
        def __init__(self, config: dict) -> None:
            self.config = config

        def sapi_get_account_apirestrictions(self) -> dict:
            raise RuntimeError(f"falhou com {self.config['secret']}")

    monkeypatch.setattr(ps, "_cliente", lambda venue, cfg: Quebra(cfg))
    veredicto = CONSULTAR("binance", {"api_key": "k", "api_secret": "SEGREDO", "api_password": ""}, sandbox=False)
    assert veredicto.estado == ERRO
    assert "SEGREDO" not in veredicto.detalhe


# --- doctor ---------------------------------------------------------------


def _doctor_com(monkeypatch: pytest.MonkeyPatch, veredicto: ps.Veredicto | None) -> dict:
    from workspace import run

    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.delenv("DEX_ID", raising=False)
    chamadas: list[str] = []

    def consultar(venue: str, credenciais: dict, *, sandbox: bool) -> ps.Veredicto:
        chamadas.append(venue)
        assert veredicto is not None
        return veredicto

    monkeypatch.setattr(ps, "consultar", consultar)
    relatorio = run.doctor()
    relatorio["_chamadas"] = chamadas
    return relatorio


def _check(relatorio: dict) -> dict | None:
    return next((c for c in relatorio["checks"] if c["name"] == "cex_key_sem_saque"), None)


def test_doctor_reprova_key_que_pode_sacar_com_bloqueio_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Por padrao e aviso (decisao do autor, 25/09); com `BLOQUEAR_SAQUE`, reprova.
    O caso padrao esta em `test_bloqueios_configuraveis.py`."""
    monkeypatch.setenv("CEX_API_KEY", "k")
    monkeypatch.setenv("CEX_API_SECRET", "s")
    monkeypatch.setenv("BLOQUEAR_SAQUE", "sim")
    relatorio = _doctor_com(monkeypatch, ps.Veredicto("binance", PODE, "a key pode sacar"))

    check = _check(relatorio)
    assert check is not None and check["ok"] is False
    # `status` sozinho nao prova nada: no ambiente de teste outros checks
    # bloqueantes ja reprovam. O que importa e este estar entre os que reprovam.
    reprovados = [c["name"] for c in relatorio["checks"] if c["name"] in relatorio["blocking_checks"] and not c["ok"]]
    assert "cex_key_sem_saque" in reprovados
    assert relatorio["status"] == "attention"


def test_doctor_aprova_key_sem_saque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CEX_API_KEY", "k")
    monkeypatch.setenv("CEX_API_SECRET", "s")
    check = _check(_doctor_com(monkeypatch, ps.Veredicto("binance", SEM, "sem saque")))
    assert check is not None and check["ok"] is True and check["verificado"] is True


@pytest.mark.parametrize("estado", [NAO_VERIFICAVEL, ERRO])
def test_doctor_diz_que_nao_verificou_sem_reprovar(monkeypatch: pytest.MonkeyPatch, estado: str) -> None:
    """Nao reprova: a falta de verificacao nao prova que a key saca. Mas diz."""
    monkeypatch.setenv("CEX_API_KEY", "k")
    monkeypatch.setenv("CEX_API_SECRET", "s")
    check = _check(_doctor_com(monkeypatch, ps.Veredicto("binance", estado, "confira no painel")))
    assert check is not None and check["ok"] is True and check["verificado"] is False
    assert "nao verificado" in check["detail"]


def test_doctor_sem_credencial_nao_consulta_a_rede(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("CEX_API_KEY", "CEX_API_SECRET", "BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(nome, raising=False)
    relatorio = _doctor_com(monkeypatch, None)
    assert relatorio["_chamadas"] == []
    assert _check(relatorio) is None
