"""
Integração com a Nado DEX (Python SDK).

Classe NadoTrader e constantes para trading na Nado Protocol.
Documentação: https://docs.nado.xyz
SDK: https://nadohq.github.io/nado-python-sdk/
"""

import time
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from eth_account import Account

from workspace.nado.units import from_x18, from_x6  # noqa: F401  (reexport: conversao sem SDK)
from workspace.venues.order_validation import wrap_replace_failure

from nado_protocol.client import create_nado_client, NadoClientMode
from nado_protocol.engine_client.types.execute import (
    OrderParams,
    PlaceOrderParams,
    PlaceMarketOrderParams,
    CancelOrdersParams,
    WithdrawCollateralParams,
)
from nado_protocol.contracts.types import DepositCollateralParams
from nado_protocol.utils.bytes32 import subaccount_to_bytes32, subaccount_to_hex
from nado_protocol.utils.execute import MarketOrderParams
from nado_protocol.utils.expiration import OrderType, get_expiration_timestamp
from nado_protocol.utils.order import build_appendix
from nado_protocol.utils.math import round_x18, to_pow_10, to_x18
from nado_protocol.utils.nonce import gen_order_nonce
from nado_protocol.utils.subaccount import SubaccountParams
from nado_protocol.trigger_client.types.query import (
    ListTriggerOrdersParams,
    ListTriggerOrdersTx,
    TriggerOrderStatusType,
    TriggerType,
)

# ─── Logging ─────────────────────────────────────────────────
logger = logging.getLogger(__name__)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
NADO_ISOLATED_MARGIN_SCALE = 10**6

# ─── Fees Nado (docs.nado.xyz/fees-and-rebates) ──────────────
# Tiers baseados em volume 30d (maker + taker). Fees em bps (0.01%).
NADO_FEE_TIERS = {
    "entry": {"taker_bps": 3.5, "maker_bps": 1.0},    # $0 volume
    "mid": {"taker_bps": 3.0, "maker_bps": 0.5},      # $25M+ volume
    "elite": {"taker_bps": 1.5, "maker_bps": -0.8},   # $5B+ volume (maker rebate)
}


def get_nado_fees(tier: str = "entry") -> tuple[float, float]:
    """
    Retorna (maker_fee, taker_fee) em decimal (ex: 0.00035 = 3.5 bps).
    tier: 'entry' | 'mid' | 'elite'
    """
    t = NADO_FEE_TIERS.get(tier, NADO_FEE_TIERS["entry"])
    maker = t["maker_bps"] / 10000
    taker = t["taker_bps"] / 10000
    return (maker, taker)


# ─── Constantes de Product IDs ───────────────────────────────
# Verifique os IDs com trader.get_all_products()
# IDs podem variar entre testnet e mainnet.
USDT0_SPOT = 0   # USDT0 (colateral principal)
BTC_PERP   = 2   # BTC-PERP
ETH_PERP   = 4   # ETH-PERP
SOL_PERP   = 6   # SOL-PERP
BNB_PERP   = 8   # BNB-PERP
XRP_PERP   = 10  # XRP-PERP
DOGE_PERP  = 12  # DOGE-PERP
AVAX_PERP  = 14  # AVAX-PERP
ARB_PERP   = 16  # ARB-PERP
OP_PERP    = 18  # OP-PERP




