"""Preferencias de instancia viram configuracao (ROADMAP 1.2).

O `SKILL.md` ditava ao agente valores de uma instancia: capital de simulacao
"US$1.000 por cenario", universo "Hyperliquid top 50", relatorio "dashboard
HTML v3". Agora sao chaves em `backtest.*`, com default, e o `setup-check`
mostra os valores efetivos -- o agente le a configuracao, nao o texto.

O universo padrao e a allowlist, nao "Hyperliquid top 50": um universo de uma
venue como padrao seria venue padrao (decisao do autor de 24/09/2026).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import preferencias
from workspace.config import ConfigError, load_settings
from workspace.settings_schema import validar_settings


def _settings(tmp_path: Path, conteudo: dict):
    (tmp_path / "settings.local.json").write_text(json.dumps(conteudo), encoding="utf-8")
    return load_settings()


def test_defaults(tmp_path: Path) -> None:
    prefs = preferencias.preferencias_de_backtest(_settings(tmp_path, {}))
    assert prefs == {
        "capital_por_cenario_usd": 1000.0,
        "relatorio": "dashboard_html",
        "universo_auditoria": "allowlist",
    }


def test_operador_sobrescreve(tmp_path: Path) -> None:
    prefs = preferencias.preferencias_de_backtest(
        _settings(tmp_path, {"backtest": {"capital_por_cenario_usd": 250, "universo_auditoria": "hyperliquid_top_50"}})
    )
    assert prefs["capital_por_cenario_usd"] == 250.0
    assert prefs["universo_auditoria"] == "hyperliquid_top_50"


def test_valor_invalido_nomeia_a_chave(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        preferencias.preferencias_de_backtest(_settings(tmp_path, {"backtest": {"capital_por_cenario_usd": "mil"}}))
    assert "backtest.capital_por_cenario_usd" in str(exc.value)


@pytest.mark.parametrize("valor", [0, -100])
def test_capital_precisa_ser_positivo(tmp_path: Path, valor: int) -> None:
    with pytest.raises(ConfigError):
        preferencias.preferencias_de_backtest(_settings(tmp_path, {"backtest": {"capital_por_cenario_usd": valor}}))


def test_schema_aceita_as_chaves_e_recusa_typo() -> None:
    assert validar_settings({"backtest": {"capital_por_cenario_usd": 1000, "relatorio": "x", "universo_auditoria": "y"}}, origem="t") == []
    assert validar_settings({"backtest": {"capital_cenario": 1000}}, origem="t") != []


def test_exemplo_traz_o_bloco_com_os_defaults() -> None:
    exemplo = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    assert exemplo["backtest"] == {
        "capital_por_cenario_usd": 1000,
        "relatorio": "dashboard_html",
        "universo_auditoria": "allowlist",
    }


def test_setup_check_mostra_as_preferencias_efetivas(tmp_path: Path) -> None:
    from workspace import run

    _settings(tmp_path, {"backtest": {"capital_por_cenario_usd": 500}})
    relatorio = run.setup_check()
    assert relatorio["preferencias"]["backtest"]["capital_por_cenario_usd"] == 500.0


def test_skill_md_referencia_a_chave_nao_o_valor() -> None:
    texto = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "US$1.000" not in texto
    assert "Hyperliquid top 50" not in texto
    for chave in ("backtest.capital_por_cenario_usd", "backtest.universo_auditoria", "backtest.relatorio"):
        assert chave in texto
