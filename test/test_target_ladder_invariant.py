"""A escada de alvos e invariante do tipo, nao da fabrica.

`DivergenceVolumeConfig` decide onde o capital sai da posicao. Validar so no
caminho do settings deixava duas respostas para o mesmo estado invalido: fatal
vindo do arquivo, silenciosamente reparado para pesos iguais vindo do
construtor ou de um `config=` explicito.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.core.setups import DivergenceVolumeConfig  # noqa: E402


def test_config_padrao_e_coerente() -> None:
    cfg = DivergenceVolumeConfig()
    assert len(cfg.target_levels) == len(cfg.target_weights)


def test_construtor_recusa_pesos_em_quantidade_diferente() -> None:
    with pytest.raises(ValueError, match="(?i)target_weights"):
        DivergenceVolumeConfig(target_levels=(1.0, 2.0), target_weights=(0.5,))


def test_construtor_recusa_escada_vazia() -> None:
    with pytest.raises(ValueError, match="(?i)target_levels|vazi"):
        DivergenceVolumeConfig(target_levels=(), target_weights=())


def test_construtor_recusa_pesos_sem_soma_positiva() -> None:
    """Soma zero ou negativa nao distribui nada; o reparo silencioso para
    pesos iguais escondia isso."""
    with pytest.raises(ValueError, match="(?i)soma|positiv"):
        DivergenceVolumeConfig(target_levels=(1.0, 2.0), target_weights=(0.0, 0.0))


def test_par_coerente_continua_aceito() -> None:
    cfg = DivergenceVolumeConfig(target_levels=(1.0, 2.5), target_weights=(0.4, 0.6))
    assert cfg.target_levels == (1.0, 2.5)
    assert cfg.target_weights == (0.4, 0.6)
