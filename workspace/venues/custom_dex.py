"""Loader for user-supplied DEX adapters."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

REQUIRED_DEX_METHODS = (
    "get_symbol_to_product_map",
    "get_market_mid_price",
    "get_perp_position_size",
    "get_all_positions",
    "round_quantity_to_increment",
    "place_market_order",
    "place_stop_loss",
    "place_take_profit",
    "assert_trade_ready",
    "get_isolation_context",
)


def _load_object(spec: str) -> type:
    if not spec or ":" not in spec:
        raise ValueError("DEX_ADAPTER_MODULE precisa estar no formato 'pacote.modulo:Classe'")
    module_name, object_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    obj = getattr(module, object_name)
    if not inspect.isclass(obj):
        raise TypeError(f"{spec} nao aponta para uma classe")
    return obj


def _instantiate(adapter_cls: type, config: dict[str, Any]) -> Any:
    try:
        return adapter_cls(**config)
    except TypeError:
        adapter = adapter_cls()
        configure = getattr(adapter, "configure", None)
        if callable(configure):
            configure(**config)
        return adapter


def validate_dex_adapter(adapter: Any) -> None:
    missing = [name for name in REQUIRED_DEX_METHODS if not callable(getattr(adapter, name, None))]
    if missing:
        raise TypeError("DEX adapter incompleto; faltam metodos: " + ", ".join(missing))


def load_custom_dex_adapter(spec: str, config: dict[str, Any] | None = None) -> Any:
    adapter_cls = _load_object(spec)
    adapter = _instantiate(adapter_cls, dict(config or {}))
    validate_dex_adapter(adapter)
    return adapter
