"""O modo de execucao e escolha do operador, como a venue.

Ate a v1.8.0, `abrir` sem modo virava `hedged` -- abria as duas pernas. O modo
nao e deduzido pelo que tem credencial: acrescentar uma chave mudaria o modo
sozinho no ciclo seguinte. Sem modo, o comando que abre ordem para e sugere os
modos que combinam com as venues escolhidas; leitura e diagnostico seguem.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import cli
from workspace.venues.config import VenueSelection, modos_compativeis

ENVS = (
    "EXECUTION_MODE",
    "DEFAULT_EXECUTION_MODE",
    "TRADE_EXECUTION_MODE",
    "DEX_ID",
    "TRADE_DEX_ID",
    "PRIMARY_DEX",
    "CEX_ID",
    "TRADE_CEX_ID",
    "PRIMARY_CEX",
)


@pytest.fixture
def sem_modo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ENVS:
        monkeypatch.delenv(nome, raising=False)


@pytest.mark.parametrize(
    ("dex", "cex", "esperado"),
    [
        ("hyperliquid", "kraken", ["hedged", "dex_only", "cex_only"]),
        ("", "bybit", ["cex_only"]),
        ("nado", "", ["dex_only"]),
        ("", "", []),
    ],
)
def test_modos_compativeis_seguem_as_venues(
    dex: str, cex: str, esperado: list[str]
) -> None:
    assert modos_compativeis(VenueSelection(dex_id=dex, cex_id=cex)) == esperado


def test_abrir_sem_modo_para_e_sugere(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "bybit")

    def nao_monta(*a: object, **k: object) -> None:
        raise AssertionError("abriu motor sem modo escolhido")

    monkeypatch.setattr(cli, "build_engine", nao_monta)
    args = SimpleNamespace(side="long", execution_mode=None)
    with pytest.raises(SystemExit) as erro:
        cli.cmd_open(args)
    mensagem = str(erro.value)
    assert "EXECUTION_MODE" in mensagem
    assert "cex_only" in mensagem
    assert "hedged" not in mensagem


def test_abrir_com_modo_do_env_nao_para_na_escolha(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXECUTION_MODE", "cex_only")
    monkeypatch.setenv("CEX_ID", "bybit")
    montado = {}

    def marca(*a: object, **k: object) -> None:
        montado["ok"] = True
        raise SystemExit("parou depois da escolha do modo")

    monkeypatch.setattr(cli, "build_engine", marca)
    args = SimpleNamespace(side="long", execution_mode=None)
    with pytest.raises(SystemExit):
        cli.cmd_open(args)
    assert montado.get("ok"), "o modo do env nao foi aceito"


def _doctor(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    from workspace import run

    monkeypatch.setattr(run, "_ensure_venv_ready", dict)
    monkeypatch.setattr(
        run,
        "_dependency_status",
        lambda python=None: dict.fromkeys(run.PROBED_MODULES, True),
    )
    return {c["name"]: c for c in run.doctor()["checks"]}


def test_doctor_avisa_modo_nao_escolhido(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workspace import run

    monkeypatch.setenv("CEX_ID", "bybit")
    checks = _doctor(monkeypatch)
    assert checks["modo_execucao"]["ok"] is False
    assert "cex_only" in checks["modo_execucao"]["detail"]
    # leitura e diagnostico rodam sem modo: nao bloqueia
    assert "modo_execucao" not in run.BLOCKING_CHECKS


def test_doctor_acusa_modo_incompativel_com_as_venues(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "bybit")
    monkeypatch.setenv("EXECUTION_MODE", "hedged")
    checks = _doctor(monkeypatch)
    assert checks["modo_execucao"]["ok"] is False
    assert "DEX" in checks["modo_execucao"]["detail"]


def test_doctor_aceita_modo_compativel(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "bybit")
    monkeypatch.setenv("EXECUTION_MODE", "somente-cex")
    checks = _doctor(monkeypatch)
    assert checks["modo_execucao"]["ok"] is True


def test_relatorio_nao_inventa_modo(
    sem_modo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workspace import run

    monkeypatch.setattr(run, "_ensure_venv_ready", dict)
    relatorio = run.setup_check()
    assert relatorio["safe_defaults"]["execution_mode"] == ""


def test_env_example_nao_escolhe_modo() -> None:
    exemplo = (ROOT / "workspace" / ".env.example").read_text(encoding="utf-8")
    linha = next(li for li in exemplo.splitlines() if li.startswith("EXECUTION_MODE="))
    assert linha.split("=", 1)[1].split("#", 1)[0].strip() == ""


def test_todo_setup_ativo_e_direcional_ou_hedgeado_por_natureza() -> None:
    """A exigencia de modo no setup-live depende destas duas categorias: um setup
    fora das duas escaparia do bloqueio de live sem modo."""
    from workspace.core.setups import (
        ACTIVE_SETUP_KEYS,
        DIRECTIONAL_SETUP_KEYS,
        HEDGED_ONLY_SETUP_KEYS,
    )

    assert set(ACTIVE_SETUP_KEYS) <= set(DIRECTIONAL_SETUP_KEYS) | set(
        HEDGED_ONLY_SETUP_KEYS
    )
    assert not set(DIRECTIONAL_SETUP_KEYS) & set(HEDGED_ONLY_SETUP_KEYS)
