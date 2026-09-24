"""O que vai dentro do `.skill` é o que o bot de cada operador recebe.

`build.py` montava o pacote com `ROOT.rglob("*")` menos uma lista fixa de
pastas. O critério era **o que está no disco**, não o que está no repositório.
Medido numa máquina de desenvolvimento em 24/09/2026: dos 239 arquivos que iriam
no pacote, **104 estavam fora do git** — 74 do `.ua/` (o grafo do código e o
inventário de variáveis de ambiente de uma auditoria), 18 do cache do mypy, 12
do cache do ruff. Qualquer `settings.local.json` que um operador deixasse na
raiz iria junto.

O pacote passa a conter só o que o git rastreia — e, entre isso, nada que seja
instrução de desenvolvimento do repositório (`CLAUDE.md`), que descreve a
organização e não pertence ao produto entregue.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build  # noqa: E402


def _rastreados() -> set[str]:
    saida = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return set(saida.stdout.splitlines())


def test_todo_arquivo_do_pacote_esta_no_git() -> None:
    """O critério é o repositório, não o disco da máquina que empacota."""
    pacote = build.arquivos_do_pacote()
    fora = sorted(set(pacote) - _rastreados())
    assert fora == [], f"arquivo fora do git entraria no pacote: {fora[:10]}"


def test_arquivo_solto_no_disco_nao_entra(tmp_path: Path) -> None:
    """A garantia não pode depender de a máquina estar limpa: um arquivo
    plantado no repositório, sem estar no git, não entra."""
    plantado = ROOT / "settings.local.json"
    existia = plantado.exists()
    if existia:
        pytest.skip("já existe um settings.local.json na raiz desta máquina")
    plantado.write_text('{"segredo_do_operador": "nao-deveria-ir"}', encoding="utf-8")
    try:
        assert "settings.local.json" not in build.arquivos_do_pacote()
    finally:
        plantado.unlink()


def test_instrucao_de_desenvolvimento_nao_entra_no_pacote() -> None:
    """`CLAUDE.md` descreve a organização e o repositório — não é produto.

    Testado no filtro, e não na lista final: enquanto o repositório não tiver
    `CLAUDE.md`, uma asserção sobre a lista passaria por vacuidade, sem provar
    nada.
    """
    assert build.entra_no_pacote("CLAUDE.md") is False
    assert build.entra_no_pacote("workspace/CLAUDE.md") is False
    assert build.entra_no_pacote("SKILL.md") is True
    assert build.entra_no_pacote("workspace/run.py") is True
    assert build.entra_no_pacote(".env") is False
    assert build.entra_no_pacote("dist/x.skill") is False


def test_o_que_a_skill_precisa_continua_no_pacote() -> None:
    """A correção não pode esvaziar o pacote."""
    pacote = set(build.arquivos_do_pacote())
    for obrigatorio in build.REQUIRED_FILES:
        assert obrigatorio in pacote, obrigatorio
    for pasta in build.REQUIRED_DIRS:
        assert any(p.startswith(pasta + "/") for p in pacote), pasta
    assert "workspace/run.py" in pacote


def test_a_lista_do_pacote_aplica_o_filtro(tmp_path: Path, monkeypatch) -> None:
    """O filtro precisa ser **usado**, não só existir.

    Uma mutação que removia a chamada a `entra_no_pacote` passava por todos os
    outros testes: hoje nenhum arquivo rastreado cai no filtro, então a lista
    real não o exercita. Quando o `CLAUDE.md` for commitado, isso viraria
    vazamento. Aqui a saída do git é injetada, com o que precisa ficar de fora.
    """
    for nome in ("SKILL.md", "CLAUDE.md", ".env"):
        (tmp_path / nome).write_text("x", encoding="utf-8")

    class _Saida:
        returncode = 0
        stdout = chr(0).join(["SKILL.md", "CLAUDE.md", ".env", ""]).encode("utf-8")

    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: _Saida())
    assert build.arquivos_do_pacote() == ["SKILL.md"]

