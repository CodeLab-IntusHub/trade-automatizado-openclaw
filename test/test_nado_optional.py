"""O SDK da Nado e opcional: sua ausencia nao pode derrubar o resto da skill.

A Nado e a unica venue com SDK proprio (`nado-protocol`, que arrasta web3 +
extensoes nativas). Kraken, Hyperliquid e as demais CEXs rodam por CCXT. Um
import obrigatorio no topo fazia a venue menos central derrubar a importacao
de `cli.py` inteiro -- inclusive em maquinas que so operam CEX.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BLOCK_NADO = """
import sys

class _BlockNado:
    def find_module(self, name, path=None):
        return None
    def find_spec(self, name, path=None, target=None):
        if name == "nado_protocol" or name.startswith("nado_protocol."):
            raise ImportError("No module named 'nado_protocol'")
        return None

sys.meta_path.insert(0, _BlockNado())
for mod in [m for m in sys.modules if m.startswith("nado_protocol")]:
    del sys.modules[mod]
"""


def _run_without_nado(body: str) -> subprocess.CompletedProcess[str]:
    script = BLOCK_NADO + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_core_importa_sem_o_sdk_da_nado() -> None:
    result = _run_without_nado(
        """
        import workspace.core
        print("OK", workspace.core.DeltaNeutralEngine.__name__)
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK DeltaNeutralEngine" in result.stdout


def test_cli_importa_sem_o_sdk_da_nado() -> None:
    result = _run_without_nado(
        """
        import workspace.cli as cli
        print("OK", cli.SETUP_STATE_LOCK_TIMEOUT)
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_conversao_x18_nao_depende_do_sdk() -> None:
    result = _run_without_nado(
        """
        from workspace.nado.units import from_x18, from_x6
        print("OK", from_x18(10**18), from_x6(10**6))
        """
    )
    assert result.returncode == 0, result.stderr
    assert "OK 1.0 1.0" in result.stdout


def test_usar_a_nado_sem_o_sdk_falha_alto_e_com_instrucao() -> None:
    """Ausencia do SDK vira erro explicito no ponto de uso, nunca fallback mudo."""
    result = _run_without_nado(
        """
        import workspace.cli as cli
        try:
            cli.load_nado_trader_class()
        except BaseException as exc:  # SystemExit e o padrao de erro de config do cli.py
            print("RAISED", type(exc).__name__, str(exc))
        else:
            print("NAO LEVANTOU")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "RAISED SystemExit" in result.stdout
    assert "NAO LEVANTOU" not in result.stdout
    assert "nado-protocol" in result.stdout
    assert "DEX_ID" in result.stdout


def test_com_o_sdk_presente_o_acesso_continua_funcionando() -> None:
    pytest.importorskip("nado_protocol")
    import workspace.cli as cli

    assert cli.load_nado_trader_class().__name__ == "NadoTrader"
