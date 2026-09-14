"""Parametros de setup vem do settings, nao do codigo.

Requisito do operador: nenhum valor de setup hardcoded -- cada setup expoe as
suas vars. Hoje os tres `get_*_config` leem env direto, com dois limites que o
settings remove:

- um unico `DIVERGENCE_AND_VOLUME_RSI_PERIOD` vale para 15m, 1h e 4h ao mesmo
  tempo, entao nao da para calibrar um timeframe sem mexer nos outros;
- `fibonacci_levels`, `target_levels` e `target_weights` nao sao configuraveis
  por meio nenhum.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import ConfigError, load_settings  # noqa: E402
from workspace.core.setups import (  # noqa: E402
    get_divergence_volume_config,
    get_funding_arb_config,
    get_triangle_breakout_config,
)


def _settings(tmp_path: Path, payload: dict, env: dict | None = None):
    (tmp_path / "settings.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    return load_settings(root=tmp_path, env=env or {})


# --- precedencia: env continua vencendo, para a migracao ser reversivel -----

def test_env_continua_vencendo_o_settings(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        {"setups": {"triangle-breakout": {"pivot_window": 9}}},
        env={"TRIANGLE_PIVOT_WINDOW": "3"},
    )
    assert get_triangle_breakout_config(settings=s).pivot_window == 3


def test_settings_vence_o_default_do_codigo(tmp_path: Path) -> None:
    s = _settings(tmp_path, {"setups": {"triangle-breakout": {"pivot_window": 9}}})
    assert get_triangle_breakout_config(settings=s).pivot_window == 9


def test_sem_settings_nada_muda(tmp_path: Path) -> None:
    """Ausencia de arquivo mantem exatamente o comportamento anterior."""
    padrao = get_triangle_breakout_config()
    assert get_triangle_breakout_config(settings=_settings(tmp_path, {})) == padrao


def test_config_explicita_ainda_curto_circuita(tmp_path: Path) -> None:
    from workspace.core.setups import TRIANGLE_BREAKOUT_DEFAULT_CONFIG

    s = _settings(tmp_path, {"setups": {"triangle-breakout": {"pivot_window": 9}}})
    assert get_triangle_breakout_config(TRIANGLE_BREAKOUT_DEFAULT_CONFIG, settings=s) == TRIANGLE_BREAKOUT_DEFAULT_CONFIG


# --- o que o settings destrava e a env nao consegue -------------------------

@pytest.mark.parametrize("timeframe,esperado", [("15m", 7), ("1h", 11), ("4h", 21)])
def test_divergence_calibravel_por_timeframe(tmp_path: Path, timeframe, esperado) -> None:
    """Com env, um unico valor vale para os tres timeframes."""
    s = _settings(
        tmp_path,
        {
            "setups": {
                "divergence-and-volume-15m": {"rsi_period": 7},
                "divergence-and-volume-1h": {"rsi_period": 11},
                "divergence-and-volume-4h": {"rsi_period": 21},
            }
        },
    )
    assert get_divergence_volume_config(timeframe=timeframe, settings=s).rsi_period == esperado


def test_listas_de_alvo_viram_configuraveis(tmp_path: Path) -> None:
    """`target_levels`/`target_weights`/`fibonacci_levels` nao tinham como ser
    ajustados por meio nenhum."""
    s = _settings(
        tmp_path,
        {
            "setups": {
                "divergence-and-volume-4h": {
                    "target_levels": [1.0, 2.0],
                    "target_weights": [0.5, 0.5],
                    "fibonacci_levels": [1.0, 1.618],
                }
            }
        },
    )
    cfg = get_divergence_volume_config(timeframe="4h", settings=s)
    assert cfg.target_levels == (1.0, 2.0)
    assert cfg.target_weights == (0.5, 0.5)
    assert cfg.fibonacci_levels == (1.0, 1.618)


def test_funding_arb_le_do_settings(tmp_path: Path) -> None:
    s = _settings(tmp_path, {"setups": {"funding-arb": {"min_rate": 0.0005, "max_hold_hours": 24}}})
    cfg = get_funding_arb_config(settings=s)
    assert cfg.min_rate == 0.0005
    assert cfg.max_hold_hours == 24


# --- valor invalido nao pode virar default em silencio ----------------------

def test_valor_invalido_no_settings_falha_nomeando_a_chave(tmp_path: Path) -> None:
    s = _settings(tmp_path, {"setups": {"triangle-breakout": {"pivot_window": "nove"}}})
    with pytest.raises(ConfigError, match="triangle-breakout.pivot_window"):
        get_triangle_breakout_config(settings=s)


def test_pesos_de_alvo_incoerentes_sao_recusados(tmp_path: Path) -> None:
    """Quantidade de pesos diferente da de alvos distribui capital errado."""
    s = _settings(
        tmp_path,
        {"setups": {"divergence-and-volume-4h": {"target_levels": [1.0, 2.0], "target_weights": [0.5]}}},
    )
    with pytest.raises(ConfigError, match="(?i)target_weights|alvos"):
        get_divergence_volume_config(timeframe="4h", settings=s)
