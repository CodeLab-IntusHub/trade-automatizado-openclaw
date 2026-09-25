"""Nenhum doc de operador elege venue nem modo; o onboarding diz o que protege.

O codigo deixou de ter venue e modo padrao na v1.9.0 (ROADMAP 1.6), mas o
`SKILL.md` -- o que o agente de cada bot le -- ainda descrevia "Nado DEX/Kraken
CEX como defaults", e o questionario mandava usar `DEX_ID=nado CEX_ID=kraken`
como "default seguro" quando o operador nao escolhesse: o agente reintroduziria
pelo texto o padrao que o codigo tirou.

O ADR 0007 decidiu os modos de operacao (analise, real com aprovacao, real
autonomo) e que a skill sempre sugere o 1Password. O ROADMAP 1.7 pede que o
onboarding diga ao operador qual modo ele usa e o que o protege.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _docs_de_operador() -> list[Path]:
    docs = [ROOT / nome for nome in ("SKILL.md", "README.md", "INSTALL.md", "skill.json")]
    docs += sorted((ROOT / "references").glob("*.md"))
    docs += sorted((ROOT / "doc referencia").glob("*.md"))
    return docs


ELEGE_VENUE = (
    # "default" de parametro (stop, notional, nome de subconta) e legitimo;
    # o que nao pode e o default de venue.
    r"default seguro[^\n]{0,20}(nado|kraken|dex_id|cex_id)",
    r"defaults?\s+nado",
    r"\b(nado|kraken)\b[^\n;]{0,30}como defaults?\b",
    r"default\s+(cex|dex)\b",
    r"requer somente (kraken|nado)",
    r"(é|e) apenas o default",
    # "Por padrão a skill usa `DEX_ID=nado`": o padrao antes do valor (achado do review da #43).
    r"padr(ã|a)o[^\n]{0,40}\b(dex_id|cex_id)\s*=\s*(nado|kraken)\b",
    r"\b(dex_id|cex_id)\s*=\s*(nado|kraken)\b[^\n]{0,30}(padr(ã|a)o|default)",
)


@pytest.mark.parametrize("doc", _docs_de_operador(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_doc_de_operador_nao_elege_venue(doc: Path) -> None:
    texto = doc.read_text(encoding="utf-8")
    achados = [
        f"{doc.name}:{texto.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
        for padrao in ELEGE_VENUE
        for m in re.finditer(padrao, texto, flags=re.IGNORECASE)
    ]
    assert achados == []


MODOS = ("análise", "real com aprovação", "real autônomo")


@pytest.mark.parametrize("doc", ["SKILL.md", "references/onboarding-questionario.md"])
def test_onboarding_descreve_os_modos_e_sugere_1password(doc: str) -> None:
    texto = (ROOT / doc).read_text(encoding="utf-8").lower()
    assert [m for m in MODOS if m not in texto] == []
    assert "1password" in texto
    assert "tools.exec" in texto


def test_payload_do_onboarding_pergunta_o_modo_e_sugere_1password() -> None:
    from workspace import first_run_setup

    payload = first_run_setup.DEFAULT_PAYLOAD
    pergunta = next(q for q in payload["question_flow"] if q["field"] == "autonomy_mode")
    assert pergunta["options"] == ["analise", "real_com_aprovacao", "real_autonomo"]
    # Analise e o modo de toda instalacao ate o operador escolher outro (ADR 0007).
    assert pergunta["default"] == "analise"
    assert payload["state"]["autonomy_mode"] == "analise"
    assert "1Password" in payload["credential_guidance"]["recommended_secret_manager"]
    assert "1Password" in json.dumps(payload, ensure_ascii=False)


def test_confirmacao_de_trade_real_nao_e_apresentada_como_trava() -> None:
    """ADR 0007: `AUTORIZAR_TRADE_REAL` e rastro de auditoria, nao trava --
    o agente monta o comando e pode definir a variavel."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "bloqueados pelo wrapper até definir" not in readme
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "não é trava" in skill
