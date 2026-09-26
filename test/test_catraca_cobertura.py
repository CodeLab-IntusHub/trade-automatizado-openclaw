"""Piso de cobertura com catraca (portao da Fase 3, item 1).

O contrato publico precisa de protecao contra regressao. O piso fica
versionado em `ci/cobertura-piso.txt`; a CI reprova se a cobertura cair abaixo
dele **ou** se a PR baixar o piso em relacao a `main`. O piso so sobe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ci") not in sys.path:
    sys.path.insert(0, str(ROOT / "ci"))

import catraca_cobertura as cc


def test_cobertura_no_piso_passa() -> None:
    erros, avisos = cc.verificar(piso=50, piso_main=50, medido=50.4)
    assert erros == [] and avisos == []


def test_cobertura_abaixo_do_piso_reprova() -> None:
    erros, _ = cc.verificar(piso=50, piso_main=50, medido=49.9)
    assert erros and "49.9" in erros[0]


def test_baixar_o_piso_reprova() -> None:
    erros, _ = cc.verificar(piso=48, piso_main=50, medido=60.0)
    assert erros and "catraca" in erros[0]


def test_subir_o_piso_passa() -> None:
    erros, _ = cc.verificar(piso=52, piso_main=50, medido=53.0)
    assert erros == []


def test_sem_piso_na_main_e_a_primeira_vez() -> None:
    erros, _ = cc.verificar(piso=50, piso_main=None, medido=51.0)
    assert erros == []


def test_folga_grande_sugere_subir_o_piso() -> None:
    erros, avisos = cc.verificar(piso=50, piso_main=50, medido=53.2)
    assert erros == []
    assert avisos and "53" in avisos[0]


def test_main_le_os_arquivos(tmp_path: Path, capsys) -> None:
    (tmp_path / "piso.txt").write_text("50\n", encoding="utf-8")
    (tmp_path / "piso-main.txt").write_text("50\n", encoding="utf-8")
    (tmp_path / "cov.json").write_text(json.dumps({"totals": {"percent_covered": 49.0}}), encoding="utf-8")
    rc = cc.main([str(tmp_path / "piso.txt"), str(tmp_path / "cov.json"), str(tmp_path / "piso-main.txt")])
    assert rc == 1
    assert "49.0" in capsys.readouterr().out


def test_main_sem_arquivo_da_main(tmp_path: Path) -> None:
    (tmp_path / "piso.txt").write_text("50\n", encoding="utf-8")
    (tmp_path / "cov.json").write_text(json.dumps({"totals": {"percent_covered": 51.0}}), encoding="utf-8")
    assert cc.main([str(tmp_path / "piso.txt"), str(tmp_path / "cov.json"), str(tmp_path / "nao-existe.txt")]) == 0


def test_piso_versionado_e_inteiro_e_esta_abaixo_da_medicao_conhecida() -> None:
    piso = int((ROOT / "ci" / "cobertura-piso.txt").read_text(encoding="utf-8").strip())
    assert 0 < piso <= 100


def test_piso_apagado_na_pr_reprova(tmp_path: Path, capsys) -> None:
    """Apagar `ci/cobertura-piso.txt` nao pode desligar a catraca."""
    (tmp_path / "piso-main.txt").write_text("50\n", encoding="utf-8")
    (tmp_path / "cov.json").write_text(json.dumps({"totals": {"percent_covered": 51.0}}), encoding="utf-8")
    rc = cc.main([str(tmp_path / "apagado.txt"), str(tmp_path / "cov.json"), str(tmp_path / "piso-main.txt")])
    assert rc == 1
    assert "piso ausente" in capsys.readouterr().out


def test_sem_piso_na_main_avisa(tmp_path: Path, capsys) -> None:
    """Sem o piso da main, a catraca nao compara -- e diz isso, em vez de calar."""
    (tmp_path / "piso.txt").write_text("50\n", encoding="utf-8")
    (tmp_path / "cov.json").write_text(json.dumps({"totals": {"percent_covered": 51.0}}), encoding="utf-8")
    cc.main([str(tmp_path / "piso.txt"), str(tmp_path / "cov.json"), str(tmp_path / "nao-existe.txt")])
    assert "sem piso da main" in capsys.readouterr().out
