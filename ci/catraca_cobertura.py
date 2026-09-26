"""Catraca do piso de cobertura: o piso so sobe.

Uso (na CI):
    python ci/catraca_cobertura.py ci/cobertura-piso.txt cov.json piso-da-main.txt

Reprova se a cobertura medida ficar abaixo do piso, ou se o piso da PR for
menor que o da `main`. Com folga grande, sugere subir o piso.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FOLGA_PARA_SUBIR = 2.0


def verificar(*, piso: int, piso_main: int | None, medido: float) -> tuple[list[str], list[str]]:
    erros: list[str] = []
    avisos: list[str] = []
    if piso_main is not None and piso < piso_main:
        erros.append(f"catraca: o piso so sobe -- a main tem {piso_main}%, esta PR baixa para {piso}%")
    if medido < piso:
        erros.append(f"cobertura {medido:.1f}% abaixo do piso de {piso}%")
    elif medido >= piso + FOLGA_PARA_SUBIR:
        avisos.append(f"cobertura {medido:.1f}%: suba o piso para {int(medido)} em ci/cobertura-piso.txt")
    return erros, avisos


def _ler_piso(caminho: Path) -> int | None:
    return int(caminho.read_text(encoding="utf-8").strip()) if caminho.exists() else None


def main(argv: list[str]) -> int:
    piso_arquivo, cov_json, piso_main_arquivo = (Path(a) for a in argv[:3])
    piso = _ler_piso(piso_arquivo)
    if piso is None:
        print(f"piso ausente: {piso_arquivo}")
        return 1
    medido = float(json.loads(cov_json.read_text(encoding="utf-8"))["totals"]["percent_covered"])
    erros, avisos = verificar(piso=piso, piso_main=_ler_piso(piso_main_arquivo), medido=medido)
    for aviso in avisos:
        print(f"aviso: {aviso}")
    for erro in erros:
        print(f"erro: {erro}")
    if not erros:
        print(f"ok: cobertura {medido:.1f}% >= piso {piso}%")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
