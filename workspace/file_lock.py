"""Lock de arquivo cross-platform, sem `fcntl`.

`fcntl` so existe em Unix, e o Windows e alvo suportado da skill (`run.py`
trata `os.name == "nt"` ao provisionar o venv). Este modulo consolida a
estrategia de lock que ja era usada pelo `dashboard_publisher`: um arquivo
criado com `O_EXCL` contendo o PID do dono, com recuperacao de lock orfao
quando o dono morreu.

O lock e sempre exclusivo. Nao existe modo compartilhado: a escrita do state
file e atomica (`os.replace`), entao leitor concorrente nunca ve arquivo pela
metade e nao precisa de lock proprio.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEFAULT_POLL_INTERVAL = 0.05
# Um lock ilegivel (sem PID) pode ser um dono legitimo que ainda nao escreveu o
# seu -- ha uma janela entre o `O_EXCL` e o `write`. So depois desta idade ele e
# tratado como lixo de crash.
STALE_UNPARSABLE_GRACE_SECONDS = 10.0

__all__ = [
    "STALE_UNPARSABLE_GRACE_SECONDS",
    "FileLock",
    "LockHeld",
    "pid_is_alive",
]


class LockHeld(RuntimeError):
    """O lock pertence a outro processo vivo."""


if sys.platform == "win32":  # pragma: no cover - especifico de plataforma

    def pid_is_alive(pid: int) -> bool:
        """Sonda liveness consultando o estado real do processo.

        `os.kill(pid, 0)` NAO serve no Windows: o sinal 0 e CTRL_C_EVENT, que
        cai no ramo de evento de console e **nao levanta** para um PID que ja
        morreu. A sonda reportaria qualquer processo morto como vivo, e um
        lock orfao nunca seria recuperado.
        """
        if pid <= 0:
            return False
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Sem permissao significa que o processo existe.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # na duvida, trata como vivo e nao rouba o lock
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

else:

    def pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


class FileLock:
    """Lock exclusivo entre processos.

    `timeout=None` (default) falha imediatamente com `LockHeld` se o lock
    estiver tomado. `timeout=N` espera ate N segundos antes de desistir.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        timeout: float | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.poll_interval = max(float(poll_interval), 0.001)
        self.fd: int | None = None

    def _try_acquire(self) -> bool:
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(self.fd, str(os.getpid()).encode("ascii"))
        return True

    def _owner_pid(self) -> int | None:
        """PID do dono, ou None se o arquivo ainda nao tem um legivel."""
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _reclaim_if_orphan(self) -> bool:
        """Remove o lock se o dono morreu. Retorna True se removeu.

        Duas armadilhas tratadas aqui:

        - Um lock sem PID legivel pode ser um dono legitimo que ainda nao
          escreveu o seu. So e considerado lixo depois do periodo de graca.
        - Entre decidir "orfao" e apagar, outro processo pode ter apagado e
          recriado o arquivo. Apagar as cegas destruiria o lock novo, com dois
          processos se achando donos. Por isso a identidade do arquivo e
          reconferida imediatamente antes do unlink.
        """
        try:
            before = self.path.stat()
        except OSError:
            return True  # sumiu no caminho: ha o que tentar de novo

        owner = self._owner_pid()
        if owner is None:
            age = time.time() - before.st_mtime
            if age < STALE_UNPARSABLE_GRACE_SECONDS:
                return False
        elif pid_is_alive(owner):
            return False

        try:
            after = self.path.stat()
            if (after.st_ino, after.st_mtime) != (before.st_ino, before.st_mtime):
                return False  # outro processo recriou: nao e o arquivo que inspecionei
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # No Windows, apagar arquivo aberto por outro processo levanta
            # PermissionError -- sinal de dono vivo, nao de orfao.
            return False
        return True

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = None if self.timeout is None else time.monotonic() + self.timeout
        while True:
            if self._try_acquire():
                return self
            if self._reclaim_if_orphan() and self._try_acquire():
                return self
            if deadline is None or time.monotonic() >= deadline:
                raise LockHeld(f"lock ativo: {self.path}")
            time.sleep(self.poll_interval)

    def __exit__(self, *_exc: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except (FileNotFoundError, PermissionError):
            pass