def _normalize_address(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _short_hex(value: str | None, *, prefix: int = 10, suffix: int = 8) -> str:
    if not value:
        return "-"
    raw = str(value)
    if len(raw) <= prefix + suffix + 3:
        return raw
    return f"{raw[:prefix]}...{raw[-suffix:]}"


@dataclass
class NadoPosition:
    symbol: str
    product_id: int
    side: str
    size: float
    mark_price: float
    notional_usd: float
    margin_mode: str
    liquidation_price: float = 0.0


def _first_nested_float(*values: Any) -> float:
    """Best-effort parser for SDK fields that may be attrs, dicts or x18 ints."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _first_nested_float(
                value.get("liquidation_price"),
                value.get("liquidationPrice"),
                value.get("liq_price"),
                value.get("liqPrice"),
                value.get("price"),
                value.get("amount"),
                value.get("amount_x18"),
            )
            if nested > 0:
                return nested
            continue
        amount = getattr(value, "amount", None) or getattr(value, "amount_x18", None)
        if amount is not None:
            try:
                parsed = float(amount)
                if parsed > 1e10:
                    parsed /= 1e18
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                pass
        try:
            parsed = float(value)
            if parsed > 1e10:
                parsed /= 1e18
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            continue
    return 0.0


def _extract_liquidation_price(raw: Any) -> float:
    return _first_nested_float(
        getattr(raw, "liquidation_price", None),
        getattr(raw, "liquidationPrice", None),
        getattr(raw, "liquidation", None),
        getattr(raw, "liq_price", None),
        getattr(raw, "liqPrice", None),
        getattr(raw, "estimated_liquidation_price", None),
        getattr(raw, "estimatedLiquidationPrice", None),
    )


class NadoTrader:
    """
    Cliente para interação com a Nado DEX.

    Usa o SDK nado-protocol para ordens, depósitos, consultas de mercado, etc.
    """

    def __init__(
        self,
        owner_private_key: str,
        network: str = "testnet",
        subaccount_name: str = "default_1",
        linked_signer_private_key: Optional[str] = None,
        require_linked_signer: bool = True,
        allow_owner_fallback: bool = False,
    ):
        cleaned_subaccount_name = (subaccount_name or "").strip()
        if not cleaned_subaccount_name:
            raise ValueError("NADO_SUBACCOUNT_NAME nao pode ficar vazio.")
        mode = (
            NadoClientMode.TESTNET if network == "testnet"
            else NadoClientMode.MAINNET
        )
        self.client = create_nado_client(mode, owner_private_key)
        self.network = network
        self.require_linked_signer = bool(require_linked_signer)
        self.allow_owner_fallback = bool(allow_owner_fallback)
        self.owner_private_key = owner_private_key
        self.linked_signer_private_key = (linked_signer_private_key or "").strip() or None
        self.owner = self.client.context.engine_client.signer.address
        self.owner_address = self.owner
        self.subaccount_name = cleaned_subaccount_name
        self.subaccount_params = SubaccountParams(
            subaccount_owner=self.owner,
            subaccount_name=self.subaccount_name,
        )
        self.subaccount_hex = subaccount_to_hex(self.subaccount_params)
        self.linked_signer_address: Optional[str] = None
        self.linked_signer_onchain: Optional[str] = None
        self.linked_signer_query_error: Optional[str] = None
        self.trade_auth_error: Optional[str] = None
        self.signer_mode = "owner_only"

        self._configure_linked_signer()
        self._refresh_trade_auth_state()

        logger.info(f"✅ Cliente Nado conectado ({network})")
        logger.info(
            "   Subaccount: %s (%s)",
            self.subaccount_name,
            _short_hex(self.subaccount_hex, prefix=14, suffix=10),
        )
        logger.info(
            "   Owner: %s | linked: %s | mode=%s | trade_ready=%s",
            _short_hex(self.owner_address),
            _short_hex(self.linked_signer_address),
            self.signer_mode,
            "sim" if self.is_trade_ready() else "nao",
        )
        if self.trade_auth_error:
            logger.warning("   %s", self.trade_auth_error)

    def _configure_linked_signer(self) -> None:
        if not self.linked_signer_private_key:
            return
        linked_account = Account.from_key(self.linked_signer_private_key)
        self.client.context.engine_client.linked_signer = linked_account
        if self.client.context.trigger_client is not None:
            self.client.context.trigger_client.linked_signer = linked_account
        self.linked_signer_address = linked_account.address
        self.signer_mode = "linked"

    def _use_owner_fallback(self) -> None:
        self.signer_mode = "owner_fallback"
        self.linked_signer_private_key = None
        self.linked_signer_address = None
        self.client.context.engine_client.linked_signer = None
        if self.client.context.trigger_client is not None:
            self.client.context.trigger_client.linked_signer = None

    def _fetch_onchain_linked_signer(self) -> Optional[str]:
        self.linked_signer_query_error = None
        try:
            linked_signer_data = self.client.context.engine_client.get_linked_signer(
                self.subaccount_hex
            )
        except Exception as exc:  # noqa: BLE001
            self.linked_signer_query_error = str(exc)
            return None
        linked_signer = getattr(linked_signer_data, "linked_signer", None)
        if _normalize_address(linked_signer) in {"", _normalize_address(ZERO_ADDRESS)}:
            return None
        return str(linked_signer)

    def _refresh_trade_auth_state(self) -> None:
        self.linked_signer_onchain = self._fetch_onchain_linked_signer()
        self.trade_auth_error = None
        configured = _normalize_address(self.linked_signer_address)
        onchain = _normalize_address(self.linked_signer_onchain)
        if self.require_linked_signer and not self.linked_signer_private_key:
            if getattr(self, "allow_owner_fallback", False):
                self._use_owner_fallback()
                return
            self.trade_auth_error = (
                "NADO_LINKED_SIGNER_PRIVATE_KEY ausente. "
                "Novos trades so podem rodar na subconta com linked signer dedicado."
            )
            return
        if self.linked_signer_private_key and self.linked_signer_query_error:
            if getattr(self, "allow_owner_fallback", False):
                self._use_owner_fallback()
                return
            self.trade_auth_error = (
                "Nao foi possivel validar o linked signer on-chain da subconta "
                f"{self.subaccount_name}: {self.linked_signer_query_error}"
            )
            return
        if self.require_linked_signer and not onchain:
            if getattr(self, "allow_owner_fallback", False):
                self._use_owner_fallback()
                return
            self.trade_auth_error = (
                f"A subconta {self.subaccount_name} nao possui linked signer on-chain validado."
            )
            return
        if configured and onchain and configured != onchain:
            if getattr(self, "allow_owner_fallback", False):
                self._use_owner_fallback()
                return
            self.trade_auth_error = (
                "O linked signer configurado nao bate com o linked signer on-chain da subconta."
            )

    def is_trade_ready(self) -> bool:
        return self.trade_auth_error is None

    def assert_trade_ready(self) -> None:
        self._refresh_trade_auth_state()
        if self.trade_auth_error:
            raise RuntimeError(self.trade_auth_error)

    def get_isolation_context(self) -> Dict[str, Any]:
        self._refresh_trade_auth_state()
        return {
            "network": self.network,
            "subaccount_name": self.subaccount_name,
            "subaccount_hex": self.subaccount_hex,
            "owner_address": self.owner_address,
            "linked_signer_address": self.linked_signer_address or "",
            "linked_signer_onchain": self.linked_signer_onchain or "",
            "signer_mode": self.signer_mode,
            "require_linked_signer": self.require_linked_signer,
            "allow_owner_fallback": self.allow_owner_fallback,
            "trade_ready": self.is_trade_ready(),
            "trade_auth_error": self.trade_auth_error or "",
        }

    # ═══════════════════════════════════════════════════════════
    #  CONSULTAS DE MERCADO
    # ═══════════════════════════════════════════════════════════

    def get_symbol_to_product_map(self) -> dict:
        """
        Retorna mapeamento dinâmico CCXT symbol → product_id.
        Ex: {"BTC/USDT": 2, "ETH/USDT": 4, "HYPE/USDT": 16, ...}

        IDs variam entre testnet/mainnet; esta consulta garante o mapeamento
        correto para a rede atual (evita ARB→HYPE, OP→ZEC por IDs errados).
        """
        result = {}
        try:
            symbols = self.client.market.get_all_product_symbols()
            products = self.client.context.engine_client.get_all_products()
            perp_ids = {
                p.product_id if hasattr(p, "product_id") else p
                for p in products.perp_products
            }
            for s in symbols:
                pid = getattr(s, "product_id", None)
                if pid is None or pid not in perp_ids:
                    continue
                sym = getattr(s, "symbol", "")
                if sym and "-PERP" in sym.upper():
                    base = sym.split("-")[0].strip()
                    if base:
                        result[f"{base}/USDT"] = pid
        except Exception as e:
            logger.warning("⚠️ Falha ao obter mapeamento de símbolos: %s", e)
        return result

    def get_all_products(self):
        """Lista todos os produtos disponíveis (spot + perp) com símbolos."""
        products = self.client.context.engine_client.get_all_products()
        symbols_map = {}
        try:
            symbols = self.client.market.get_all_product_symbols()
            for s in symbols:
                symbols_map[s.product_id] = getattr(s, "symbol", str(s.product_id))
        except Exception:
            pass

        def _fmt(pid):
            sym = symbols_map.get(pid, "")
            return f"  ID {pid} ({sym})" if sym else f"  ID {pid}"

        logger.info("═══ PRODUTOS SPOT ═══")
        for p in products.spot_products:
            pid = p.product_id if hasattr(p, "product_id") else p
            logger.info(_fmt(pid))
        logger.info("═══ PRODUTOS PERP ═══")
        for p in products.perp_products:
            pid = p.product_id if hasattr(p, "product_id") else p
            logger.info(_fmt(pid))
        return products

    def get_market_price(self, product_id: int) -> dict:
        """Retorna bid/ask/mid de um produto."""
        market = self.client.context.engine_client.get_market_price(product_id)
        bid = from_x18(market.bid_x18)
        ask = from_x18(market.ask_x18)
        mid = (bid + ask) / 2
        logger.info(f"📊 Preço produto {product_id}:")
        logger.info(f"   Bid: ${bid:,.2f}  |  Ask: ${ask:,.2f}  |  Mid: ${mid:,.2f}")
        return {"bid_price": bid, "ask_price": ask, "mid_price": mid}

    def get_market_mid_price(self, product_id: int) -> float:
        """Retorna apenas o preço mid do produto (sem log). Útil para cálculos de tamanho."""
        market = self.client.context.engine_client.get_market_price(product_id)
        bid = from_x18(market.bid_x18)
        ask = from_x18(market.ask_x18)
        return (bid + ask) / 2

    def get_orderbook(self, product_id: int, depth: int = 10):
        """Retorna o orderbook de um produto."""
        orderbook = self.client.context.engine_client.get_market_liquidity(
            product_id, depth
        )
        logger.info(f"📖 Orderbook produto {product_id} (top {depth}):")

        def parse_level(level):
            if isinstance(level, (list, tuple)):
                return from_x18(level[0]), from_x18(level[1])
            elif hasattr(level, "price_x18"):
                return from_x18(level.price_x18), from_x18(level.quantity_x18)
            elif hasattr(level, "price"):
                return from_x18(level.price), from_x18(level.quantity)
            elif isinstance(level, dict):
                p = level.get("price_x18") or level.get("price", 0)
                q = level.get("quantity_x18") or level.get("quantity", 0)
                return from_x18(p), from_x18(q)
            return 0, 0

        logger.info("   ── ASKS (vendedores) ──")
        for level in (orderbook.asks or [])[:5]:
            price, qty = parse_level(level)
            logger.info(f"   ${price:>12,.2f}  |  {qty:>12.6f}")
        logger.info("   ── BIDS (compradores) ──")
        for level in (orderbook.bids or [])[:5]:
            price, qty = parse_level(level)
            logger.info(f"   ${price:>12,.2f}  |  {qty:>12.6f}")
        return orderbook

    # ═══════════════════════════════════════════════════════════
    #  DEPÓSITOS / SAQUES
    # ═══════════════════════════════════════════════════════════

    def get_perp_position_size(self, product_id: int) -> float:
        """Retorna o tamanho total da posição perp.

        A Nado expõe posições cross em `subaccount_info.perp_balances` e posições
        isolated em `isolated_positions`. Para refletir a exposição real da conta,
        somamos os dois caminhos.
        """
        cross_qty = 0.0
        info = self.client.context.engine_client.get_subaccount_info(self.subaccount_hex)
        for position in info.perp_balances:
            pid = getattr(position, "product_id", None)
            if pid == product_id:
                bal = getattr(position, "balance", position)
                for attr in ["amount", "amount_x18"]:
                    val = getattr(bal, attr, None)
                    if val is not None and str(val) != "0":
                        cross_qty = float(val) / 1e18
                        break
                break

        isolated_qty = 0.0
        try:
            isolated_data = self.client.context.engine_client.get_isolated_positions(
                self.subaccount_hex
            )
            for isolated in getattr(isolated_data, "isolated_positions", []) or []:
                base_product = getattr(isolated, "base_product", None)
                if getattr(base_product, "product_id", None) != product_id:
                    continue
                base_balance = getattr(isolated, "base_balance", None)
                balance = getattr(base_balance, "balance", base_balance)
                amount = getattr(balance, "amount", None) or getattr(balance, "amount_x18", None)
                if amount is not None and str(amount) != "0":
                    isolated_qty += float(amount) / 1e18
        except Exception:
            pass

        return cross_qty + isolated_qty

    def get_all_positions(self) -> list[NadoPosition]:
        """Lista posições perp não-zero, incluindo cross e isolated."""
        symbol_map = self.get_symbol_to_product_map()
        product_to_symbol = {pid: symbol for symbol, pid in symbol_map.items()}

        cross_amounts: Dict[int, float] = {}
        liquidation_prices: Dict[int, float] = {}
        info = self.client.context.engine_client.get_subaccount_info(self.subaccount_hex)
        for position in info.perp_balances:
            pid = getattr(position, "product_id", None)
            bal = getattr(position, "balance", position)
            amount = getattr(bal, "amount", None) or getattr(bal, "amount_x18", None)
            if pid is not None and amount is not None and str(amount) != "0":
                cross_amounts[int(pid)] = cross_amounts.get(int(pid), 0.0) + float(amount) / 1e18
                liq = _extract_liquidation_price(position)
                if liq > 0:
                    liquidation_prices[int(pid)] = liq

        isolated_amounts: Dict[int, float] = {}
        try:
            isolated_data = self.client.context.engine_client.get_isolated_positions(
                self.subaccount_hex
            )
            for isolated in getattr(isolated_data, "isolated_positions", []) or []:
                base_product = getattr(isolated, "base_product", None)
                pid = getattr(base_product, "product_id", None)
                base_balance = getattr(isolated, "base_balance", None)
                balance = getattr(base_balance, "balance", base_balance)
                amount = getattr(balance, "amount", None) or getattr(balance, "amount_x18", None)
                if pid is not None and amount is not None and str(amount) != "0":
                    isolated_amounts[int(pid)] = isolated_amounts.get(int(pid), 0.0) + float(amount) / 1e18
                    liq = _extract_liquidation_price(isolated)
                    if liq > 0:
                        liquidation_prices[int(pid)] = liq
        except Exception:
            pass

        positions: list[NadoPosition] = []
        for pid in sorted(set(cross_amounts) | set(isolated_amounts)):
            size = cross_amounts.get(pid, 0.0) + isolated_amounts.get(pid, 0.0)
            if abs(size) < 1e-12:
                continue
            mark_price = self.get_market_mid_price(pid)
            cross_present = abs(cross_amounts.get(pid, 0.0)) > 1e-12
            isolated_present = abs(isolated_amounts.get(pid, 0.0)) > 1e-12
            if cross_present and isolated_present:
                margin_mode = "mixed"
            elif isolated_present:
                margin_mode = "isolated"
            else:
                margin_mode = "cross"
            positions.append(
                NadoPosition(
                    symbol=product_to_symbol.get(pid, f"PID:{pid}"),
                    product_id=pid,
                    side="long" if size > 0 else "short",
                    size=size,
                    mark_price=mark_price,
                    notional_usd=abs(size * mark_price),
                    margin_mode=margin_mode,
                    liquidation_price=liquidation_prices.get(pid, 0.0),
                )
            )
        return positions

    def get_usdt0_balance(self) -> float:
        """Retorna o saldo USDT0 na Nado (subaccount spot)."""
        info = self.client.context.engine_client.get_subaccount_info(self.subaccount_hex)
        for balance in info.spot_balances:
            if getattr(balance, "product_id", None) == USDT0_SPOT:
                bal = getattr(balance, "balance", balance)
                for attr in ["amount", "amount_x18", "balance_amount"]:
                    val = getattr(bal, attr, None)
                    if val is not None and str(val) != "0":
                        return float(val) / 1e18
                return 0.0
        return 0.0

    def deposit_usdt0(self, amount: float, wait_after_approve_secs: int = 6):
        """Deposita USDT0 na Nado (mínimo $5 para criar subaccount).

        Args:
            amount: Quantidade de USDT0
            wait_after_approve_secs: Segundos para aguardar a tx de approve ser minerada
                antes do deposit (evita erro "nonce too low").
        """
        self.assert_trade_ready()
        raw_amount = to_pow_10(int(amount), 6)
        logger.info(f"💰 Depositando {amount} USDT0...")
        approve_tx = self.client.spot.approve_allowance(USDT0_SPOT, raw_amount)
        logger.info(f"   ✅ Allowance aprovado: {approve_tx}")
        logger.info(f"   ⏳ Aguardando {wait_after_approve_secs}s para tx ser minerada...")
        time.sleep(wait_after_approve_secs)
        deposit_tx = self.client.spot.deposit(
            DepositCollateralParams(
                subaccount_name=self.subaccount_name,
                product_id=USDT0_SPOT,
                amount=raw_amount,
            )
        )
        logger.info(f"   ✅ Depósito de {amount} USDT0 realizado! Tx: {deposit_tx}")

    def withdraw_usdt0(self, amount: float):
        """Saca USDT0 da Nado para a wallet."""
        self.assert_trade_ready()
        raw_amount = to_pow_10(int(amount), 6)
        logger.info(f"🏦 Sacando {amount} USDT0...")
        res = self.client.spot.withdraw(
            WithdrawCollateralParams(
                productId=USDT0_SPOT,
                amount=raw_amount,
                sender=self.subaccount_hex,
            )
        )
        logger.info(f"   ✅ Saque enviado! Resultado: {res}")

    def auto_deposit_if_needed(
        self,
        min_balance: float = 100.0,
        deposit_amount: float = 200.0,
    ) -> bool:
        """
        Deposita automaticamente se o saldo Nado estiver abaixo do mínimo.

        Exige USDT0 na wallet (L1). Retorna True se depositou.
        """
        balance = self.get_usdt0_balance()
        if balance >= min_balance:
            logger.info(f"   Saldo Nado: ${balance:,.2f} (mínimo ${min_balance:,.2f}) — OK")
            return False
        logger.info(
            f"   Saldo Nado: ${balance:,.2f} < ${min_balance:,.2f} — depositando ${deposit_amount:,.0f}"
        )
        try:
            self.deposit_usdt0(deposit_amount)
            return True
        except Exception as e:
            logger.error("   ❌ Falha no depósito automático: %s", e)
            return False

    def auto_withdraw_if_needed(
        self,
        min_balance: float = 50.0,
        withdraw_amount: float = None,
        leave_on_nado: float = 100.0,
    ) -> bool:
        """
        Saca automaticamente se o saldo Nado estiver acima do alvo.

        withdraw_amount: quanto sacar. Se None, saca (balance - leave_on_nado).
        leave_on_nado: saldo mínimo a manter na Nado.
        Retorna True se sacou.
        """
        balance = self.get_usdt0_balance()
        if balance < min_balance:
            logger.info(f"   Saldo Nado: ${balance:,.2f} (abaixo do mínimo ${min_balance:,.2f}) — nada a sacar")
            return False
        to_withdraw = withdraw_amount
        if to_withdraw is None:
            to_withdraw = max(0, balance - leave_on_nado)
        if to_withdraw <= 0:
            logger.info(f"   Saldo Nado: ${balance:,.2f} — mantendo (leave=${leave_on_nado:,.0f})")
            return False
        logger.info(f"   Saldo Nado: ${balance:,.2f} — sacando ${to_withdraw:,.0f} para wallet")
        try:
            self.withdraw_usdt0(to_withdraw)
            return True
        except Exception as e:
            logger.error("   ❌ Falha no saque automático: %s", e)
            return False

    # ═══════════════════════════════════════════════════════════
    #  ORDENS
    # ═══════════════════════════════════════════════════════════

    def _get_price_increment_x18(self, product_id: int) -> int:
        position = self.client.context.engine_client._get_subaccount_product_position(
            self.subaccount_hex, product_id
        )
        return int(position.product.book_info.price_increment_x18)

    def _get_size_increment_x18(self, product_id: int) -> int:
        """Retorna o size_increment do produto em x18 (ex.: 1e16 = 0.01). Fallback se SDK não expuser."""
        try:
            position = self.client.context.engine_client._get_subaccount_product_position(
                self.subaccount_hex, product_id
            )
            book = position.product.book_info
            # SDK expõe size_increment como string (valor raw x18), não size_increment_x18
            inc = getattr(book, "size_increment", None) or getattr(book, "size_increment_x18", None)
            if inc is not None:
                return int(inc)
        except Exception:
            pass
        # Fallback: Nado usa 0.01 para vários PERPs (ex.: produto 18 = OP). 1e16 em x18 = 0.01
        return 10**16

    def get_min_order_notional_usd(self, product_id: int) -> float:
        """Retorna o minimo de notional para ordens/trigger orders do produto."""
        try:
            position = self.client.context.engine_client._get_subaccount_product_position(
                self.subaccount_hex, product_id
            )
            raw_min_size = getattr(position.product.book_info, "min_size", None)
            if raw_min_size is not None:
                return float(from_x18(raw_min_size))
        except Exception:
            pass
        return 0.0

    def round_quantity_to_increment(self, product_id: int, quantity: float) -> float:
        """Arredonda quantity para o size_increment do produto (para uso em ordens e SL/TP)."""
        inc_x18 = self._get_size_increment_x18(product_id)
        inc = Decimal(inc_x18) / Decimal(10**18)
        qty = Decimal(str(quantity or 0.0))
        if qty <= 0 or inc <= 0:
            return 0.0
        rounded = (qty / inc).to_integral_value(rounding=ROUND_DOWN) * inc
        return float(rounded)

    @staticmethod
    def _isolated_margin_to_raw(isolated_margin_usd: float | None) -> int:
        """Converte margem isolada em USD para o raw de appendix da Nado.

        O campo `isolated_margin` do appendix ocupa 64 bits; usar x18 estoura a
        escala prática para posições pequenas. A Nado usa quote margin em x6.
        """
        amount = max(float(isolated_margin_usd or 0.0), 0.0)
        return int(round(amount * NADO_ISOLATED_MARGIN_SCALE))

    def _build_order(
        self,
        price: float,
        quantity: float,
        is_buy: bool,
        product_id: int,
        order_type: OrderType = OrderType.DEFAULT,
        expiration_secs: int = 86400,
        reduce_only: bool = False,
        margin_mode: str = "cross",
        isolated_margin_usd: float | None = None,
    ) -> OrderParams:
        size_increment_x18 = self._get_size_increment_x18(product_id)
        amount_raw = int(abs(quantity) * 1e18)
        # A Nado exige amount divisível por size_increment
        amount_raw = (amount_raw // size_increment_x18) * size_increment_x18
        if amount_raw <= 0:
            raise ValueError(
                f"Quantidade {quantity} abaixo do size_increment "
                f"({size_increment_x18 / 1e18}) para produto {product_id}"
            )
        if not is_buy:
            amount_raw = -amount_raw
        price_increment_x18 = self._get_price_increment_x18(product_id)
        price_x18 = round_x18(to_x18(price), price_increment_x18)
        isolated = str(margin_mode or "cross").strip().lower() == "isolated"
        isolated_margin = self._isolated_margin_to_raw(isolated_margin_usd) if isolated else None
        return OrderParams(
            sender=SubaccountParams(
                subaccount_owner=self.owner,
                subaccount_name=self.subaccount_name,
            ),
            priceX18=price_x18,
            amount=amount_raw,
            expiration=get_expiration_timestamp(expiration_secs),
            appendix=build_appendix(
                order_type=order_type,
                reduce_only=reduce_only,
                isolated=isolated,
                isolated_margin=isolated_margin,
            ),
            nonce=gen_order_nonce(),
        )

    def place_limit_order(
        self,
        product_id: int,
        price: float,
        quantity: float,
        is_buy: bool = True,
        post_only: bool = False,
    ):
        """Coloca uma ordem limitada."""
        self.assert_trade_ready()
        otype = OrderType.POST_ONLY if post_only else OrderType.DEFAULT
        side_str = "COMPRA 🟢" if is_buy else "VENDA 🔴"
        logger.info(f"📝 Limit {side_str}: {quantity} @ ${price:,.2f} (produto {product_id})")
        order = self._build_order(
            price, quantity, is_buy, product_id=product_id, order_type=otype
        )
        res = self.client.market.place_order(
            PlaceOrderParams(product_id=product_id, order=order)
        )
        logger.info(f"   ✅ Ordem colocada! Resultado: {res}")
        return res

    def place_market_order(
        self,
        product_id: int,
        quantity: float,
        is_buy: bool = True,
        slippage_bps: int = 50,
        reduce_only: bool = False,
        margin_mode: str = "cross",
        leverage: float | None = None,
    ):
        """Coloca uma ordem a mercado."""
        self.assert_trade_ready()
        market = self.client.context.engine_client.get_market_price(product_id)
        if is_buy:
            price = from_x18(market.ask_x18) * (1 + slippage_bps / 10000)
        else:
            price = from_x18(market.bid_x18) * (1 - slippage_bps / 10000)
        side_str = "COMPRA 🟢" if is_buy else "VENDA 🔴"
        logger.info(f"⚡ Market {side_str}: {quantity} @ ~${price:,.2f} (produto {product_id})")
        normalized_margin_mode = str(margin_mode or "cross").strip().lower()
        if normalized_margin_mode not in {"cross", "isolated"}:
            raise ValueError(f"margin mode Nado invalido: {margin_mode}")
        if normalized_margin_mode == "isolated":
            leverage_value = max(float(leverage or 1.0), 1.0)
            isolated_margin_usd = abs(float(quantity) * float(price)) / leverage_value
            logger.info("   Nado isolated solicitado | margem ~= $%.2f | lev=%.2fx", isolated_margin_usd, leverage_value)
            order = self._build_order(
                price,
                quantity,
                is_buy,
                product_id=product_id,
                order_type=OrderType.FOK,
                expiration_secs=1000,
                reduce_only=reduce_only,
                margin_mode=normalized_margin_mode,
                isolated_margin_usd=isolated_margin_usd,
            )
            res = self.client.market.place_order(
                PlaceOrderParams(product_id=product_id, order=order)
            )
            logger.info(f"   ✅ Ordem market enviada! Resultado: {res}")
            return res

        size_increment_x18 = self._get_size_increment_x18(product_id)
        amount_raw = int(abs(quantity) * 1e18)
        amount_raw = (amount_raw // size_increment_x18) * size_increment_x18
        if amount_raw <= 0:
            raise ValueError(
                f"Quantidade {quantity} abaixo do size_increment "
                f"({size_increment_x18 / 1e18}) para produto {product_id}"
            )
        if not is_buy:
            amount_raw = -amount_raw

        params = PlaceMarketOrderParams(
            product_id=product_id,
            market_order=MarketOrderParams(
                sender=SubaccountParams(
                    subaccount_owner=self.owner,
                    subaccount_name=self.subaccount_name,
                ),
                amount=amount_raw,
            ),
            slippage=slippage_bps / 10000,
            reduce_only=reduce_only,
        )
        res = self.client.market.place_market_order(params)
        logger.info(f"   ✅ Ordem market enviada! Resultado: {res}")
        return res

    def place_stop_loss(
        self,
        product_id: int,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float = 0.01,
    ):
        """Coloca Stop Loss (trigger por preço)."""
        self.assert_trade_ready()
        if self.client.context.trigger_client is None:
            logger.error("❌ Trigger client não configurado. Ordens TP/SL requerem trigger.")
            return None
        if is_long:
            trigger_type = "last_price_below"
            exec_price = trigger_price * (1 - slippage_pct)
            amount_x18 = str(-int(abs(quantity) * 1e18))
        else:
            trigger_type = "last_price_above"
            exec_price = trigger_price * (1 + slippage_pct)
            amount_x18 = str(int(abs(quantity) * 1e18))
        price_increment_x18 = self._get_price_increment_x18(product_id)
        price_x18 = str(round_x18(to_x18(exec_price), price_increment_x18))
        trigger_price_x18 = str(round_x18(to_x18(trigger_price), price_increment_x18))
        side = "LONG" if is_long else "SHORT"
        logger.info(
            f"🛑 Stop Loss ({side}): fechar {quantity} quando preço "
            f"{'<' if is_long else '>'} ${trigger_price:,.0f} (exec @ ~${exec_price:,.0f})"
        )
        res = self.client.market.place_price_trigger_order(
            product_id=product_id,
            price_x18=price_x18,
            amount_x18=amount_x18,
            trigger_price_x18=trigger_price_x18,
            trigger_type=trigger_type,
            subaccount_owner=self.owner,
            subaccount_name=self.subaccount_name,
            reduce_only=True,
        )
        # LACUNA CONHECIDA: ao contrario dos adapters CCXT (Kraken,
        # Hyperliquid, generico), a resposta do SDK da Nado nao e validada --
        # este log declara sucesso qualquer que seja o retorno. O formato de
        # resposta do SDK nao esta documentado em lugar nenhum deste modulo e
        # nao ha como verifica-lo sem uma conta Nado ativa, entao inventar um
        # validador aqui seria adivinhar. Ver `workspace/venues/order_validation.py`
        # para o padrao a seguir quando a forma da resposta for conhecida.
        logger.info(f"   ✅ Stop Loss enviada (resposta nao validada): {res}")
        return res

    def place_limit_order_with_tp_sl(
        self,
        product_id: int,
        price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        is_buy: bool = True,
        post_only: bool = False,
        slippage_pct: float = 0.01,
    ):
        """
        Coloca ordem limitada com SL e TP vinculados (bracket order).

        SL e TP só ativam quando a ordem limitada for preenchida.
        Útil para abrir posição já protegida em uma única operação.

        Args:
            product_id: ID do produto
            price: Preço da ordem limitada
            quantity: Quantidade
            stop_loss: Preço do Stop Loss (abaixo do preço para long, acima para short)
            take_profit: Preço do Take Profit (acima do preço para long, abaixo para short)
            is_buy: True = long, False = short
            post_only: Se True, ordem maker-only
            slippage_pct: Slippage nas ordens SL/TP (ex: 0.01 = 1%)
        """
        logger.info(
            f"📋 Limit + SL + TP: {quantity} @ ${price:,.0f} "
            f"| SL=${stop_loss:,.0f} TP=${take_profit:,.0f}"
        )
        res = self.place_limit_order(
            product_id=product_id,
            price=price,
            quantity=quantity,
            is_buy=is_buy,
            post_only=post_only,
        )
        digest = getattr(res.data, "digest", None) if res and res.data else None
        if not digest:
            logger.warning("   ⚠️ Digest não obtido. SL/TP não vinculados à ordem.")
            return res

        dependency = {"digest": digest, "on_partial_fill": False}
        self._place_stop_loss_internal(
            product_id, quantity, stop_loss, is_long=is_buy, slippage_pct=slippage_pct,
            dependency=dependency,
        )
        self._place_take_profit_internal(
            product_id, quantity, take_profit, is_long=is_buy, slippage_pct=slippage_pct,
            dependency=dependency,
        )
        logger.info("   ✅ SL e TP vinculados (ativam quando a ordem limitada preencher)")
        return res

    def place_market_order_with_tp_sl(
        self,
        product_id: int,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        is_buy: bool = True,
        slippage_bps: int = 50,
        slippage_pct: float = 0.01,
        verify_fill_wait_secs: float = 2.0,
    ):
        """
        Coloca ordem a mercado com SL e TP vinculados.

        SL e TP só são colocados se a ordem de entrada preencher. Ordem IOC
        pode não preencher por falta de liquidez — evita SL/TP órfãos.

        Args:
            product_id: ID do produto
            quantity: Quantidade
            stop_loss: Preço do Stop Loss
            take_profit: Preço do Take Profit
            is_buy: True = long, False = short
            slippage_bps: Slippage da ordem market (50 = 0.5%)
            slippage_pct: Slippage das ordens SL/TP (0.01 = 1%)
            verify_fill_wait_secs: Tempo para aguardar settlement antes de verificar fill
        """
        logger.info(
            f"⚡ Market + SL + TP: {quantity} @ mercado "
            f"| SL=${stop_loss:,.0f} TP=${take_profit:,.0f}"
        )
        position_before = self.get_perp_position_size(product_id)
        res = self.place_market_order(
            product_id=product_id,
            quantity=quantity,
            is_buy=is_buy,
            slippage_bps=slippage_bps,
        )
        digest = getattr(res.data, "digest", None) if res and res.data else None
        if not digest:
            logger.warning("   ⚠️ Digest não obtido. SL/TP não vinculados.")
            return res

        # Verifica se a ordem preencheu antes de colocar SL/TP
        time.sleep(verify_fill_wait_secs)
        position_after = self.get_perp_position_size(product_id)
        delta = position_after - position_before
        expected_delta = quantity if is_buy else -quantity
        tolerance = quantity * 0.001  # 0.1% de tolerância
        filled = abs(delta - expected_delta) <= tolerance

        if not filled:
            logger.warning(
                "   ⚠️ Ordem market não preencheu (pos antes=%.4f, depois=%.4f, esperado Δ=%.4f). "
                "SL/TP não colocados para evitar ordens órfãs. Tente aumentar slippage ou liquidez.",
                position_before, position_after, expected_delta,
            )
            return res

        dependency = {"digest": digest, "on_partial_fill": False}
        self._place_stop_loss_internal(
            product_id, quantity, stop_loss, is_long=is_buy, slippage_pct=slippage_pct,
            dependency=dependency,
        )
        self._place_take_profit_internal(
            product_id, quantity, take_profit, is_long=is_buy, slippage_pct=slippage_pct,
            dependency=dependency,
        )
        logger.info("   ✅ SL e TP vinculados (ordem market executada)")
        return res

    def _place_stop_loss_internal(
        self,
        product_id: int,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float = 0.01,
        dependency: dict = None,
    ):
        """Coloca SL (uso interno, com dependency opcional)."""
        self.assert_trade_ready()
        if self.client.context.trigger_client is None:
            logger.error("❌ Trigger client não configurado.")
            return None
        if is_long:
            trigger_type = "last_price_below"
            exec_price = trigger_price * (1 - slippage_pct)
            amount_x18 = str(-int(abs(quantity) * 1e18))
        else:
            trigger_type = "last_price_above"
            exec_price = trigger_price * (1 + slippage_pct)
            amount_x18 = str(int(abs(quantity) * 1e18))
        price_increment_x18 = self._get_price_increment_x18(product_id)
        price_x18 = str(round_x18(to_x18(exec_price), price_increment_x18))
        trigger_price_x18 = str(round_x18(to_x18(trigger_price), price_increment_x18))
        self.client.market.place_price_trigger_order(
            product_id=product_id,
            price_x18=price_x18,
            amount_x18=amount_x18,
            trigger_price_x18=trigger_price_x18,
            trigger_type=trigger_type,
            subaccount_owner=self.owner,
            subaccount_name=self.subaccount_name,
            reduce_only=True,
            dependency=dependency,
        )
        logger.info(f"   🛑 SL @ ${trigger_price:,.0f}")

    def _place_take_profit_internal(
        self,
        product_id: int,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float = 0.01,
        dependency: dict = None,
    ):
        """Coloca TP (uso interno, com dependency opcional)."""
        self.assert_trade_ready()
        if self.client.context.trigger_client is None:
            return None
        if is_long:
            trigger_type = "last_price_above"
            exec_price = trigger_price * (1 + slippage_pct)
            amount_x18 = str(-int(abs(quantity) * 1e18))
        else:
            trigger_type = "last_price_below"
            exec_price = trigger_price * (1 - slippage_pct)
            amount_x18 = str(int(abs(quantity) * 1e18))
        price_increment_x18 = self._get_price_increment_x18(product_id)
        price_x18 = str(round_x18(to_x18(exec_price), price_increment_x18))
        trigger_price_x18 = str(round_x18(to_x18(trigger_price), price_increment_x18))
        self.client.market.place_price_trigger_order(
            product_id=product_id,
            price_x18=price_x18,
            amount_x18=amount_x18,
            trigger_price_x18=trigger_price_x18,
            trigger_type=trigger_type,
            subaccount_owner=self.owner,
            subaccount_name=self.subaccount_name,
            reduce_only=True,
            dependency=dependency,
        )
        logger.info(f"   🎯 TP @ ${trigger_price:,.0f}")

    def place_take_profit(
        self,
        product_id: int,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        slippage_pct: float = 0.01,
    ):
        """Coloca Take Profit (trigger por preço)."""
        self.assert_trade_ready()
        if self.client.context.trigger_client is None:
            logger.error("❌ Trigger client não configurado. Ordens TP/SL requerem trigger.")
            return None
        if is_long:
            trigger_type = "last_price_above"
            exec_price = trigger_price * (1 + slippage_pct)
            amount_x18 = str(-int(abs(quantity) * 1e18))
        else:
            trigger_type = "last_price_below"
            exec_price = trigger_price * (1 - slippage_pct)
            amount_x18 = str(int(abs(quantity) * 1e18))
        price_increment_x18 = self._get_price_increment_x18(product_id)
        price_x18 = str(round_x18(to_x18(exec_price), price_increment_x18))
        trigger_price_x18 = str(round_x18(to_x18(trigger_price), price_increment_x18))
        side = "LONG" if is_long else "SHORT"
        logger.info(
            f"🎯 Take Profit ({side}): fechar {quantity} quando preço "
            f"{'>' if is_long else '<'} ${trigger_price:,.0f} (exec @ ~${exec_price:,.0f})"
        )
        res = self.client.market.place_price_trigger_order(
            product_id=product_id,
            price_x18=price_x18,
            amount_x18=amount_x18,
            trigger_price_x18=trigger_price_x18,
            trigger_type=trigger_type,
            subaccount_owner=self.owner,
            subaccount_name=self.subaccount_name,
            reduce_only=True,
        )
        logger.info(f"   ✅ Take Profit colocada! Resultado: {res}")
        return res

    def capabilities(self) -> dict[str, bool]:
        return {
            "native_sl": True,
            "native_tp": True,
            "edit_stop": False,
            "cancel_trigger": True,
            "reduce_only": True,
        }

    def replace_stop_loss(
        self,
        product_id: int,
        quantity: float,
        trigger_price: float,
        is_long: bool = True,
        previous_order_ref: dict | str | None = None,
        slippage_pct: float = 0.01,
        **_: object,
    ) -> dict:
        digest = previous_order_ref if isinstance(previous_order_ref, str) else None
        if isinstance(previous_order_ref, dict):
            digest = str(previous_order_ref.get("digest") or previous_order_ref.get("id") or "")
        if not digest:
            return {"cancelled": False, "order": None, "skipped_reason": "missing_previous_order_digest"}
        self.cancel_trigger_orders(product_id, [digest])
        try:
            order = self.place_stop_loss(
                product_id=product_id,
                quantity=quantity,
                trigger_price=trigger_price,
                is_long=is_long,
                slippage_pct=slippage_pct,
            )
        except Exception as exc:
            # Mesmo padrao dos outros adapters: o trigger antigo ja foi
            # cancelado, entao a falha aqui deixa a posicao sem stop.
            raise wrap_replace_failure(exc, symbol=product_id, cancelled_order_id=digest) from exc
        return {"cancelled": True, "order": order}

    def cancel_order(self, product_id: int, digest: str):
        """Cancela uma ordem pelo digest."""
        self.assert_trade_ready()
        logger.info(f"❌ Cancelando ordem {digest[:16]}...")
        res = self.client.market.cancel_orders(
            CancelOrdersParams(
                productIds=[product_id],
                digests=[digest],
                sender=self.subaccount_hex,
            )
        )
        logger.info(f"   ✅ Ordem cancelada! Resultado: {res}")
        return res

    def cancel_all_orders(self, product_id: int):
        """Cancela todas as ordens abertas de um produto."""
        self.assert_trade_ready()
        orders = self.get_open_orders(product_id)
        if not orders:
            logger.info("   Nenhuma ordem aberta para cancelar.")
            return
        digests = []
        for o in orders:
            d = getattr(o, "digest", None)
            if d is None and isinstance(o, dict):
                d = o.get("digest")
            if d:
                digests.append(d)
        if not digests:
            logger.info("   Nenhuma ordem com digest encontrada.")
            return
        logger.info(f"❌ Cancelando {len(digests)} ordens do produto {product_id}...")
        res = self.client.market.cancel_orders(
            CancelOrdersParams(
                productIds=[product_id] * len(digests),
                digests=digests,
                sender=self.subaccount_hex,
            )
        )
        logger.info(f"   ✅ {len(digests)} ordens canceladas!")
        return res

    # ═══════════════════════════════════════════════════════════
    #  CONSULTAS DE CONTA
    # ═══════════════════════════════════════════════════════════

    def get_subaccount_info(self):
        """Retorna informações da subconta (saldos, saúde, posições)."""
        info = self.client.context.engine_client.get_subaccount_info(self.subaccount_hex)
        logger.info("═══ INFO DA SUBCONTA ═══")
        health_labels = ["initial", "maintenance"]
        for i, h in enumerate(info.healths):
            label = health_labels[i] if i < len(health_labels) else f"#{i}"
            try:
                assets = float(h.assets) / 1e18 if hasattr(h, "assets") else 0
                liabs = float(h.liabilities) / 1e18 if hasattr(h, "liabilities") else 0
                health_val = float(h.health) / 1e18 if hasattr(h, "health") else 0
                if assets > 0 or liabs > 0 or health_val > 0:
                    logger.info(f"   Health ({label}): assets=${assets:,.2f} liabs=${liabs:,.2f} health=${health_val:,.2f}")
            except Exception:
                logger.info(f"   Health ({label}): {h}")
        for balance in info.spot_balances:
            try:
                bal = getattr(balance, "balance", balance)
                amount = 0
                for attr in ["amount", "amount_x18", "balance_amount"]:
                    val = getattr(bal, attr, None)
                    if val is not None and str(val) != "0":
                        amount = float(val) / 1e18
                        break
                pid = getattr(balance, "product_id", "?")
                if abs(amount) > 0.001:
                    logger.info(f"   Spot ID {pid}: {amount:,.6f}")
            except Exception:
                pass
        for position in info.perp_balances:
            try:
                bal = getattr(position, "balance", position)
                amount = 0
                for attr in ["amount", "amount_x18"]:
                    val = getattr(bal, attr, None)
                    if val is not None and str(val) != "0":
                        amount = float(val) / 1e18
                        break
                pid = getattr(position, "product_id", "?")
                if abs(amount) > 0.001:
                    logger.info(f"   Perp ID {pid}: Size={amount:,.6f}")
            except Exception:
                pass
        return info

    def get_open_orders(self, product_id: int):
        """Lista ordens abertas de um produto."""
        result = self.client.market.get_subaccount_open_orders(
            product_id, self.subaccount_hex
        )
        logger.info(f"📋 Ordens abertas (produto {product_id}):")
        orders_list = result
        if hasattr(result, "orders"):
            orders_list = result.orders
        elif hasattr(result, "data"):
            orders_list = result.data
        if not orders_list:
            logger.info("   (nenhuma)")
            return orders_list or []
        for o in orders_list:
            try:
                price = from_x18(getattr(o, "price", 0))
                qty = from_x18(getattr(o, "amount", 0))
                digest = getattr(o, "digest", "?")
                side = "BUY" if qty > 0 else "SELL"
                logger.info(f"   [{side}] {abs(qty):.6f} @ ${price:,.2f} (digest: {str(digest)[:12]}...)")
            except Exception:
                logger.info(f"   Ordem: {o}")
        return orders_list

    def get_order_digest(self, order: OrderParams, product_id: int) -> str:
        """Calcula o digest de uma ordem (necessário para cancelamento)."""
        order.sender = subaccount_to_bytes32(order.sender)
        return self.client.context.engine_client.get_order_digest(order, product_id)

    # ═══════════════════════════════════════════════════════════
    #  ESTRATÉGIAS SIMPLES
    # ═══════════════════════════════════════════════════════════

    def get_trigger_orders(
        self,
        product_ids: list[int] | None = None,
        *,
        status_types: list[TriggerOrderStatusType] | None = None,
        reduce_only: bool | None = True,
        limit: int = 100,
    ):
        """Lista ordens trigger da Nado, incluindo SL/TP por preço."""
        if self.client.context.trigger_client is None:
            logger.warning("Trigger client nao configurado; nao foi possivel consultar SL/TP.")
            return []
        params = ListTriggerOrdersParams(
            tx=ListTriggerOrdersTx(
                sender=self.subaccount_hex,
                nonce=None,
                recvTime=int(time.time() * 1000) + 60_000,
            ),
            product_ids=product_ids,
            trigger_types=[TriggerType.PRICE_TRIGGER],
            status_types=status_types
            or [
                TriggerOrderStatusType.WAITING_PRICE,
                TriggerOrderStatusType.WAITING_DEPENDENCY,
                TriggerOrderStatusType.TRIGGERING,
            ],
            reduce_only=reduce_only,
            limit=limit,
        )
        result = self.client.market.get_trigger_orders(params)
        data = getattr(result, "data", None)
        return list(getattr(data, "orders", []) or [])

    def cancel_trigger_orders(self, product_id: int, digests: list[str]):
        """Cancela trigger orders especificas de SL/TP."""
        self.assert_trade_ready()
        clean_digests = [digest for digest in digests if digest]
        if not clean_digests:
            return None
        logger.info("Cancelando %d trigger orders da Nado no produto %s...", len(clean_digests), product_id)
        res = self.client.market.cancel_trigger_orders(
            CancelOrdersParams(
                productIds=[product_id] * len(clean_digests),
                digests=clean_digests,
                sender=self.subaccount_hex,
            )
        )
        logger.info("   trigger orders canceladas: %s", res)
        return res

    def grid_trading(
        self,
        product_id: int,
        lower_price: float,
        upper_price: float,
        num_grids: int = 6,
        total_quantity: float = 0.01,
    ):
        """Grid Trading: ordens de compra abaixo e venda acima do mid price."""
        market = self.get_market_price(product_id)
        mid = market["mid_price"]
        price_step = (upper_price - lower_price) / (num_grids - 1)
        qty_per_grid = total_quantity / (num_grids // 2)
        logger.info("🔲 Iniciando Grid Trading:")
        logger.info(f"   Range: ${lower_price:,.2f} - ${upper_price:,.2f}")
        logger.info(f"   Mid: ${mid:,.2f} | Grids: {num_grids} | Qty/grid: {qty_per_grid:.6f}")
        results = []
        for i in range(num_grids):
            price = lower_price + (i * price_step)
            is_buy = price < mid
            res = self.place_limit_order(product_id, price, qty_per_grid, is_buy=is_buy)
            results.append(res)
            time.sleep(0.15)
        logger.info(f"   ✅ Grid com {len(results)} ordens colocadas!")
        return results

    def spread_orders(
        self,
        product_id: int,
        spread_bps: int = 10,
        quantity: float = 0.01,
    ):
        """Coloca ordens de compra e venda com spread ao redor do mid price."""
        market = self.get_market_price(product_id)
        mid = market["mid_price"]
        buy_price = mid * (1 - spread_bps / 10000)
        sell_price = mid * (1 + spread_bps / 10000)
        logger.info(f"📐 Spread Orders ({spread_bps} bps):")
        logger.info(f"   Buy @ ${buy_price:,.2f}  |  Sell @ ${sell_price:,.2f}")
        buy_res = self.place_limit_order(product_id, buy_price, quantity, is_buy=True)
        sell_res = self.place_limit_order(product_id, sell_price, quantity, is_buy=False)
        return {"buy": buy_res, "sell": sell_res}

    def inspect_sdk(self):
        """Inspeciona o SDK para debug (mostra métodos disponíveis)."""
        import inspect
        logger.info("═══ INSPEÇÃO DO SDK ═══")
        for api_name, api in [("market", self.client.market), ("spot", self.client.spot)]:
            logger.info(f"\n--- client.{api_name} ---")
            for name, method in inspect.getmembers(api, predicate=inspect.ismethod):
                if not name.startswith("_"):
                    logger.info(f"  {name}{inspect.signature(method)}")
