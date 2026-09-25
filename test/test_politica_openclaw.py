"""O `doctor` diz se o OpenClaw pede aprovacao antes de executar (ADR 0007, 1.7).

A aprovacao de execucao do OpenClaw e a trava humana que o agente nao alcanca.
A politica efetiva e a mais restritiva entre `tools.exec` e o arquivo de
aprovacoes; a fonte e `openclaw exec-policy show --json`, nao um arquivo --
as versoes novas aposentaram o `exec-approvals.json`.

Decisao do autor (25/09/2026): sem aprovacao e aviso, nao bloqueio; bloquear e
escolha do operador (`BLOQUEAR_SEM_APROVACAO`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import politica_openclaw as po

# A consulta real: o conftest a troca por uma sem subprocess em toda a suite.
CONSULTAR = po.consultar

# Saida de `openclaw exec-policy show --json` de uma instancia real (25/09/2026).
INSTANCIA_DO_AUTOR = {
    "configPath": "/home/node/.openclaw/openclaw.json",
    "approvalsPath": "/home/node/.openclaw/exec-approvals.json",
    "approvalsExists": True,
    "effectivePolicy": {
        "scopes": [
            {
                "scopeLabel": "tools.exec",
                "host": {"requested": "auto", "requestedSource": "OpenClaw default (auto)"},
                "mode": {"requested": "full", "effective": "full"},
                "security": {"requested": "full", "host": "full", "effective": "full"},
                "ask": {"requested": "on-miss", "host": "on-miss", "effective": "on-miss"},
                "askFallback": {"effective": "deny", "source": "OpenClaw default (deny)"},
                "runtimeApprovalsSource": "local-file",
            }
        ]
    },
}


def _escopo(security: str, ask: str, mode: str | None = None) -> dict:
    escopo = {"scopeLabel": "tools.exec", "security": {"effective": security}, "ask": {"effective": ask}}
    if mode:
        escopo["mode"] = {"effective": mode}
    return {"effectivePolicy": {"scopes": [escopo]}}


def test_instancia_real_em_full_e_sem_aprovacao() -> None:
    veredicto = po.interpretar(INSTANCIA_DO_AUTOR)
    assert veredicto.estado == po.SEM_APROVACAO
    assert "security=full" in veredicto.detalhe


@pytest.mark.parametrize(
    ("payload", "estado"),
    [
        (_escopo("allowlist", "on-miss", "ask"), po.PROTEGIDO),
        (_escopo("allowlist", "always"), po.PROTEGIDO),
        (_escopo("deny", "off", "deny"), po.PROTEGIDO),
        # allowlist sem ask: o que esta na allowlist roda sem pedir.
        (_escopo("allowlist", "off", "allowlist"), po.SEM_APROVACAO),
        # auto: o erro de allowlist vai a um revisor automatico antes do humano.
        (_escopo("allowlist", "on-miss", "auto"), po.REVISOR_AUTOMATICO),
    ],
)
def test_interpreta_os_modos(payload: dict, estado: str) -> None:
    assert po.interpretar(payload).estado == estado


def test_o_pior_escopo_decide() -> None:
    payload = _escopo("allowlist", "on-miss", "ask")
    payload["effectivePolicy"]["scopes"].append(_escopo("full", "off", "full")["effectivePolicy"]["scopes"][0])
    assert po.interpretar(payload).estado == po.SEM_APROVACAO


@pytest.mark.parametrize("payload", [None, {}, {"effectivePolicy": {"scopes": []}}, _escopo("", "")])
def test_saida_ilegivel_e_nao_verificavel(payload: object) -> None:
    assert po.interpretar(payload).estado == po.NAO_VERIFICAVEL


def _run_devolve(monkeypatch: pytest.MonkeyPatch, *, rc: int = 0, stdout: str = "", erro: Exception | None = None) -> list:
    chamadas: list = []

    def fake_run(cmd, **kwargs):
        chamadas.append(cmd)
        if erro:
            raise erro
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")

    monkeypatch.setattr(po.subprocess, "run", fake_run)
    return chamadas


def test_consulta_usa_o_exec_policy_show_json(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = _run_devolve(monkeypatch, stdout=json.dumps(INSTANCIA_DO_AUTOR))
    assert CONSULTAR().estado == po.SEM_APROVACAO
    assert chamadas[0][1:] == ["exec-policy", "show", "--json"]


@pytest.mark.parametrize(
    "falha",
    [
        {"erro": FileNotFoundError("openclaw")},
        {"erro": subprocess.TimeoutExpired("openclaw", 10)},
        {"rc": 1},
        {"stdout": "nao e json"},
    ],
)
def test_falha_na_consulta_e_nao_verificavel(monkeypatch: pytest.MonkeyPatch, falha: dict) -> None:
    _run_devolve(monkeypatch, **falha)
    assert CONSULTAR().estado == po.NAO_VERIFICAVEL
