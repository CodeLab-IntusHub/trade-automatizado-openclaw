"""Builtin Hyperliquid DEX adapter backed by CCXT.

The engine historically calls its DEX leg with Nado-style method names.
This adapter keeps that interface while routing to Hyperliquid perps via CCXT.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import ccxt

logger = logging.getLogger(__name__)


@dataclass
class HyperliquidPosition:
    symbol: str
    product_id: str
    side: str
    size: float
    mark_price: float
    notional_usd: float
    margin_mode: str = ""
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    liquidation_price: float = 0.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""


def _clean_address(value: str | None) -> str:
    return (value or "").strip()


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        return normalized in {"1", "true", "yes", "y", "sim", "s", "on"}
    return bool(value)


def _short_address(value: str | None) -> str:
    raw = _clean_address(value)
    if len(raw) <= 18:
        return raw or "-"
    return f"{raw[:10]}...{raw[-6:]}"


class HyperliquidDexTrader:
    """DEX-leg adapter for Hyperliquid perpetuals.

    Public market data works without credentials, but trading requires
    ``wallet_address`` and ``private_key``. ``vault_address`` is optional and
    is forwarded to CCXT on orders when configured.
    """

    exchange_id = "hyperliquid"
    venue = "hyperliquid"

    def __init__(
        self,
        *,
        wallet_address: str = "",
        private_key: str = "",
        vault_address: str = "",
        sandbox: bool = False,
        market_type: str = "swap",
        symbol_quote: str = "USDT",
        options: dict[str, Any] | None = None,
        load_markets: bool = True,
    ) -> None:
        self.wallet_address = _clean_address(wallet_address)
        self.private_key = (private_key or "").strip()
        self.vault_address = _clean_address(vault_address)
        self.sandbox = _to_bool(sandbox, False)
        self.network = "testnet" if self.sandbox else "mainnet"
        self.market_type = self._normalize_market_type(market_type)
        self.symbol_quote = (symbol_quote or "USDT").strip().upper()
        self.account = "vault" if self.vault_address else "wallet"
        self.account_symbol = None
        self.api_fingerprint = _fingerprint(self.wallet_address or self.private_key)

        client_options: dict[str, Any] = {"defaultType": self.market_type}
        if options:
            client_options.update(options)
        config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": client_options,
        }
        if self.wallet_address:
            config["walletAddress"] = self.wallet_address
        if self.private_key:
            config["privateKey"] = self.private_key
        self.client = ccxt.hyperliquid(config)
        if self.sandbox:
            self.client.set_sandbox_mode(True)
        if load_markets:
            self.client.load_markets()

    @staticmethod
    def _normalize_market_type(value: str) -> str:
        key = (value or "swap").strip().lower()
        aliases = {
            "trade": "swap",
            "trading": "swap",
            "long-short": "swap",
            "long_short": "swap",
            "perpetual": "swap",
            "perpetuals": "swap",
            "perp": "swap",
            "perps": "swap",
            "futures": "swap",
            "future": "swap",
        }
        return aliases.get(key, key)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None, **overrides: Any) -> "HyperliquidDexTrader":
        payload = dict(config or {})
        payload.update({key: value for key, value in overrides.items() if value is not None and value != ""})
        options = payload.get("options")
        if options is None and payload.get("options_json"):
            options = json.loads(str(payload["options_json"]))
        if options is not None and not isinstance(options, dict):
            raise ValueError("HYPERLIQUID_OPTIONS_JSON/DEX_CONFIG_JSON.options precisa ser objeto JSON")
        return cls(
            wallet_address=str(payload.get("wallet_address") or payload.get("walletAddress") or ""),
            private_key=str(payload.get("private_key") or payload.get("privateKey") or ""),
            vault_address=str(payload.get("vault_address") or payload.get("vaultAddress") or ""),
            sandbox=_to_bool(payload.get("sandbox"), False),
            market_type=str(payload.get("market_type") or payload.get("marketType") or "swap"),
            symbol_quote=str(payload.get("symbol_quote") or payload.get("symbolQuote") or "USDT"),
            options=options,
            load_markets=_to_bool(payload.get("load_markets"), True),
        )

    def _order_params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self.vault_address:
            params.setdefault("vaultAddress", self.vault_address)
        return params

    def _market_matches_type(self, market: dict[str, Any]) -> bool:
        if self.market_type == "spot":
            return bool(market.get("spot"))
        return bool(market.get("swap") or market.get("contract"))

    def _display_symbol(self, market: dict[str, Any]) -> str:
        base = str(market.get("base") or "").upper()
        return f"{base}/{self.symbol_quote}" if base else str(market.get("symbol") or "")

    def get_symbol_to_product_map(self, product_filter: Optional[List[str]] = None) -> Dict[str, str]:
        if not getattr(self.client, "markets", None):
            self.client.load_markets()
        filters = {str(item).upper() for item in (product_filter or [])}
        out: Dict[str, str] = {}
        for native, market in self.client.markets.items():
            if not self._market_matches_type(market):
                continue
            display = self._display_symbol(market)
            base = str(market.get("base") or "").upper()
            if filters and display.upper() not in filters and base not in filters:
                continue
            out[display] = native
        return out

    def _resolve_market_symbol(self, symbol: object) -> str:
        raw = str(symbol or "").strip().upper()
        if not getattr(self.client, "markets", None):
            self.client.load_markets()
        if raw in self.client.markets:
            return raw
        if "/" not in raw:
            raw = f"{raw}/{self.symbol_quote}"
        base = raw.split("/", 1)[0]
        candidates = [
            raw,
            f"{base}/USDC:USDC",
            f"{base}/USDT:USDT",
            f"{base}/USDC",
            f"{base}/USDT",
            f"{base}/USD:USD",
        ]
        for candidate in candidates:
            if candidate in self.client.markets:
                return candidate
        return candidates[0]

    def _extract_mark_price(self, ticker: dict[str, Any]) -> float:
        info = ticker.get("info") or {}
        bid = _to_float(ticker.get("bid"))
        ask = _to_float(ticker.get("ask"))
        if bid and ask:
            return (bid + ask) / 2
        return _first_float(
            ticker.get("last"),
            ticker.get("mark"),
            info.get("midPx"),
            info.get("markPx"),
            info.get("oraclePx"),
            default=0.0,
        )

    def get_market_mid_price(self, product_id: object) -> float:
        native = self._resolve_market_symbol(product_id)
        return self._extract_mark_price(self.client.fetch_ticker(native))

    def _parse_position(self, position: dict[str, Any], fallback_symbol: str = "") -> HyperliquidPosition:
        info = position.get("info") or {}
        symbol = str(position.get("symbol") or fallback_symbol or info.get("coin") or "")
        native = self._resolve_market_symbol(symbol) if symbol else fallback_symbol
        size_abs = _first_float(position.get("contracts"), position.get("contractSize"), info.get("szi"), info.get("size"), default=0.0)
        side_raw = str(position.get("side") or info.get("side") or "").lower()
        if not side_raw and _to_float(info.get("szi")) < 0:
            side_raw = "short"
        signed_size = -abs(size_abs) if side_raw == "short" else abs(size_abs) if size_abs else 0.0
        entry_price = _first_float(position.get("entryPrice"), info.get("entryPx"), info.get("entryPrice"), default=0.0)
        mark_price = _first_float(position.get("markPrice"), info.get("markPx"), info.get("oraclePx"), default=0.0)
        if mark_price <= 0 and native:
            mark_price = self.get_market_mid_price(native)
        notional = _first_float(position.get("notional"), info.get("positionValue"), default=0.0)
        if notional <= 0 and mark_price > 0:
            notional = abs(signed_size) * mark_price
        margin_mode = str(position.get("marginMode") or info.get("marginMode") or "").lower()
        leverage_raw = info.get("leverage")
        leverage = _first_float(
            position.get("leverage"),
            leverage_raw.get("value") if isinstance(leverage_raw, dict) else leverage_raw,
            default=1.0,
        ) or 1.0
        liquidation_price = _first_float(position.get("liquidationPrice"), info.get("liquidationPx"), default=0.0)
        pnl = _first_float(position.get("unrealizedPnl"), info.get("unrealizedPnl"), default=0.0)
        market = self.client.markets.get(native, {"symbol": native, "base": symbol.split("/", 1)[0]})
        return HyperliquidPosition(
            symbol=self._display_symbol(market) if native else symbol,
            product_id=native,
            side="short" if signed_size < 0 else "long" if signed_size > 0 else "flat",
            size=signed_size,
            mark_price=mark_price,
            notional_usd=notional,
            margin_mode=margin_mode,
            entry_price=entry_price,
            unrealized_pnl=pnl,
            leverage=leverage,
            liquidation_price=liquidation_price,
        )

    def get_position(self, product_id: object) -> HyperliquidPosition:
        native = self._resolve_market_symbol(product_id)
        try:
            positions = self.client.fetch_positions([native])
        except Exception:
            positions = self.client.fetch_positions()
        for position in positions:
            parsed = self._parse_position(position, native)
            if abs(parsed.size) < 1e-12:
                continue
            if parsed.product_id == native or self._resolve_market_symbol(parsed.product_id) == native:
                return parsed
        return HyperliquidPosition(
            symbol=self._display_symbol(self.client.markets.get(native, {"symbol": native, "base": native.split("/", 1)[0]})),
            product_id=native,
            side="flat",
            size=0.0,
            mark_price=self.get_market_mid_price(native),
            notional_usd=0.0,
        )

    def get_perp_position_size(self, product_id: object) -> float:
        return float(self.get_position(product_id).size)

    def get_balance(self, asset: str = "USDC") -> float:
        balance = self.client.fetch_balance(self._order_params())
        candidates = []
        for code in (asset, "USDC", "USD", "USDT"):
            normalized = str(code or "").upper()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        for code in candidates:
            row = balance.get(code)
            if isinstance(row, dict):
                value = _first_float(row.get("free"), row.get("total"), default=0.0)
                if value > 0:
                    return value
            for bucket in ("free", "total"):
                values = balance.get(bucket)
                if isinstance(values, dict):
                    value = _first_float(values.get(code), default=0.0)
                    if value > 0:
                        return value
        return 0.0

    def get_all_positions(self) -> List[HyperliquidPosition]:
        if not getattr(self.client, "has", {}).get("fetchPositions"):
            return []
        out: list[HyperliquidPosition] = []
        for raw in self.client.fetch_positions():
            parsed = self._parse_position(raw, str(raw.get("symbol") or ""))
            if abs(parsed.size) > 1e-12:
                out.append(parsed)
        return out

    def round_quantity_to_increment(self, product_id: object, quantity: float) -> float:
        native = self._resolve_market_symbol(product_id)
        market = self.client.market(native)
        precision = (market.get("precision") or {}).get("amount")
        min_amount = (((market.get("limits") or {}).get("amount") or {}).get("min")) or 0
        qty = float(quantity or 0.0)
        if precision is not None:
            step = 10 ** (-precision) if isinstance(precision, int) else float(precision)
            if step > 0:
                qty = int(qty / step) * step
        qty = round(qty, 12)
        return 0.0 if qty < float(min_amount or 0.0) else qty

    def configure_futures_risk_context(self, product_id: object, *, leverage: float | None = None, margin_mode: str | None = None) -> dict[str, Any]:
        native = self._resolve_market_symbol(product_id)
        result: dict[str, Any] = {}
        leverage_int = int(round(float(leverage))) if leverage is not None else None
        if margin_mode and getattr(self.client, "has", {}).get("setMarginMode"):
            if leverage_int is None:
                result["margin_mode_skipped"] = "missing_leverage"
            else:
                result["set_margin_mode_response"] = self.client.set_margin_mode(
                    str(margin_mode).lower(),
                    native,
                    self._order_params({"leverage": leverage_int}),
                )
                result["margin_mode"] = str(margin_mode).lower()
        elif leverage_int is not None and getattr(self.client, "has", {}).get("setLeverage"):
            result["response"] = self.client.set_leverage(leverage_int, native, self._order_params())
        if leverage_int is not None:
            result["leverage"] = float(leverage)
        return result

    def place_market_order(
        self,
        product_id: object,
        quantity: float,
        is_buy: bool = True,
        slippage_bps: int | None = None,
        reduce_only: bool = False,
        margin_mode: str | None = None,
        leverage: float | None = None,
    ) -> dict[str, Any]:
        native = self._resolve_market_symbol(product_id)
        if not reduce_only:
            self.configure_futures_risk_context(native, leverage=leverage, margin_mode=margin_mode)
        side = "buy" if is_buy else "sell"
        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True
        if slippage_bps is not None:
            params["slippage"] = float(slippage_bps) / 10000.0
        reference_price = self.get_market_mid_price(native)
        if reference_price <= 0:
            raise RuntimeError(f"Preco de referencia invalido para ordem market Hyperliquid: {native}")
        logger.info("[hyperliquid %s] MARKET %s %s %s", self.network, side.upper(), quantity, native)
        return self.client.create_order(native, "market", side, quantity, reference_price, self._order_params(params))

    def place_stop_loss(
        self,
        product_id: object,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        native = self._resolve_market_symbol(product_id)
        side = "sell" if is_long else "buy"
        params: dict[str, Any] = {"stopLossPrice": trigger_price, "reduceOnly": True}
        if slippage_pct is not None:
            params["slippage"] = float(slippage_pct)
        return self.client.create_order(native, "market", side, quantity, trigger_price, self._order_params(params))

    def place_take_profit(
        self,
        product_id: object,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        native = self._resolve_market_symbol(product_id)
        side = "sell" if is_long else "buy"
        params: dict[str, Any] = {"takeProfitPrice": trigger_price, "reduceOnly": True}
        if slippage_pct is not None:
            params["slippage"] = float(slippage_pct)
        return self.client.create_order(native, "market", side, quantity, trigger_price, self._order_params(params))

    def capabilities(self) -> Dict[str, bool]:
        return {
            "native_sl": True,
            "native_tp": True,
            "edit_stop": False,
            "cancel_trigger": True,
            "reduce_only": True,
        }

    def replace_stop_loss(
        self,
        product_id: object,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        previous_order_ref: dict | str | None = None,
        slippage_pct: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        order_id = previous_order_ref if isinstance(previous_order_ref, str) else None
        if isinstance(previous_order_ref, dict):
            order_id = str(previous_order_ref.get("id") or previous_order_ref.get("digest") or "")
        if not order_id:
            return {"cancelled": False, "order": None, "skipped_reason": "missing_previous_order_id"}
        self.cancel_order(order_id, product_id)
        order = self.place_stop_loss(
            product_id,
            quantity,
            trigger_price,
            is_long=is_long,
            slippage_pct=slippage_pct,
        )
        return {"cancelled": True, "order": order}

    def cancel_all_orders(self, product_id: object | None = None):
        native = self._resolve_market_symbol(product_id) if product_id else None
        if getattr(self.client, "has", {}).get("cancelAllOrders"):
            return self.client.cancel_all_orders(native, self._order_params())
        return [self.client.cancel_order(order["id"], native, self._order_params()) for order in self.client.fetch_open_orders(native)]

    def cancel_order(self, order_id: str, product_id: object | None = None):
        native = self._resolve_market_symbol(product_id) if product_id else None
        return self.client.cancel_order(order_id, native, self._order_params())

    def get_open_orders(self, product_id: object | None = None):
        native = self._resolve_market_symbol(product_id) if product_id else None
        return self.client.fetch_open_orders(native)

    def assert_trade_ready(self) -> None:
        missing = []
        if not self.wallet_address:
            missing.append("HYPERLIQUID_WALLET_ADDRESS")
        if not self.private_key:
            missing.append("HYPERLIQUID_PRIVATE_KEY")
        if missing:
            raise RuntimeError("Configure " + "/".join(missing) + " no env/secret manager para operar Hyperliquid")

    def get_isolation_context(self) -> Dict[str, Any]:
        return {
            "venue": "hyperliquid",
            "network": self.network,
            "sandbox": self.sandbox,
            "wallet_address": _short_address(self.wallet_address),
            "vault_address": _short_address(self.vault_address),
            "subaccount_mode": "vault" if self.vault_address else "wallet",
            "api_fingerprint": self.api_fingerprint,
            "trade_ready": bool(self.wallet_address and self.private_key),
        }
