"""Preferencias de backtest que eram texto do `SKILL.md` (ROADMAP 1.2).

Capital de simulacao, formato do relatorio e universo da auditoria eram
valores de uma instancia escritos para o agente. Agora sao chaves em
`backtest.*`, com default, e o `setup-check` mostra os valores efetivos.
"""

from __future__ import annotations

from typing import Any

from workspace.config import ConfigError, Settings, load_settings

CAPITAL_POR_CENARIO_USD = 1000.0
RELATORIO = "dashboard_html"
# Nao "hyperliquid_top_50": o universo de uma venue como padrao seria venue
# padrao. A allowlist ja e o fluxo padrao da skill.
UNIVERSO_AUDITORIA = "allowlist"


def preferencias_de_backtest(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    capital = settings.get_float("backtest.capital_por_cenario_usd", default=CAPITAL_POR_CENARIO_USD)
    if capital <= 0:
        raise ConfigError(f"backtest.capital_por_cenario_usd precisa ser positivo, veio {capital}")
    return {
        "capital_por_cenario_usd": capital,
        "relatorio": settings.get_str("backtest.relatorio", default=RELATORIO),
        "universo_auditoria": settings.get_str("backtest.universo_auditoria", default=UNIVERSO_AUDITORIA),
    }
