"""Pacote da venue Nado.

`nado_integration` exige o SDK `nado-protocol`, que e opcional: quem opera so
CEX/Hyperliquid nao precisa dele. Por isso os simbolos sao resolvidos sob
demanda -- importar `workspace.nado` nunca falha por SDK ausente, mas usar um
simbolo que dependa dele falha alto, no ponto de uso.
"""

from __future__ import annotations

from typing import Any

from .units import from_x18, from_x6

_LAZY = {
    "NadoTrader": ".nado_integration",
    "get_nado_fees": ".nado_integration",
    "NADO_FEE_TIERS": ".nado_integration",
    "CryptoDecisionEngine": ".decision",
    "DecisionResult": ".decision",
}

__all__ = [
    "NadoTrader",
    "get_nado_fees",
    "NADO_FEE_TIERS",
    "CryptoDecisionEngine",
    "DecisionResult",
    "from_x18",
    "from_x6",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)
