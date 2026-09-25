"""Saque e OpenClaw sem aprovacao sao aviso; bloquear e escolha do operador.

Decisao do autor (25/09/2026): "Sacar nao e um bloqueador, somente um warning
que o usuario deve ter ciencia. Quando possivel, sempre bloquear configuravel."

- `BLOQUEAR_SAQUE`: key da CEX com saque e saque automatico da Nado passam a
  reprovar o `doctor` e a recusar comando de trade.
- `BLOQUEAR_SEM_APROVACAO`: OpenClaw que executa sem pedir aprovacao, idem.

Nao verificado nunca bloqueia: a duvida nao prova nada, e travar todo trade de
quem nao tem o `openclaw` no PATH do exec seria pior.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import politica_openclaw as po
from workspace import run
from workspace.venues import permissao_de_saque as ps

ENVS = ("BLOQUEAR_SAQUE", "BLOQUEAR_SEM_APROVACAO", "AUTO_WITHDRAW_ENABLED", "DEX_ID")


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for nome in ENVS:
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.setenv("CEX_API_KEY", "k")
    monkeypatch.setenv("CEX_API_SECRET", "s")
    return monkeypatch


def _key(monkeypatch: pytest.MonkeyPatch, estado: str) -> None:
    monkeypatch.setattr(ps, "consultar", lambda venue, cred, *, sandbox: ps.Veredicto(venue, estado, f"key {estado}"))


def _openclaw(monkeypatch: pytest.MonkeyPatch, estado: str) -> None:
    monkeypatch.setattr(po, "consultar", lambda: po.Veredicto(estado, f"openclaw {estado}"))


def _check(relatorio: dict, nome: str) -> dict | None:
    return next((c for c in relatorio["checks"] if c["name"] == nome), None)


def _reprovados(relatorio: dict) -> list[str]:
    return [c["name"] for c in relatorio["checks"] if c["name"] in relatorio["blocking_checks"] and not c["ok"]]


# --- doctor ---------------------------------------------------------------


def test_key_com_saque_e_aviso_por_padrao(ambiente) -> None:
    _key(ambiente, ps.PODE_SACAR)
    relatorio = run.doctor()
    assert _check(relatorio, "cex_key_sem_saque")["ok"] is False
    assert "cex_key_sem_saque" not in _reprovados(relatorio)


def test_key_com_saque_bloqueia_quando_o_operador_liga(ambiente) -> None:
    _key(ambiente, ps.PODE_SACAR)
    ambiente.setenv("BLOQUEAR_SAQUE", "sim")
    assert "cex_key_sem_saque" in _reprovados(run.doctor())


def test_openclaw_sem_aprovacao_e_aviso_por_padrao(ambiente) -> None:
    _openclaw(ambiente, po.SEM_APROVACAO)
    relatorio = run.doctor()
    check = _check(relatorio, "openclaw_aprovacao")
    assert check["ok"] is False and check["verificado"] is True
    assert "openclaw_aprovacao" not in _reprovados(relatorio)


@pytest.mark.parametrize("estado", [po.SEM_APROVACAO, po.REVISOR_AUTOMATICO])
def test_openclaw_sem_aprovacao_bloqueia_quando_o_operador_liga(ambiente, estado: str) -> None:
    _openclaw(ambiente, estado)
    ambiente.setenv("BLOQUEAR_SEM_APROVACAO", "sim")
    assert "openclaw_aprovacao" in _reprovados(run.doctor())


def test_openclaw_nao_verificado_nao_bloqueia(ambiente) -> None:
    _openclaw(ambiente, po.NAO_VERIFICAVEL)
    ambiente.setenv("BLOQUEAR_SEM_APROVACAO", "sim")
    relatorio = run.doctor()
    check = _check(relatorio, "openclaw_aprovacao")
    assert check["ok"] is True and check["verificado"] is False
    assert "openclaw_aprovacao" not in _reprovados(relatorio)


def test_saque_automatico_da_nado_e_aviso(ambiente) -> None:
    ambiente.setenv("AUTO_WITHDRAW_ENABLED", "true")
    relatorio = run.doctor()
    assert _check(relatorio, "saque_automatico")["ok"] is False
    assert "saque_automatico" not in _reprovados(relatorio)
    ambiente.setenv("BLOQUEAR_SAQUE", "sim")
    assert "saque_automatico" in _reprovados(run.doctor())


def test_saque_automatico_segue_o_que_o_script_le(ambiente) -> None:
    """O `auto_trade_nado.py` so liga com `true` literal; `sim` fica desligado.
    Avisar de um saque que nao acontece ensinaria o operador a ignorar o aviso."""
    ambiente.setenv("AUTO_WITHDRAW_ENABLED", "sim")
    assert _check(run.doctor(), "saque_automatico") is None


def test_valor_invalido_no_bloqueio_reprova_nomeando_a_variavel(ambiente) -> None:
    ambiente.setenv("BLOQUEAR_SAQUE", "talvez")
    relatorio = run.doctor()
    check = _check(relatorio, "config_bloqueios")
    assert check is not None and "BLOQUEAR_SAQUE" in check["detail"]
    assert "config_bloqueios" in _reprovados(relatorio)


# --- comando de trade -----------------------------------------------------


@pytest.fixture
def trade(ambiente) -> list:
    ambiente.setenv("AUTORIZAR_TRADE_REAL", "sim")
    ambiente.setenv("DELTA_NEUTRAL_NO_BOOTSTRAP", "1")
    executados: list = []
    ambiente.setattr(run.subprocess, "call", lambda cmd, **k: executados.append(cmd) or 0)
    return executados


ABRIR = ["abrir", "ETH/USDT", "--margem-usd", "20"]


def test_trade_segue_com_key_que_saca_por_padrao(trade, ambiente) -> None:
    _key(ambiente, ps.PODE_SACAR)
    assert run._run_cli(ABRIR) == 0
    assert len(trade) == 1


def test_trade_recusado_quando_bloqueio_de_saque_ligado(trade, ambiente, capsys) -> None:
    _key(ambiente, ps.PODE_SACAR)
    ambiente.setenv("BLOQUEAR_SAQUE", "sim")
    assert run._run_cli(ABRIR) == 2
    assert trade == []
    assert "BLOQUEAR_SAQUE" in capsys.readouterr().out


def test_trade_recusado_quando_openclaw_sem_aprovacao_e_bloqueio_ligado(trade, ambiente) -> None:
    _openclaw(ambiente, po.SEM_APROVACAO)
    ambiente.setenv("BLOQUEAR_SEM_APROVACAO", "sim")
    assert run._run_cli(ABRIR) == 2
    assert trade == []


def test_trade_segue_quando_nao_da_para_verificar(trade, ambiente, capsys) -> None:
    _key(ambiente, ps.NAO_VERIFICAVEL)
    _openclaw(ambiente, po.NAO_VERIFICAVEL)
    ambiente.setenv("BLOQUEAR_SAQUE", "sim")
    ambiente.setenv("BLOQUEAR_SEM_APROVACAO", "sim")
    assert run._run_cli(ABRIR) == 0
    assert "nao verificado" in capsys.readouterr().err


def test_simulacao_nao_consulta_nada(trade, ambiente) -> None:
    ambiente.setenv("BLOQUEAR_SAQUE", "sim")

    def proibido(*a, **k):
        raise AssertionError("simulacao nao deve consultar a venue")

    ambiente.setattr(ps, "consultar", proibido)
    assert run._run_cli([*ABRIR, "--simular"]) == 0
