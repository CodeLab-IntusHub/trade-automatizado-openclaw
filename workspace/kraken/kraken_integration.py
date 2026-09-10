"""
Integração com Kraken (Spot via ccxt.kraken) e Kraken Futures (ccxt.krakenfutures).

Exposicao simétrica ao NadoTrader para permitir orquestração delta-neutral.
Docs oficiais:
  - REST Spot:    https://docs.kraken.com/rest/
  - Futures:      https://docs.kraken.com/api/docs/futures-api/trading/
  - ccxt wrapper: https://docs.ccxt.com/en/latest/manual.html
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import ccxt

from workspace.venues.order_validation import validate_order_response, wrap_replace_failure

logger = logging.getLogger(__name__)

# ─── Fees Kraken ─────────────────────────────────────────────────
# Volume mensal em USD → (maker_bps, taker_bps).
# Spot tiers: docs.kraken.com/rest/#tag/Spot-Trading/operation/getTradingFees
# Futures tiers: docs.kraken.com/api/docs/futures-api/trading/get-fee-schedule
KRAKEN_FEE_TIERS = {
    "spot": {
        "entry":   {"maker_bps": 25.0, "taker_bps": 40.0},  # $0 30d vol
        "mid":     {"maker_bps": 14.0, "taker_bps": 24.0},  # $100k+
        "pro":     {"maker_bps":  0.0, "taker_bps": 10.0},  # $10M+
    },
    "futures": {
        "entry":   {"maker_bps":  2.0, "taker_bps":  5.0},
        "mid":     {"maker_bps":  1.0, "taker_bps":  4.0},
        "pro":     {"maker_bps":  0.0, "taker_bps":  2.0},
    },
}


def get_kraken_fees(venue: str = "futures", tier: str = "entry") -> tuple[float, float]:
    """Retorna (maker_fee, taker_fee) em decimal. Ex: 0.00025 = 2.5 bps."""
    v = KRAKEN_FEE_TIERS.get(venue, KRAKEN_FEE_TIERS["futures"])
    t = v.get(tier, v["entry"])
    return (t["maker_bps"] / 10000, t["taker_bps"] / 10000)


@dataclass
class KrakenPosition:
    symbol: str
    side: str                # 'long' / 'short' / 'flat'
    size: float              # positivo = long, negativo = short
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float
    margin_mode: str = ""
    liquidation_price: float = 0.0
    initial_margin: float = 0.0


@dataclass(frozen=True)
class KrakenOrderConflict:
    order_id: str
    side: str
    order_type: str
    reason: str


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


class KrakenTrader:
    """
    Cliente unificado Kraken Spot + Futures.

    Por padrão roda em venue='futures' (perpétuos — usado no delta-neutral hedge).
    Permite também venue='spot' para farming de volume à vista.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        venue: str = "futures",   # 'futures' | 'spot'
        sandbox: bool = True,
        account: str | None = None,
        account_symbol: str | None = None,
        require_subaccount: bool = False,
        declared_is_subaccount: bool = False,
    ):
        self.venue = venue
        self.sandbox = sandbox
        self.account = (account or "flex").strip().lower() if venue == "futures" else None
        self.account_symbol = account_symbol.strip() if account_symbol else None
        self.require_subaccount = require_subaccount
        self.declared_is_subaccount = declared_is_subaccount
        self.api_fingerprint = _api_fingerprint(api_key) if api_key else ""

        if venue == "spot":
            self.client = ccxt.kraken({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
        elif venue == "futures":
            self.client = ccxt.krakenfutures({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            })
            if sandbox:
                # Endpoint demo.futures.kraken.com
                try:
                    self.client.set_sandbox_mode(True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("⚠️ Sandbox Kraken Futures indisponível: %s", exc)
        else:
            raise ValueError(f"venue inválido: {venue} (use 'spot' ou 'futures')")

        logger.info("✅ Cliente Kraken conectado (venue=%s, sandbox=%s)", venue, sandbox)
        if self.venue == "futures":
            logger.info(
                "   Account context: account=%s symbol=%s api=%s declared_subaccount=%s",
                self.account,
                self.account_symbol or "-",
                self.api_fingerprint or "-",
                "sim" if self.declared_is_subaccount else "nao",
            )
        try:
            self.client.load_markets()
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ load_markets falhou (credenciais?): %s", exc)

    def _normalize_account_name(self, account: str | None) -> str | None:
        if account is None:
            return None
        normalized = account.strip().lower()
        aliases = {
            "cashaccount": "cash",
            "main": "cash",
            "funding": "cash",
            "future": "cash",
            "multicollateral": "flex",
            "multicollateralmargin": "flex",
            "multicollateralmarginaccount": "flex",
            "marginaccount": "margin",
        }
        return aliases.get(normalized, normalized)

    def _normalize_account_symbol(self, symbol: str | None) -> str | None:
        if symbol is None:
            return None
        stripped = symbol.strip()
        if stripped in self.client.markets:
            return stripped
        return self.normalize_symbol(stripped)

    def _resolve_market_symbol(self, symbol: str) -> str:
        stripped = symbol.strip()
        if stripped in self.client.markets:
            return stripped
        normalized = self.normalize_symbol(stripped)
        if normalized in self.client.markets:
            return normalized
        return normalized

    def _build_balance_params(
        self,
        account: str | None = None,
        symbol: str | None = None,
    ) -> Dict[str, Any]:
        if self.venue != "futures":
            return {}
        selected = self._normalize_account_name(account or self.account)
        selected_symbol = self._normalize_account_symbol(symbol or self.account_symbol)
        if selected in (None, "", "flex", "cash"):
            return {"account": selected or "flex"}
        if selected == "margin":
            if selected_symbol is None:
                raise ValueError("KRAKEN_ACCOUNT_SYMBOL eh obrigatorio quando KRAKEN_ACCOUNT=margin")
            return {"account": "margin", "symbol": selected_symbol}
        if selected_symbol is not None and selected not in self.client.markets:
            return {"account": selected_symbol}
        if selected in self.client.markets:
            return {"account": selected}
        return {"account": selected}

    def get_account_context(self) -> Dict[str, Any]:
        return {
            "account": self.account,
            "account_symbol": self.account_symbol,
            "balance_params": self._build_balance_params(),
            "api_fingerprint": self.api_fingerprint,
            "declared_is_subaccount": self.declared_is_subaccount,
            "require_subaccount": self.require_subaccount,
        }

    def get_isolation_context(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "sandbox": self.sandbox,
            "account": self.account or "",
            "account_symbol": self.account_symbol or "",
            "api_fingerprint": self.api_fingerprint,
            "subaccount_mode": (
                "dedicated_api" if self.declared_is_subaccount else "master_or_unknown_api"
            ),
        }

    def get_subaccounts_metadata(self) -> Dict[str, Any]:
        if self.venue != "futures":
            return {}
        return self.client.request("subaccounts", "private", "GET", {})

    def detect_master_api_key(self) -> Optional[bool]:
        if self.venue != "futures":
            return None
        try:
            metadata = self.get_subaccounts_metadata()
        except Exception:
            return None
        # Kraken Futures exposes `masterAccountUid` on the master-account endpoint.
        return "masterAccountUid" in metadata

    def get_trading_safety(
        self,
        *,
        require_subaccount: Optional[bool] = None,
        declared_is_subaccount: Optional[bool] = None,
    ) -> Dict[str, Any]:
        require = self.require_subaccount if require_subaccount is None else require_subaccount
        declared = (
            self.declared_is_subaccount
            if declared_is_subaccount is None
            else declared_is_subaccount
        )
        if self.venue != "futures":
            return {
                "safe": True,
                "label": "safe",
                "reason": "venue spot nao exige isolamento de subconta Futures",
                "master_detected": None,
            }
        if not require:
            return {
                "safe": True,
                "label": "safe",
                "reason": "regra de subconta nao esta habilitada",
                "master_detected": None,
            }
        if not declared:
            return {
                "safe": False,
                "label": "unsafe",
                "reason": "KRAKEN_API_IS_SUBACCOUNT=false. Use uma API key dedicada da subconta.",
                "master_detected": None,
            }
        master_detected = self.detect_master_api_key()
        if master_detected is None:
            return {
                "safe": False,
                "label": "unsafe",
                "reason": "Nao foi possivel validar a metadata da Kraken. Rode `kraken-accounts` e confirme a API key da subconta.",
                "master_detected": None,
            }
        if master_detected is True:
            return {
                "safe": False,
                "label": "unsafe",
                "reason": "A API key atual aparenta ser de conta master na Kraken Futures.",
                "master_detected": True,
            }
        return {
            "safe": True,
            "label": "safe",
            "reason": "API key dedicada da subconta validada para trading.",
            "master_detected": False,
        }

    def validate_entry_subaccount_rule(
        self,
        *,
        require_subaccount: Optional[bool] = None,
        declared_is_subaccount: Optional[bool] = None,
    ) -> None:
        safety = self.get_trading_safety(
            require_subaccount=require_subaccount,
            declared_is_subaccount=declared_is_subaccount,
        )
        if safety["safe"]:
            return
        raise RuntimeError(str(safety["reason"]))

    def fetch_account_balance(
        self,
        *,
        account: str | None = None,
        symbol: str | None = None,
    ) -> Dict[str, Any]:
        params = self._build_balance_params(account=account, symbol=symbol)
        return self.client.fetch_balance(params)

    def get_accounts_overview(self) -> Dict[str, Any]:
        raw = self.client.fetch_balance()
        accounts = ((raw.get("info") or {}).get("accounts") or {})
        overview = []
        for name, data in accounts.items():
            entry: Dict[str, Any] = {
                "name": name,
                "type": data.get("type"),
            }
            if entry["type"] == "multiCollateralMarginAccount":
                entry["portfolio_value"] = _to_float(data.get("portfolioValue"))
                entry["available_margin"] = _to_float(data.get("availableMargin"))
                entry["currencies"] = sorted((data.get("currencies") or {}).keys())
            elif entry["type"] == "cashAccount":
                entry["balances"] = {
                    code: amount
                    for code, amount in {
                        code.upper(): _to_float(value)
                        for code, value in (data.get("balances") or {}).items()
                    }.items()
                    if abs(amount) > 0
                }
            else:
                auxiliary = data.get("auxiliary") or {}
                entry["currency"] = str(data.get("currency") or "").upper()
                entry["portfolio_value"] = _to_float(auxiliary.get("pv"))
                entry["available_funds"] = _to_float(auxiliary.get("af"))
            overview.append(entry)
        return {
            "selected": self.get_account_context(),
            "accounts": overview,
            "trading_safety": self.get_trading_safety(),
        }

    def transfer_between_accounts(
        self,
        code: str,
        amount: float,
        from_account: str,
        to_account: str,
    ):
        return self.client.transfer(code, amount, from_account, to_account)

    # ═══════════════════════════════════════════════════════════
    #  HELPERS DE SÍMBOLO
    # ═══════════════════════════════════════════════════════════
    def normalize_symbol(self, base: str) -> str:
        """
        Converte 'BTC/USDT' (Nado/Binance style) em símbolo Kraken.
        Futures perp:  'BTC/USD:USD' (PF_XBTUSD no protocolo).
        Spot:          'BTC/USD' ou 'BTC/USDT' se listado.
        """
        if "/" not in base:
            base = base + "/USDT"
        coin, quote = base.upper().split("/")
        if self.venue == "futures":
            candidates = [
                f"{coin}/USD:USD",
                f"{coin}/USD:{coin}",
            ]
            if coin == "BTC":
                candidates.extend(["XBT/USD:USD", "XBT/USD:XBT"])
            for candidate in candidates:
                if candidate in self.client.markets:
                    return candidate
            return candidates[0]
        # Spot: Kraken tem muitos /USDT e /USD; prefere /USDT se existir
        coin_k = "XBT" if coin == "BTC" else coin
        candidate = f"{coin_k}/USDT"
        if candidate in self.client.markets:
            return candidate
        return f"{coin_k}/USD"

    def get_symbol_to_product_map(self, product_filter: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Retorna mapa CCXT-style -> símbolo nativo Kraken.
        Filtra pelo subset passado (útil para casar com a lista da Nado).
        """
        out: Dict[str, str] = {}
        for m, data in self.client.markets.items():
            if self.venue == "futures" and not data.get("swap"):
                continue
            if self.venue == "spot" and not data.get("spot"):
                continue
            base = data.get("base", "")
            if base == "XBT":
                base = "BTC"
            pretty = f"{base}/USDT"
            if product_filter and pretty not in product_filter:
                continue
            out[pretty] = m
        return out

    # ═══════════════════════════════════════════════════════════
    #  CONSULTAS DE MERCADO
    # ═══════════════════════════════════════════════════════════
    def get_market_price(self, symbol: str) -> Dict[str, float]:
        symbol = self._resolve_market_symbol(symbol)
        ticker = self.client.fetch_ticker(symbol)
        bid = _to_float(ticker.get("bid"))
        ask = _to_float(ticker.get("ask"))
        mid = self._extract_mark_price(ticker)
        logger.info("📊 %s  bid=%.4f  ask=%.4f  mid=%.4f", symbol, bid, ask, mid)
        return {"bid_price": bid, "ask_price": ask, "mid_price": mid}

    def get_market_mid_price(self, symbol: str) -> float:
        symbol = self._resolve_market_symbol(symbol)
        return self._extract_mark_price(self.client.fetch_ticker(symbol))

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
            info.get("last"),
            info.get("lastPrice"),
            default=0.0,
        )

    def get_orderbook(self, symbol: str, depth: int = 10):
        symbol = self._resolve_market_symbol(symbol)
        book = self.client.fetch_order_book(symbol, limit=depth)
        logger.info("📖 %s orderbook top %d", symbol, depth)
        for price, qty in (book.get("asks") or [])[:5]:
            logger.info("   ASK  %.4f  |  %.6f", price, qty)
        for price, qty in (book.get("bids") or [])[:5]:
            logger.info("   BID  %.4f  |  %.6f", price, qty)
        return book

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Funding rate anualizada (apenas futures). Retorna decimal, ex 0.0001 = 1 bp."""
        if self.venue != "futures":
            return None
        try:
            symbol = self._resolve_market_symbol(symbol)
            fr = self.client.fetch_funding_rate(symbol)
            return float(fr.get("fundingRate") or fr.get("rate") or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ funding rate indisponível: %s", exc)
            return None

    # ═══════════════════════════════════════════════════════════
    #  SALDOS E POSIÇÕES
    # ═══════════════════════════════════════════════════════════
    def get_balance(self, asset: str = "USD") -> float:
        bal = self.fetch_account_balance()
        free = bal.get(asset, {}).get("free")
        if free is None:
            # Kraken às vezes renomeia USD em ZUSD
            free = bal.get(f"Z{asset}", {}).get("free", 0)
        return _to_float(free)

    def _parse_position(self, position: Dict[str, Any], symbol: str) -> KrakenPosition:
        info = position.get("info") or {}
        size_abs = _first_float(
            position.get("contracts"),
            info.get("size"),
            default=0.0,
        )
        if size_abs <= 0:
            notional = _first_float(position.get("notional"))
            entry_from_notional = _first_float(position.get("entryPrice"), info.get("price"))
            if notional and entry_from_notional:
                size_abs = abs(notional / entry_from_notional)
        side_raw = str(position.get("side") or info.get("side") or "flat").lower()
        if size_abs <= 0:
            side = "flat"
            signed_size = 0.0
        elif side_raw == "short":
            side = "short"
            signed_size = -abs(size_abs)
        else:
            side = "long"
            signed_size = abs(size_abs)

        entry_price = _first_float(
            position.get("entryPrice"),
            info.get("price"),
            info.get("entryPrice"),
            default=0.0,
        )
        mark_price = _first_float(
            position.get("markPrice"),
            info.get("markPrice"),
            info.get("indexPrice"),
            default=0.0,
        )
        if mark_price <= 0:
            mark_price = self.get_market_mid_price(symbol)

        unrealized_pnl = _first_float(
            position.get("unrealizedPnl"),
            info.get("unrealizedPnl"),
            info.get("pnl"),
            default=0.0,
        )
        if signed_size and unrealized_pnl == 0.0 and entry_price > 0 and mark_price > 0:
            unrealized_pnl = signed_size * (mark_price - entry_price)

        leverage = _first_float(
            position.get("leverage"),
            info.get("leverage"),
            default=0.0,
        )
        initial_margin = _first_float(position.get("initialMargin"), info.get("initialMargin"))
        if leverage <= 0 and signed_size and mark_price > 0:
            collateral = _first_float(position.get("collateral"))
            denominator = initial_margin or collateral
            if denominator > 0:
                leverage = abs(signed_size * mark_price) / denominator
        if leverage <= 0:
            leverage = 1.0

        margin_mode = str(
            position.get("marginMode")
            or position.get("marginType")
            or info.get("marginMode")
            or info.get("marginType")
            or ""
        ).lower()
        liquidation_price = _first_float(
            position.get("liquidationPrice"),
            info.get("liquidationPrice"),
            info.get("liquidation"),
            default=0.0,
        )

        return KrakenPosition(
            symbol=position.get("symbol") or symbol,
            side=side,
            size=signed_size,
            entry_price=entry_price,
            mark_price=mark_price,
            unrealized_pnl=unrealized_pnl,
            leverage=leverage,
            margin_mode=margin_mode,
            liquidation_price=liquidation_price,
            initial_margin=initial_margin,
        )

    def get_position(self, symbol: str) -> KrakenPosition:
        if self.venue != "futures":
            # Spot: "posição" é o saldo da moeda base
            base = symbol.split("/")[0]
            qty = self.get_balance(base)
            mid = self.get_market_mid_price(symbol)
            return KrakenPosition(
                symbol=symbol, side="long" if qty > 0 else "flat",
                size=qty, entry_price=0.0, mark_price=mid,
                unrealized_pnl=0.0, leverage=1.0,
                margin_mode="spot",
            )
        symbol = self._resolve_market_symbol(symbol)
        try:
            positions = self.client.fetch_positions([symbol])
        except Exception:
            positions = self.client.fetch_positions()
        for p in positions:
            parsed = self._parse_position(p, symbol)
            if abs(parsed.size) < 1e-12:
                continue
            parsed_symbol = self._resolve_market_symbol(parsed.symbol)
            if parsed_symbol == symbol:
                return parsed
        return KrakenPosition(
            symbol=symbol,
            side="flat",
            size=0.0,
            entry_price=0.0,
            mark_price=self.get_market_mid_price(symbol),
            unrealized_pnl=0.0,
            leverage=1.0,
            margin_mode="",
        )

    def get_all_positions(self) -> List[KrakenPosition]:
        if self.venue != "futures":
            return []
        out = []
        for p in self.client.fetch_positions():
            parsed = self._parse_position(p, p.get("symbol", "?"))
            if abs(parsed.size) < 1e-12:
                continue
            out.append(parsed)
        return out

    # ═══════════════════════════════════════════════════════════
    #  ORDENS
    # ═══════════════════════════════════════════════════════════
    def round_quantity_to_increment(self, symbol: str, quantity: float) -> float:
        symbol = self._resolve_market_symbol(symbol)
        market = self.client.market(symbol)
        precision = market.get("precision", {}).get("amount")
        min_amount = market.get("limits", {}).get("amount", {}).get("min") or 0
        if precision is not None:
            # ccxt precision pode ser int (nº de casas) ou float (step)
            if isinstance(precision, int):
                step = 10 ** (-precision)
            else:
                step = float(precision)
            n = int(quantity / step)
            qty = round(n * step, 12)
        else:
            qty = quantity
        if qty < min_amount:
            return 0.0
        return qty

    def configure_futures_risk_context(
        self,
        symbol: str,
        *,
        leverage: float | None = None,
        margin_mode: str | None = None,
    ) -> dict[str, Any]:
        symbol = self._resolve_market_symbol(symbol)
        if self.venue != "futures":
            return {}

        result: dict[str, Any] = {}
        if margin_mode:
            normalized_margin_mode = str(margin_mode).strip().lower()
            if normalized_margin_mode not in {"cross", "isolated"}:
                raise ValueError(f"margin mode '{margin_mode}' invalido para Kraken Futures")
            logger.info("[Kraken %s] margin mode solicitado para %s: %s", self.venue, symbol, normalized_margin_mode)
            if normalized_margin_mode == "cross":
                has_set_margin_mode = bool(getattr(self.client, "has", {}).get("setMarginMode"))
                if has_set_margin_mode and hasattr(self.client, "set_margin_mode"):
                    try:
                        result["set_margin_mode_response"] = self.client.set_margin_mode("cross", symbol)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(f"falha ao ajustar margin mode cross em {symbol}: {exc}") from exc
                else:
                    logger.info("   margin mode cross sera validado pelo contexto/posicao apos a ordem")
            else:
                logger.info("   isolated sera enviado como parametro nativo de ordem e validado apos fill")
            result["margin_mode"] = normalized_margin_mode
            result["margin_mode_enforced"] = normalized_margin_mode == "cross" and "set_margin_mode_response" in result

        if leverage is not None:
            leverage_value = int(round(float(leverage)))
            if leverage_value < 1:
                raise ValueError(f"leverage invalida para Kraken Futures: {leverage}")
            logger.info("⚙️ [Kraken %s] ajustando leverage para %sx em %s", self.venue, leverage_value, symbol)
            try:
                response = self.client.set_leverage(leverage_value, symbol)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"falha ao ajustar leverage {leverage_value}x em {symbol}: {exc}"
                ) from exc
            logger.info("   ✅ leverage configurada para %sx", leverage_value)
            result["leverage"] = float(leverage_value)
            result["response"] = response

        return result

    def place_market_order(
        self,
        symbol: str,
        quantity: float,
        is_buy: bool = True,
        reduce_only: bool = False,
        margin_mode: str | None = None,
        leverage: float | None = None,
    ):
        symbol = self._resolve_market_symbol(symbol)
        side = "buy" if is_buy else "sell"
        params: Dict[str, Any] = {}
        if reduce_only and self.venue == "futures":
            params["reduceOnly"] = True
        if self.venue == "futures" and margin_mode:
            params["marginMode"] = str(margin_mode).strip().lower()
        if self.venue == "futures" and leverage is not None:
            params["leverage"] = int(round(float(leverage)))
        logger.info("⚡ [Kraken %s] MARKET %s %s %s", self.venue, side.upper(), quantity, symbol)
        order = self.client.create_order(symbol, "market", side, quantity, None, params)
        logger.info("   ✅ id=%s status=%s", order.get("id"), order.get("status"))
        return order

    def place_limit_order(
        self,
        symbol: str,
        price: float,
        quantity: float,
        is_buy: bool = True,
        post_only: bool = False,
        reduce_only: bool = False,
    ):
        symbol = self._resolve_market_symbol(symbol)
        side = "buy" if is_buy else "sell"
        params: Dict[str, Any] = {}
        if post_only:
            params["postOnly"] = True
        if reduce_only and self.venue == "futures":
            params["reduceOnly"] = True
        logger.info("📝 [Kraken %s] LIMIT %s %s @ %.4f %s", self.venue, side.upper(), quantity, price, symbol)
        order = self.client.create_order(symbol, "limit", side, quantity, price, params)
        logger.info("   ✅ id=%s status=%s", order.get("id"), order.get("status"))
        return order

    def place_stop_loss(
        self,
        symbol: str,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
    ):
        symbol = self._resolve_market_symbol(symbol)
        side = "sell" if is_long else "buy"
        params = {"stopLossPrice": trigger_price, "reduceOnly": True}
        logger.info("🛑 [Kraken %s] SL %s %s trigger=%.4f", self.venue, side, quantity, trigger_price)
        return validate_order_response(
            self.client.create_order(symbol, "market", side, quantity, None, params),
            exchange_id=f"kraken-{self.venue}",
            what="stop loss",
        )

    def place_take_profit(
        self,
        symbol: str,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
    ):
        symbol = self._resolve_market_symbol(symbol)
        side = "sell" if is_long else "buy"
        params = {"takeProfitPrice": trigger_price, "reduceOnly": True}
        logger.info("🎯 [Kraken %s] TP %s %s trigger=%.4f", self.venue, side, quantity, trigger_price)
        return validate_order_response(
            self.client.create_order(symbol, "market", side, quantity, None, params),
            exchange_id=f"kraken-{self.venue}",
            what="take profit",
        )

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
        symbol: str,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        previous_order_ref: dict | str | None = None,
        **_: object,
    ) -> dict:
        order_id = previous_order_ref if isinstance(previous_order_ref, str) else None
        if isinstance(previous_order_ref, dict):
            order_id = str(previous_order_ref.get("id") or previous_order_ref.get("digest") or "")
        if not order_id:
            return {"cancelled": False, "order": None, "skipped_reason": "missing_previous_order_id"}
        self.cancel_order(order_id, symbol)
        try:
            order = self.place_stop_loss(symbol, quantity, trigger_price, is_long=is_long)
        except Exception as exc:
            raise wrap_replace_failure(exc, symbol=symbol, cancelled_order_id=order_id) from exc
        return {"cancelled": True, "order": order}

    def place_market_order_with_tp_sl(
        self,
        symbol: str,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        is_buy: bool = True,
        verify_fill_wait_secs: float = 2.0,
    ):
        """Abre posição + anexa SL e TP reduce-only."""
        logger.info("⚡ [Kraken] Market + SL + TP %s qty=%s SL=%.4f TP=%.4f",
                    symbol, quantity, stop_loss, take_profit)
        order = self.place_market_order(symbol, quantity, is_buy)
        time.sleep(verify_fill_wait_secs)
        # Verifica posição antes de anexar SL/TP
        pos = self.get_position(symbol)
        if abs(pos.size) < quantity * 0.99:
            logger.warning("   ⚠️ Fill parcial detectado (size=%.6f esperado=%.6f) — SL/TP não enviados.",
                           pos.size, quantity if is_buy else -quantity)
            return order
        try:
            self.place_stop_loss(symbol, quantity, stop_loss, is_long=is_buy)
            self.place_take_profit(symbol, quantity, take_profit, is_long=is_buy)
            logger.info("   ✅ SL + TP anexados")
        except Exception as exc:  # noqa: BLE001
            logger.error("   ❌ Falha ao anexar SL/TP: %s", exc)
        return order

    def cancel_all_orders(self, symbol: Optional[str] = None):
        symbol = self._resolve_market_symbol(symbol) if symbol else None
        try:
            return self.client.cancel_all_orders(symbol)
        except ccxt.NotSupported:
            orders = self.client.fetch_open_orders(symbol)
            return [self.client.cancel_order(o["id"], symbol) for o in orders]

    def cancel_order(self, order_id: str, symbol: Optional[str] = None):
        symbol = self._resolve_market_symbol(symbol) if symbol else None
        return self.client.cancel_order(order_id, symbol)

    def get_open_orders(self, symbol: Optional[str] = None):
        symbol = self._resolve_market_symbol(symbol) if symbol else None
        return self.client.fetch_open_orders(symbol)

    def get_market_order_conflicts(self, symbol: str, is_buy: bool) -> List[KrakenOrderConflict]:
        intended_side = "buy" if is_buy else "sell"
        blocking_side = "sell" if is_buy else "buy"
        conflicts: List[KrakenOrderConflict] = []
        for order in self.get_open_orders(symbol):
            side = str(order.get("side") or "").lower()
            if side != blocking_side:
                continue
            status = str(order.get("status") or "open").lower()
            if status not in {"open", "live"}:
                continue
            order_id = str(order.get("id") or "?")
            order_type = str(order.get("type") or order.get("info", {}).get("type") or "unknown")
            conflicts.append(
                KrakenOrderConflict(
                    order_id=order_id,
                    side=side,
                    order_type=order_type,
                    reason=(
                        f"ordem {side} aberta pode cruzar com market {intended_side} "
                        f"e gerar selfFill"
                    ),
                )
            )
        return conflicts

    def close_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fecha a posição inteira no símbolo. Retorna a ordem ou None se já flat."""
        pos = self.get_position(symbol)
        if abs(pos.size) < 1e-9:
            logger.info("   posição já flat em %s", symbol)
            return None
        qty = abs(pos.size)
        is_buy = pos.size < 0
        conflicts = self.get_market_order_conflicts(symbol, is_buy=is_buy)
        if conflicts:
            ids = ", ".join(c.order_id for c in conflicts)
            raise RuntimeError(f"conflito de ordens abertas em {symbol}: {ids}")
        logger.info("🧹 [Kraken] fechando %s: size=%.6f → ordem %s qty=%.6f",
                    symbol, pos.size, "BUY" if is_buy else "SELL", qty)
        return self.place_market_order(symbol, qty, is_buy=is_buy, reduce_only=True)
