"""Testes do lock de arquivo cross-platform (`workspace/file_lock.py`)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.file_lock import (
    STALE_UNPARSABLE_GRACE_SECONDS,
    FileLock,
    LockHeld,
    pid_is_alive,
)


def test_lock_cria_e_remove_o_arquivo(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"
    with FileLock(lock_path):
        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
    assert not lock_path.exists()


def test_lock_reentrante_do_mesmo_processo_e_erro(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"
    with FileLock(lock_path):
        with pytest.raises(LockHeld):
            with FileLock(lock_path):
                pass


def test_lock_orfao_de_pid_morto_e_recuperado(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=30)
    lock_path.write_text(str(dead.pid), encoding="utf-8")
    with FileLock(lock_path):
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
    assert not lock_path.exists()


def test_lock_recem_criado_sem_pid_nao_e_roubado(tmp_path: Path) -> None:
    """Entre o `O_EXCL` e a escrita do PID existe uma janela.

    Um concorrente que leia o arquivo nessa janela ve string vazia. Tratar isso
    como orfao deixaria dois processos com o mesmo lock -- e, no Windows, o
    `unlink` do arquivo ainda aberto escapa como `PermissionError`, que o
    chamador nao espera.
    """
    lock_path = tmp_path / "state.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with pytest.raises(LockHeld):
            with FileLock(lock_path):
                pass
    finally:
        os.close(fd)


def test_lock_vazio_e_antigo_e_recuperado(tmp_path: Path) -> None:
    """Passado o periodo de graca, um lock ilegivel e mesmo lixo de crash."""
    lock_path = tmp_path / "state.lock"
    lock_path.write_text("", encoding="utf-8")
    old_time = time.time() - (STALE_UNPARSABLE_GRACE_SECONDS + 5)
    os.utime(lock_path, (old_time, old_time))
    with FileLock(lock_path):
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_timeout_expira_com_lock_vivo(tmp_path: Path) -> None:
    lock_path = tmp_path / "state.lock"
    with FileLock(lock_path):
        started = time.monotonic()
        with pytest.raises(LockHeld):
            with FileLock(lock_path, timeout=0.3, poll_interval=0.02):
                pass
        assert time.monotonic() - started >= 0.25


def test_pid_is_alive_reporta_pid_morto_como_morto(tmp_path: Path) -> None:
    """No Windows `os.kill(pid, 0)` nao levanta para PID morto: reportaria vivo.

    Esse e o defeito real -- um lock orfao nunca seria recuperado. A sonda tem
    de distinguir morto de vivo sem depender de sinal.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert pid_is_alive(child.pid) is True
        time.sleep(0.2)
        assert child.poll() is None, "a sonda de liveness matou o processo"
    finally:
        child.kill()
        child.wait(timeout=10)
    assert pid_is_alive(child.pid) is False


def test_pid_invalido_nunca_esta_vivo() -> None:
    assert pid_is_alive(0) is False
    assert pid_is_alive(-1) is False
