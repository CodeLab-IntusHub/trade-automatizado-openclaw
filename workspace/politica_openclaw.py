"""O OpenClaw pede aprovacao antes de executar comando? (ADR 0007, ROADMAP 1.7)

A aprovacao de execucao do OpenClaw roda fora do alcance do agente e e a trava
humana que vale. A politica efetiva e a mais restritiva entre `tools.exec` e o
arquivo de aprovacoes; a fonte e `openclaw exec-policy show --json` -- ler o
arquivo daria falso "seguro", e as versoes novas o aposentaram.

`interpretar` e puro; `consultar` roda o comando.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTEGIDO = "protegido"
REVISOR_AUTOMATICO = "revisor_automatico"
SEM_APROVACAO = "sem_aprovacao"
NAO_VERIFICAVEL = "nao_verificavel"

# Do mais seguro ao menos seguro: o pior escopo decide.
_GRAVIDADE = {PROTEGIDO: 0, REVISOR_AUTOMATICO: 1, SEM_APROVACAO: 2}
TIMEOUT_S = 10


@dataclass(frozen=True)
class Veredicto:
    estado: str
    detalhe: str


def _efetivo(escopo: dict, campo: str) -> str:
    valor = escopo.get(campo)
    return str(valor.get("effective") or "").strip().lower() if isinstance(valor, dict) else ""


def _estado_do_escopo(escopo: dict) -> str | None:
    security = _efetivo(escopo, "security")
    ask = _efetivo(escopo, "ask")
    mode = _efetivo(escopo, "mode")
    if not security:
        return None
    if security == "full" or mode == "full":
        return SEM_APROVACAO
    if security == "deny":
        return PROTEGIDO
    if mode == "auto":
        return REVISOR_AUTOMATICO
    if ask in {"", "off"}:
        return SEM_APROVACAO
    return PROTEGIDO


_DETALHE = {
    PROTEGIDO: "o OpenClaw pede aprovacao para comando fora da allowlist; confira que os comandos de trade nao estao nela",
    REVISOR_AUTOMATICO: "modo auto: o comando fora da allowlist vai a um revisor automatico antes de chegar ao operador",
    SEM_APROVACAO: "o agente executa comandos sem pedir aprovacao: na pratica, real autonomo",
}


def interpretar(payload: Any) -> Veredicto:
    politica = payload.get("effectivePolicy") if isinstance(payload, dict) else None
    escopos = politica.get("scopes") if isinstance(politica, dict) else None
    if not isinstance(escopos, list) or not escopos:
        return Veredicto(NAO_VERIFICAVEL, "saida do `openclaw exec-policy show --json` sem escopos")
    pior: tuple[str, dict] | None = None
    for escopo in escopos:
        estado = _estado_do_escopo(escopo) if isinstance(escopo, dict) else None
        if estado is None:
            return Veredicto(NAO_VERIFICAVEL, "escopo sem `security` efetivo na saida do OpenClaw")
        if pior is None or _GRAVIDADE[estado] > _GRAVIDADE[pior[0]]:
            pior = (estado, escopo)
    assert pior is not None
    estado, escopo = pior
    rotulo = escopo.get("scopeLabel") or "tools.exec"
    resumo = f"{rotulo}: security={_efetivo(escopo, 'security')} ask={_efetivo(escopo, 'ask') or '-'}"
    return Veredicto(estado, f"{_DETALHE[estado]} ({resumo})")


def _openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or str(Path.home() / ".npm-global" / "bin" / "openclaw")


def consultar() -> Veredicto:
    try:
        resultado = subprocess.run(
            [_openclaw_bin(), "exec-policy", "show", "--json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Veredicto(NAO_VERIFICAVEL, f"`openclaw exec-policy show` indisponivel ({type(exc).__name__})")
    if resultado.returncode != 0:
        return Veredicto(NAO_VERIFICAVEL, f"`openclaw exec-policy show` saiu com {resultado.returncode}")
    try:
        payload = json.loads(resultado.stdout or "")
    except ValueError:
        return Veredicto(NAO_VERIFICAVEL, "`openclaw exec-policy show --json` nao devolveu JSON")
    return interpretar(payload)
