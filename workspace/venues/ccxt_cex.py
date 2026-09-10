"""Generic CCXT CEX adapter used as the CEX leg behind the existing engine."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import ccxt

from workspace.kraken.kraken_integration import KrakenOrderConflict, KrakenPosition

logger = logging.getLogger(__name__)


class VenueCapabilityError(RuntimeError):
    """A venue nao suporta a operacao, ou nao confirmou que a executou.

    Existe para que "esta corretora nao faz isso" nunca seja confundido com
    sucesso. Todo caminho que protege posicao levanta isto em vez de seguir.
    """



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


def _api_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


class GenericCcxtTrader:
    """CEX adapter for any CCXT exchange with a market/futures API.

    It intentionally exposes the same methods used by DeltaNeutralEngine's CEX
    leg. Exchange-specific quirks are handled best-effort through CCXT params;
    unsupported live features fail explicitly instead of being silently ignored.
    """

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        *,
        api_password: str = "",
        market_type: str = "swap",
        sandbox: bool = False,
        options: dict[str, Any] | None = None,
        load_markets: bool = True,
    ) -> None:
        self.exchange_id = self._normalize_exchange_id(exchange_id)
        self.venue = self._normalize_market_type(market_type)
        self.sandbox = bool(sandbox)
        self.account = self.venue
        self.account_symbol = None
        self.require_subaccount = False
        self.declared_is_subaccount = True
        self.api_fingerprint = _api_fingerprint(api_key) if api_key else ""

        exchange_cls = getattr(ccxt, self.exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Exchange CCXT nao suportada/instalada: {exchange_id}")

        client_options: dict[str, Any] = {"defaultType": self.venue}
        if options:
            client_options.update(options)
        config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": client_options,
        }
        if api_password:
            config["password"] = api_password
        self.client = exchange_cls(config)
        if self.sandbox:
            try:
                self.client.set_sandbox_mode(True)
            except Exception as exc:
                # Nem toda CEX tem testnet. Seguir apos a falha deixaria o
                # cliente apontando para producao com as chaves reais do
                # usuario, que pediu exatamente o contrario.
                raise VenueCapabilityError(
                    f"sandbox indisponivel em {self.exchange_id}: {exc}. "
                    "Defina CEX_SANDBOX=false para operar em producao de forma "
                    "explicita, ou escolha outra venue."
                ) from exc
        if load_markets:
            try:
                self.client.load_markets()
            except Exception as exc:  # noqa: BLE001
                logger.warning("load_markets falhou em %s: %s", self.exchange_id, exc)

    @staticmethod
    def _normalize_exchange_id(exchange_id: str) -> str:
        aliases = {
            "kraken-futures": "krakenfutures",
            "kraken_futures": "krakenfutures",
            "binance-futures": "binance",
            "binance_usdm": "binanceusdm",
            "binance-usdm": "binanceusdm",
        }
        key = (exchange_id or "").strip().lower()
        return aliases.get(key, key)

    @staticmethod
    def _normalize_market_type(market_type: str) -> str:
        key = (market_type or "swap").strip().lower()
        aliases = {
            "trade": "swap",
            "trading": "swap",
            "long-short": "swap",
            "long_short": "swap",
            "perpetual": "swap",
            "perpetuals": "swap",
            "perp": "swap",
            "perps": "swap",
            "linear": "swap",
            "futures": "future",
        }
        return aliases.get(key, key)

    @staticmethod
    def from_options_json(
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        *,
        api_password: str = "",
        market_type: str = "swap",
        sandbox: bool = False,
        options_json: str = "",
    ) -> "GenericCcxtTrader":
        options = json.loads(options_json) if options_json else None
        if options is not None and not isinstance(options, dict):
            raise ValueError("CEX_OPTIONS_JSON precisa ser um objeto JSON")
        return GenericCcxtTrader(
            exchange_id,
            api_key,
            api_secret,
            api_password=api_password,
            market_type=market_type,
            sandbox=sandbox,
            options=options,
        )

    def get_isolation_context(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "exchange_id": self.exchange_id,
            "sandbox": self.sandbox,
            "account": self.account,
            "account_symbol": self.account_symbol or "",
            "api_fingerprint": self.api_fingerprint,
            "subaccount_mode": "generic_ccxt_api",
        }

    def get_trading_safety(self, **_: Any) -> Dict[str, Any]:
        return {
            "safe": True,
            "label": "generic_ccxt",
            "reason": "CEX generica via CCXT; isolamento depende das permissoes/chaves fornecidas pelo usuario.",
            "master_detected": None,
        }

    def validate_entry_subaccount_rule(self, **_: Any) -> None:
        return None

    def get_accounts_overview(self) -> Dict[str, Any]:
        try:
            raw = self.client.fetch_balance()
        except Exception as exc:  # noqa: BLE001
            raw = {"error": str(exc)}
        return {
            "selected": self.get_isolation_context(),
            "accounts": [],
            "balance": raw,
            "trading_safety": self.get_trading_safety(),
        }

    def normalize_symbol(self, base: str) -> str:
        if not base:
            return base
        candidate = base.strip().upper()
        if candidate in getattr(self.client, "markets", {}):
            return candidate
        if "/" not in candidate:
            candidate = f"{candidate}/USDT"
        coin, quote = candidate.split("/", 1)
        quote = quote.split(":", 1)[0]
        candidates = [candidate]
        if self.venue in {"swap", "future"}:
            candidates.extend([f"{coin}/{quote}:{quote}", f"{coin}/USDT:USDT", f"{coin}/USD:USD"])
        candidates.extend([f"{coin}/USDT", f"{coin}/USDC", f"{coin}/USD"])
        for item in candidates:
            if item in getattr(self.client, "markets", {}):
                return item
        return candidates[0]

    def _resolve_market_symbol(self, symbol: str) -> str:
        stripped = symbol.strip()
        if stripped in getattr(self.client, "markets", {}):
            return stripped
        return self.normalize_symbol(stripped)

    def _market_matches_type(self, market: dict[str, Any]) -> bool:
        if self.venue == "spot":
            return bool(market.get("spot"))
        if self.venue == "future":
            return bool(market.get("future") or market.get("contract"))
        if self.venue == "swap":
            return bool(market.get("swap") or market.get("contract"))
        return True

    def get_symbol_to_product_map(self, product_filter: Optional[List[str]] = None) -> Dict[str, str]:
        out: Dict[str, str] = {}
        filters = {item.upper() for item in (product_filter or [])}
        for native, market in getattr(self.client, "markets", {}).items():
            if not self._market_matches_type(market):
                continue
            base = str(market.get("base") or "").upper()
            quote = str(market.get("quote") or market.get("settle") or "USDT").upper()
            if base in {"", "XBT"}:
                base = "BTC" if base == "XBT" else base
            if not base:
                continue
            pretty = f"{base}/{quote if quote in {'USDT', 'USDC', 'USD'} else 'USDT'}"
            if filters and pretty not in filters and f"{base}/USDT" not in filters and base not in filters:
                continue
            out[pretty] = native
        return out

    def get_market_price(self, symbol: str) -> Dict[str, float]:
        ticker = self.client.fetch_ticker(self._resolve_market_symbol(symbol))
        bid = _to_float(ticker.get("bid"))
        ask = _to_float(ticker.get("ask"))
        mid = self._extract_mark_price(ticker)
        return {"bid_price": bid, "ask_price": ask, "mid_price": mid}

    def get_market_mid_price(self, symbol: str) -> float:
        ticker = self.client.fetch_ticker(self._resolve_market_symbol(symbol))
        return self._extract_mark_price(ticker)

    def _extract_mark_price(self, ticker: Dict[str, Any]) -> float:
        info = ticker.get("info") or {}
        bid = _to_float(ticker.get("bid"))
        ask = _to_float(ticker.get("ask"))
        if bid and ask:
            return (bid + ask) / 2
        return _first_float(
            ticker.get("last"),
            ticker.get("mark"),
            info.get("markPrice"),
            info.get("indexPrice"),
            info.get("lastPrice"),
            default=0.0,
        )

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        if not getattr(self.client, "has", {}).get("fetchFundingRate"):
            return None
        try:
            fr = self.client.fetch_funding_rate(self._resolve_market_symbol(symbol))
            return float(fr.get("fundingRate") or fr.get("rate") or 0.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("funding rate indisponivel em %s: %s", self.exchange_id, exc)
            return None

    def get_balance(self, asset: str = "USD") -> float:
        balance = self.client.fetch_balance()
        for code in (asset, asset.upper(), f"Z{asset.upper()}"):
            value = ((balance.get(code) or {}).get("free") if isinstance(balance.get(code), dict) else None)
            if value is not None:
                return _to_float(value)
        return 0.0

    def _parse_position(self, position: Dict[str, Any], symbol: str) -> KrakenPosition:
        info = position.get("info") or {}
        size_abs = _first_float(position.get("contracts"), position.get("contractSize"), info.get("size"), default=0.0)
        notional = _first_float(position.get("notional"), info.get("notional"), default=0.0)
        entry_price = _first_float(position.get("entryPrice"), info.get("entryPrice"), info.get("price"), default=0.0)
        if size_abs <= 0 and notional and entry_price:
            size_abs = abs(notional / entry_price)
        side_raw = str(position.get("side") or info.get("side") or "flat").lower()
        signed_size = -abs(size_abs) if side_raw == "short" else abs(size_abs) if size_abs > 0 else 0.0
        mark_price = _first_float(position.get("markPrice"), info.get("markPrice"), info.get("indexPrice"), default=0.0)
        if mark_price <= 0:
            mark_price = self.get_market_mid_price(symbol)
        unrealized_pnl = _first_float(position.get("unrealizedPnl"), info.get("unrealizedPnl"), info.get("pnl"), default=0.0)
        leverage = _first_float(position.get("leverage"), info.get("leverage"), default=0.0) or 1.0
        margin_mode = str(position.get("marginMode") or info.get("marginMode") or "").lower()
        liquidation_price = _first_float(position.get("liquidationPrice"), info.get("liquidationPrice"), default=0.0)
        return KrakenPosition(
            symbol=position.get("symbol") or symbol,
            side="short" if signed_size < 0 else "long" if signed_size > 0 else "flat",
            size=signed_size,
            entry_price=entry_price,
            mark_price=mark_price,
            unrealized_pnl=unrealized_pnl,
            leverage=leverage,
            margin_mode=margin_mode,
            liquidation_price=liquidation_price,
        )

    def get_position(self, symbol: str) -> KrakenPosition:
        native = self._resolve_market_symbol(symbol)
        if self.venue == "spot":
            base = native.split("/", 1)[0]
            qty = self.get_balance(base)
            mid = self.get_market_mid_price(native)
            return KrakenPosition(native, "long" if qty > 0 else "flat", qty, 0.0, mid, 0.0, 1.0, margin_mode="spot")
        try:
            positions = self.client.fetch_positions([native])
        except Exception:
            positions = self.client.fetch_positions()
        for position in positions:
            parsed = self._parse_position(position, native)
            if abs(parsed.size) < 1e-12:
                continue
            if self._resolve_market_symbol(parsed.symbol) == native:
                return parsed
        return KrakenPosition(native, "flat", 0.0, 0.0, self.get_market_mid_price(native), 0.0, 1.0, margin_mode="")

    def get_all_positions(self) -> List[KrakenPosition]:
        if self.venue == "spot" or not getattr(self.client, "has", {}).get("fetchPositions"):
            return []
        positions: list[KrakenPosition] = []
        for raw in self.client.fetch_positions():
            parsed = self._parse_position(raw, raw.get("symbol", ""))
            if abs(parsed.size) > 1e-12:
                positions.append(parsed)
        return positions

    def round_quantity_to_increment(self, symbol: str, quantity: float) -> float:
        native = self._resolve_market_symbol(symbol)
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

    def configure_futures_risk_context(self, symbol: str, *, leverage: float | None = None, margin_mode: str | None = None) -> dict[str, Any]:
        native = self._resolve_market_symbol(symbol)
        result: dict[str, Any] = {}
        if margin_mode and getattr(self.client, "has", {}).get("setMarginMode"):
            result["set_margin_mode_response"] = self.client.set_margin_mode(str(margin_mode).lower(), native)
            result["margin_mode"] = str(margin_mode).lower()
        elif margin_mode:
            logger.info("%s nao expoe setMarginMode via CCXT; marginMode ira na ordem", self.exchange_id)
            result["margin_mode"] = str(margin_mode).lower()
        if leverage is not None and getattr(self.client, "has", {}).get("setLeverage"):
            result["response"] = self.client.set_leverage(int(round(float(leverage))), native)
            result["leverage"] = float(leverage)
        elif leverage is not None:
            logger.info("%s nao expoe setLeverage via CCXT; leverage ira na ordem", self.exchange_id)
            result["leverage"] = float(leverage)
        return result

    def place_market_order(
        self,
        symbol: str,
        quantity: float,
        is_buy: bool = True,
        reduce_only: bool = False,
        margin_mode: str | None = None,
        leverage: float | None = None,
    ) -> dict[str, Any]:
        native = self._resolve_market_symbol(symbol)
        side = "buy" if is_buy else "sell"
        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True
        if margin_mode:
            params["marginMode"] = str(margin_mode).lower()
        if leverage is not None:
            params["leverage"] = int(round(float(leverage)))
        logger.info("[%s %s] MARKET %s %s %s", self.exchange_id, self.venue, side.upper(), quantity, native)
        return self.client.create_order(native, "market", side, quantity, None, params)

    # Denylist, nao allowlist: o CCXT repassa status nao mapeados das venues
    # ("active", "triggered", "working"...). Uma allowlist rejeitava ordem
    # aceita, o chamador marcava a posicao como desprotegida, e o retry
    # anexava um segundo stop para a mesma quantidade.
    _REJECTED_ORDER_STATUS = {"canceled", "cancelled", "rejected", "expired", "failed"}

    def _validate_order_response(self, response: Any, *, what: str) -> dict[str, Any]:
        """Confirma que a corretora aceitou a ordem.

        Antes, qualquer objeto nao-`None` contava como sucesso: uma rejeicao
        estruturada passava por "protecao anexada". Como o chamador so testava
        `if order is None`, a posicao ficava sem protecao e ninguem sabia.
        """
        if not isinstance(response, dict) or not response.get("id"):
            raise VenueCapabilityError(
                f"{self.exchange_id} nao confirmou {what}: resposta sem id de ordem ({response!r})"
            )
        status = str(response.get("status") or "").lower()
        if status in self._REJECTED_ORDER_STATUS:
            raise VenueCapabilityError(
                f"{self.exchange_id} rejeitou {what}: status={status!r} (ordem {response.get('id')})"
            )
        return response

    def _require(self, capability: str, what: str) -> None:
        if not self.capabilities().get(capability):
            raise VenueCapabilityError(
                f"{self.exchange_id} ({self.venue}) nao expoe {what} nativo via CCXT. "
                "Enviar a ordem assim mesmo poderia virar uma ordem a mercado comum, "
                "dobrando a posicao em vez de protege-la."
            )

    def place_stop_loss(self, symbol: str, quantity: float, trigger_price: float, is_long: bool = True) -> dict[str, Any]:
        self._require("native_sl", "stop loss")
        native = self._resolve_market_symbol(symbol)
        side = "sell" if is_long else "buy"
        params: dict[str, Any] = {"stopLossPrice": trigger_price}
        if self.capabilities()["reduce_only"]:
            params["reduceOnly"] = True
        return self._validate_order_response(
            self.client.create_order(native, "market", side, quantity, None, params),
            what="stop loss",
        )

    def place_take_profit(self, symbol: str, quantity: float, trigger_price: float, is_long: bool = True) -> dict[str, Any]:
        self._require("native_tp", "take profit")
        native = self._resolve_market_symbol(symbol)
        side = "sell" if is_long else "buy"
        params: dict[str, Any] = {"takeProfitPrice": trigger_price}
        if self.capabilities()["reduce_only"]:
            params["reduceOnly"] = True
        return self._validate_order_response(
            self.client.create_order(native, "market", side, quantity, None, params),
            what="take profit",
        )

    def _has(self, *features: str) -> bool:
        table = getattr(self.client, "has", None) or {}
        return any(bool(table.get(name)) for name in features)

    def capabilities(self) -> Dict[str, bool]:
        """Le as capacidades do proprio CCXT em vez de declara-las.

        A versao anterior devolvia tudo `True` para qualquer exchange, sem
        consultar nada -- entao o diagnostico afirmava SL/TP nativo mesmo em
        venue que nao tem. O CCXT ja publica isso em `client.has`.
        """
        return {
            # Atado ao flag que gateia o param que este adapter envia. No CCXT
            # `stopLossPrice` e gated por `createStopLossOrder`;
            # `createTriggerOrder`/`createStopOrder` gateiam `triggerPrice`/
            # `stopPrice`, que nao usamos. Aceita-los admitiria 46 exchanges
            # onde o param seria descartado e a ordem viraria market comum.
            "native_sl": self._has("createStopLossOrder"),
            "native_tp": self._has("createTakeProfitOrder"),
            # `replace_stop_loss` cancela e recria; nunca chama `edit_order`.
            # Declarar `editOrder` prometeria edicao in-place que nao existe.
            "edit_stop": False,
            "cancel_trigger": self._has("cancelOrder"),
            # `reduceOnly` so faz sentido em derivativo; em spot nao existe
            # posicao a reduzir.
            "reduce_only": self.venue in {"swap", "future"},
        }

    def replace_stop_loss(
        self,
        symbol: str,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        previous_order_ref: dict | str | None = None,
        **_: object,
    ) -> dict[str, Any]:
        # Antes de tocar no stop que esta protegendo a posicao: se a recriacao
        # vai ser recusada, cancelar deixaria a posicao sem protecao alguma --
        # e o chamador ainda registraria o stop novo no estado.
        self._require("native_sl", "stop loss")
        order_id = previous_order_ref if isinstance(previous_order_ref, str) else None
        if isinstance(previous_order_ref, dict):
            order_id = str(previous_order_ref.get("id") or previous_order_ref.get("digest") or "")
        if not order_id:
            return {"cancelled": False, "order": None, "skipped_reason": "missing_previous_order_id"}
        self.cancel_order(order_id, symbol)
        order = self.place_stop_loss(symbol, quantity, trigger_price, is_long=is_long)
        return {"cancelled": True, "order": order}

    def cancel_all_orders(self, symbol: Optional[str] = None):
        native = self._resolve_market_symbol(symbol) if symbol else None
        if getattr(self.client, "has", {}).get("cancelAllOrders"):
            return self.client.cancel_all_orders(native)
        return [self.client.cancel_order(order["id"], native) for order in self.client.fetch_open_orders(native)]

    def cancel_order(self, order_id: str, symbol: Optional[str] = None):
        native = self._resolve_market_symbol(symbol) if symbol else None
        return self.client.cancel_order(order_id, native)

    def get_open_orders(self, symbol: Optional[str] = None):
        native = self._resolve_market_symbol(symbol) if symbol else None
        return self.client.fetch_open_orders(native)

    def get_market_order_conflicts(self, symbol: str, is_buy: bool) -> List[KrakenOrderConflict]:
        blocking_side = "sell" if is_buy else "buy"
        intended_side = "buy" if is_buy else "sell"
        conflicts: list[KrakenOrderConflict] = []
        for order in self.get_open_orders(symbol):
            side = str(order.get("side") or "").lower()
            if side != blocking_side:
                continue
            status = str(order.get("status") or "open").lower()
            if status not in {"open", "live"}:
                continue
            conflicts.append(
                KrakenOrderConflict(
                    order_id=str(order.get("id") or "?"),
                    side=side,
                    order_type=str(order.get("type") or "unknown"),
                    reason=f"ordem {side} aberta pode cruzar com market {intended_side}",
                )
            )
        return conflicts

    def close_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        pos = self.get_position(symbol)
        if abs(pos.size) < 1e-9:
            return None
        return self.place_market_order(symbol, abs(pos.size), is_buy=pos.size < 0, reduce_only=True)
