"""A confirmacao de operacao real vira rastro de auditoria (ADR 0007, ROADMAP 1.7).

`AUTORIZAR_TRADE_REAL` nao e trava: o agente monta o comando e pode definir a
variavel. O que ela pode ser e rastro -- o registro de que, naquela execucao, o
agente decidiu operar real. O codigo aceita quatro variaveis como
equivalentes; o registro olha para todas, ou uma execucao autorizada por outra
ficaria sem rastro.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import cli

VARIAVEIS = ("AUTORIZAR_TRADE_REAL", "CONFIRMAR_TRADE_REAL", "TRADE_AUTOMATIZADO_CONFIRM_LIVE", "DELTA_NEUTRAL_CONFIRM_LIVE")


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("DELTA_NEUTRAL_LOG_DIR", str(tmp_path))
    return tmp_path


def _registros(log_dir: Path) -> list[dict]:
    arquivo = log_dir / cli.AUDIT_FILE_NAME
    if not arquivo.exists():
        return []
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("variavel", VARIAVEIS)
def test_cada_variavel_de_confirmacao_deixa_rastro(log_dir: Path, monkeypatch: pytest.MonkeyPatch, variavel: str) -> None:
    monkeypatch.setenv(variavel, "sim")
    cli._early_live_confirmation_guard(["abrir", "ETH/USDT", "--margem-usd", "20"])
    registros = _registros(log_dir)
    assert len(registros) == 1
    assert registros[0]["comando"] == "abrir"
    assert registros[0]["variaveis"] == [variavel]
    assert registros[0]["args"] == ["ETH/USDT", "--margem-usd", "20"]
    assert registros[0]["ts"]


def test_simulacao_nao_e_registrada(log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTORIZAR_TRADE_REAL", "sim")
    cli._early_live_confirmation_guard(["abrir", "ETH/USDT", "--simular"])
    assert _registros(log_dir) == []


def test_sem_confirmacao_nao_registra_e_recusa(log_dir: Path) -> None:
    with pytest.raises(SystemExit):
        cli._early_live_confirmation_guard(["abrir", "ETH/USDT"])
    assert _registros(log_dir) == []


def test_comando_de_leitura_nao_e_registrado(log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTORIZAR_TRADE_REAL", "sim")
    cli._early_live_confirmation_guard(["status"])
    assert _registros(log_dir) == []


def test_falha_ao_gravar_nao_derruba_o_comando(log_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """E rastro, nao trava: sem onde gravar, avisa e segue."""
    monkeypatch.setenv("AUTORIZAR_TRADE_REAL", "sim")
    monkeypatch.setenv("DELTA_NEUTRAL_LOG_DIR", str(log_dir / "arquivo-no-lugar-do-dir"))
    (log_dir / "arquivo-no-lugar-do-dir").write_text("x", encoding="utf-8")
    cli._early_live_confirmation_guard(["abrir", "ETH/USDT"])
    assert "auditoria" in capsys.readouterr().err
