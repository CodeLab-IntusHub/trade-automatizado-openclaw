"""`doc referencia/` é linkado pelo `INSTALL.md`: seus links precisam resolver.

A pasta ficou congelada na v1.2.0 com o índice apontando para `README.md`,
`INSTALL.md` e `SKILL.md` como se estivessem dentro dela. Este teste trava os
links relativos de todos os arquivos da pasta, inclusive o histórico.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "doc referencia"
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def _links_relativos(arquivo: Path) -> list[str]:
    texto = arquivo.read_text(encoding="utf-8")
    return [alvo for alvo in LINK.findall(texto) if "://" not in alvo]


def test_os_links_de_doc_referencia_resolvem() -> None:
    arquivos = sorted(PASTA.rglob("*.md"))
    assert arquivos, "doc referencia/ vazia -- o teste não exercita nada"
    quebrados = [
        f"{arquivo.relative_to(ROOT)} -> {alvo}"
        for arquivo in arquivos
        for alvo in _links_relativos(arquivo)
        if not (arquivo.parent / unquote(alvo)).exists()
    ]
    assert quebrados == []


def test_o_install_aponta_para_a_pasta() -> None:
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    alvos = [unquote(a) for a in LINK.findall(install) if "doc" in a]
    assert "doc referencia/" in alvos
    assert all((ROOT / alvo).exists() for alvo in alvos)


def test_o_indice_lista_todos_os_arquivos_da_pasta() -> None:
    indice = PASTA / "00-indice.md"
    listados = {unquote(alvo) for alvo in _links_relativos(indice)}
    for arquivo in PASTA.rglob("*.md"):
        if arquivo != indice:
            assert arquivo.relative_to(PASTA).as_posix() in listados, arquivo.name
