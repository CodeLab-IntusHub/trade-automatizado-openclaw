"""Testes do provisionamento e do diagnostico (`workspace/run.py`).

Cobrem duas regressoes de plataforma encontradas no Windows: a sonda de
dependencias gastando um interpretador por modulo, e o SDK da Nado sendo
tratado como obrigatorio -- o que fazia o `setup-check` disparar `pip install`
de rede em toda execucao, numa maquina que sequer usa a Nado.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_dependency_status_usa_um_unico_subprocesso(monkeypatch) -> None:
    """Sondar N modulos nao pode custar N startups de interpretador.

    No Windows cada spawn custa ~2s; com 5 modulos o `setup-check` levava ~24s
    e estourava o timeout de 10s do proprio teste de smoke.
    """
    import workspace.run as run

    calls: list[list[str]] = []
    real_run = run.subprocess.run

    def counting_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(run.subprocess, "run", counting_run)
    status = run._dependency_status(Path(sys.executable))

    assert set(status) == set(run.PROBED_MODULES)
    assert all(isinstance(value, bool) for value in status.values())
    assert len(calls) == 1, f"esperava 1 subprocesso, houve {len(calls)}"


def test_nado_protocol_e_dependencia_opcional() -> None:
    """A skill opera Hyperliquid/CEX sem o SDK da Nado.

    Enquanto `nado_protocol` fosse obrigatorio, `setup-check` nunca ficava
    verde nessas maquinas -- e, pior, tentava um `pip install` de rede a cada
    execucao do diagnostico.
    """
    import workspace.run as run

    assert "nado_protocol" not in run.REQUIRED_MODULES
    assert "nado_protocol" in run.OPTIONAL_MODULES
    for name in ("ccxt", "pandas", "numpy", "dotenv"):
        assert name in run.REQUIRED_MODULES


def test_setup_check_nao_pede_bootstrap_por_dependencia_opcional(monkeypatch) -> None:
    import workspace.run as run

    def fake_status(python=None):
        status = {name: True for name in run.REQUIRED_MODULES}
        status.update({name: False for name in run.OPTIONAL_MODULES})
        return status

    monkeypatch.setattr(run, "_dependency_status", fake_status)
    assert run._dependencies_ready(fake_status()) is True


def test_sonda_travada_devolve_status_em_vez_de_levantar(monkeypatch) -> None:
    """O timeout existe para o diagnostico responder, nao para mata-lo."""
    import subprocess

    import workspace.run as run

    def stalled(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(run.subprocess, "run", stalled)
    status = run._dependency_status(Path(sys.executable))

    assert set(status) == set(run.PROBED_MODULES)
    assert not any(status.values())


def test_dashboard_publisher_usa_o_lock_consolidado() -> None:
    """A copia local do FileLock carregava a sonda de PID defeituosa."""
    import workspace.dashboard_publisher as publisher
    import workspace.file_lock as file_lock

    assert publisher.FileLock is file_lock.FileLock
    assert publisher.LockHeld is file_lock.LockHeld
    assert not hasattr(publisher, "_pid_is_alive")
