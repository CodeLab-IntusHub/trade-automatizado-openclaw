"""Venue selection helpers for configurable DEX/CEX execution."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VenueSelection:
    dex_id: str
    cex_id: str


CAPABILITY_KEYS = ("native_sl", "native_tp", "edit_stop", "cancel_trigger", "reduce_only")


def _capabilities(
    *,
    native_sl: bool = False,
    native_tp: bool = False,
    edit_stop: bool = False,
    cancel_trigger: bool = False,
    reduce_only: bool = False,
) -> dict[str, bool]:
    return {
        "native_sl": bool(native_sl),
        "native_tp": bool(native_tp),
        "edit_stop": bool(edit_stop),
        "cancel_trigger": bool(cancel_trigger),
        "reduce_only": bool(reduce_only),
    }


def venue_capabilities(venue_kind: str, venue_id: str) -> dict[str, bool]:
    """Static execution capability matrix for the selected venue adapter."""
    kind = str(venue_kind or "").strip().lower()
    venue = str(venue_id or "").strip().lower()
    if kind == "dex":
        if venue in {"nado", "nado-dex", "nado_dex"}:
            return _capabilities(native_sl=True, native_tp=True, cancel_trigger=True, reduce_only=True)
        if venue in {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}:
            return _capabilities(native_sl=True, native_tp=True, cancel_trigger=True, reduce_only=True)
        return _capabilities()
    if kind == "cex":
        if venue in {"kraken", "krakenfutures", "kraken-futures", "kraken_futures", "kraken-spot"}:
            # Adapter proprio (`KrakenTrader`), com SL/TP implementados aqui.
            return _capabilities(native_sl=True, native_tp=True, cancel_trigger=True, reduce_only=True)
        return _ccxt_capabilities(venue)
    return _capabilities()


def _ccxt_capabilities(venue_id: str) -> dict[str, bool]:
    """Le as capacidades declaradas pelo proprio CCXT para a exchange.

    Os dois ramos deste `if` devolviam exatamente a mesma coisa -- tudo `True`
    para qualquer CEX, sem consultar nada. O diagnostico afirmava SL/TP nativo
    para venues que nao tem, e era com esse diagnostico que o operador decidia
    se podia usar a corretora.

    O cliente e instanciado sem credencial: `has` e estatico por exchange e nao
    exige rede nem chave. Venue desconhecida devolve tudo `False` -- na duvida,
    nao prometer.
    """
    try:
        import ccxt
    except ImportError:  # pragma: no cover - ccxt e dependencia base
        return _capabilities()

    exchange_cls = getattr(ccxt, str(venue_id or "").replace("-", "").replace("_", ""), None)
    if exchange_cls is None:
        exchange_cls = getattr(ccxt, str(venue_id or ""), None)
    if exchange_cls is None:
        return _capabilities()
    try:
        table = getattr(exchange_cls(), "has", None) or {}
    except Exception:  # noqa: BLE001 - exchange invalida/instanciacao recusada
        return _capabilities()

    def has(*names: str) -> bool:
        return any(bool(table.get(name)) for name in names)

    return _capabilities(
        native_sl=has("createStopLossOrder", "createStopOrder", "createTriggerOrder"),
        native_tp=has("createTakeProfitOrder", "createTriggerOrder"),
        edit_stop=has("editOrder"),
        cancel_trigger=has("cancelOrder"),
        # `reduceOnly` so existe em derivativo; o tipo de mercado efetivo vem
        # da configuracao, entao aqui reportamos o que a exchange oferece.
        reduce_only=has("createOrder"),
    )


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.split("#", 1)[0].strip()


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean(os.environ.get(name))
        if value:
            return value
    return ""


def _prefix(venue_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", venue_id or "").strip("_").upper()
    return cleaned or "VENUE"


def _normalize_cex_market_type(value: str | None, cex_id: str) -> str:
    key = (value or "").strip().lower()
    is_kraken = cex_id.startswith("kraken")
    if not key:
        return "futures" if is_kraken else "swap"
    trade_aliases = {"trade", "trading", "long-short", "long_short", "perpetual", "perpetuals", "perp", "perps"}
    if key in trade_aliases or (is_kraken and key in {"swap", "future"}):
        return "futures" if is_kraken else "swap"
    if key == "futures":
        return "futures" if is_kraken else "future"
    return key


def selected_venues() -> VenueSelection:
    dex_id = _first_env("DEX_ID", "TRADE_DEX_ID", "PRIMARY_DEX") or "nado"
    cex_id = _first_env("CEX_ID", "TRADE_CEX_ID", "PRIMARY_CEX") or "kraken"
    return VenueSelection(dex_id=dex_id.lower(), cex_id=cex_id.lower())


def cex_env_names(cex_id: str) -> dict[str, list[str]]:
    prefix = _prefix(cex_id)
    names = {
        "api_key": ["CEX_API_KEY", f"{prefix}_API_KEY"],
        "api_secret": ["CEX_API_SECRET", f"{prefix}_API_SECRET"],
        "api_password": ["CEX_API_PASSWORD", f"{prefix}_API_PASSWORD"],
    }
    if cex_id in {"kraken", "krakenfutures", "kraken-futures", "kraken_futures"}:
        names["api_key"].extend(["KRAKEN_API_KEY", "KRAKEN_API_KEY_"])
        names["api_secret"].append("KRAKEN_API_SECRET")
    return names


def cex_credentials(cex_id: str) -> dict[str, str]:
    names = cex_env_names(cex_id)
    return {
        "api_key": _first_env(*names["api_key"]),
        "api_secret": _first_env(*names["api_secret"]),
        "api_password": _first_env(*names["api_password"]),
    }


def dex_env_names(dex_id: str) -> dict[str, list[str]]:
    prefix = _prefix(dex_id)
    builtin_dex = dex_id in {
        "nado",
        "nado-dex",
        "nado_dex",
        "hyperliquid",
        "hyperliquid-dex",
        "hyperliquid_dex",
    }
    names = {"config_json": ["DEX_CONFIG_JSON", f"{prefix}_CONFIG_JSON"]}
    if not builtin_dex:
        names["adapter"] = ["DEX_ADAPTER", "DEX_ADAPTER_MODULE", f"{prefix}_ADAPTER", f"{prefix}_ADAPTER_MODULE"]
    if dex_id in {"nado", "nado-dex", "nado_dex"}:
        names.update(
            {
                "owner_private_key": ["NADO_OWNER_PRIVATE_KEY", "NADO_PRIVATE_KEY", "PRIVATE_KEY"],
                "linked_signer_private_key": ["NADO_LINKED_SIGNER_PRIVATE_KEY"],
                "network": ["NADO_NETWORK", "NETWORK"],
                "subaccount_name": ["NADO_SUBACCOUNT_NAME"],
            }
        )
    if dex_id in {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}:
        names.update(
            {
                "private_key": [
                    "HYPERLIQUID_PRIVATE_KEY",
                    "HYPERLIQUID_API_PRIVATE_KEY",
                    "HYPERLIQUID_AGENT_PRIVATE_KEY",
                ],
                "wallet_address": ["HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_ACCOUNT_ADDRESS"],
                "vault_address": ["HYPERLIQUID_VAULT_ADDRESS"],
                "network": ["HYPERLIQUID_NETWORK", "DEX_NETWORK"],
                "sandbox": ["HYPERLIQUID_SANDBOX", "DEX_SANDBOX"],
                "market_type": ["HYPERLIQUID_MARKET_TYPE", "DEX_MARKET_TYPE"],
            }
        )
    return names


def dex_adapter_spec(dex_id: str) -> str:
    return _first_env(*dex_env_names(dex_id).get("adapter", []))


def dex_config(dex_id: str) -> dict[str, Any]:
    raw = _first_env(*dex_env_names(dex_id)["config_json"])
    payload: dict[str, Any] = {"dex_id": dex_id}
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("DEX_CONFIG_JSON precisa ser um objeto JSON")
        payload.update(parsed)
    payload.setdefault("network", _first_env("DEX_NETWORK", f"{_prefix(dex_id)}_NETWORK"))
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def venue_summary() -> dict[str, Any]:
    selection = selected_venues()
    cex_names = cex_env_names(selection.cex_id)
    dex_names = dex_env_names(selection.dex_id)
    cex_creds = cex_credentials(selection.cex_id)
    capabilities = {
        "dex": venue_capabilities("dex", selection.dex_id),
        "cex": venue_capabilities("cex", selection.cex_id),
    }
    return {
        "dex_id": selection.dex_id,
        "cex_id": selection.cex_id,
        "dex_adapter": dex_adapter_spec(selection.dex_id) or (
            "builtin:nado"
            if selection.dex_id in {"nado", "nado-dex", "nado_dex"}
            else "builtin:hyperliquid"
            if selection.dex_id in {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}
            else "missing"
        ),
        "cex_adapter": "builtin:kraken" if selection.cex_id in {"kraken", "krakenfutures", "kraken-futures", "kraken_futures", "kraken-spot"} else "ccxt",
        "cex_market_type": _normalize_cex_market_type(_first_env("CEX_MARKET_TYPE", "CEX_DEFAULT_TYPE", f"{_prefix(selection.cex_id)}_MARKET_TYPE"), selection.cex_id),
        # "nao_definido" em vez de assumir producao: o CLI recusa essa config,
        # e o diagnostico nao pode dar um veredito diferente do executor.
        "cex_sandbox": (
            _first_env(f"{_prefix(selection.cex_id)}_SANDBOX", "CEX_SANDBOX")
            or ("true" if selection.cex_id.startswith("kraken") else "nao_definido")
        ),
        "cex_required_env": cex_names,
        "cex_credentials_configured": bool(cex_creds["api_key"] and cex_creds["api_secret"]),
        "dex_required_env": dex_names,
        "dex_adapter_configured": (
            bool(dex_adapter_spec(selection.dex_id))
            or selection.dex_id in {"nado", "nado-dex", "nado_dex", "hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}
        ),
        "capabilities": capabilities,
        "venue_capabilities": capabilities,
    }
