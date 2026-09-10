"""
Orquestrador delta-neutro Nado × Kraken para farming de airdrops.

Ideia:
  - Abrir par simétrico: se Nado fica LONG X USD em BTC-PERP,
    Kraken fica SHORT X USD em BTC-PERP (ou vice-versa).
  - Delta líquido ≈ 0 → sem risco direcional.
  - Volume roda em ambas as exchanges → elegível aos airdrops das duas.
  - Custo: funding diff + taxas (entrada + saída) + spread.

Regras de segurança:
  - Tamanho por leg limitado por VOLUME_ORDER.
  - Só abre par se ambas as pernas preenchem (rollback da 1ª se a 2ª falhar).
  - Monitora drift → rebalance automático quando delta > DRIFT_BPS.
  - Stop global: se PnL total < -MAX_PAIR_LOSS_PCT do notional, desmonta.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Dict, List, Optional

from ..kraken.kraken_integration import KrakenTrader

if TYPE_CHECKING:  # o SDK da Nado e opcional; aqui o tipo so serve para anotacao
    from ..nado.nado_integration import NadoTrader
from .scenarios import (
    DRIFT_HIGH,
    EXISTING_POSITION_RISK,
    KRAKEN_POSITION_PARSE_ERROR,
    KRAKEN_SELF_FILL_RISK,
    NADO_REJECTED,
    PARTIAL_UNWIND_RISK,
    ROLLBACK_EXECUTED,
    STOP_GLOBAL_TRIGGERED,
    scenario_message,
)

MAX_REASONABLE_MARKET_PRICE_USD = 10_000_000.0

logger = logging.getLogger(__name__)


@dataclass
class PairState:
    symbol: str                 # 'BTC/USDT'
    nado_product_id: int
    kraken_symbol: str
    nado_side: str              # 'long' | 'short'
    kraken_side: str            # 'long' | 'short' (oposto ao nado)
    requested_notional_usd: float
    effective_notional_usd: float
    nado_qty: float
    kraken_qty: float
    nado_entry: float
    kraken_entry: float
    requested_margin_usd: float = 0.0
    sizing_source: str = "notional"
    nado_network: str = ""
    nado_subaccount_name: str = ""
    nado_subaccount_hex: str = ""
    nado_owner_address: str = ""
    nado_linked_signer_address: str = ""
    kraken_account: str = ""
    kraken_account_symbol: str = ""
    kraken_api_fingerprint: str = ""
    kraken_subaccount_mode: str = ""
    kraken_requested_leverage: float = 0.0
    kraken_margin_mode: str = ""
    execution_mode: str = "hedged"
    effective_venue: str = "hedged"
    nado_requested_leverage: float = 0.0
    nado_margin_mode: str = ""
    nado_liquidation_price: float = 0.0
    kraken_liquidation_price: float = 0.0
    liquidation_buffer_pct: float = 0.0
    kraken_sandbox: Optional[bool] = None
    pair_stop_loss_pct: float = 0.0
    pair_take_profit_pct: float = 0.0
    nado_stop_price: float = 0.0
    kraken_stop_price: float = 0.0
    nado_take_profit_price: float = 0.0
    kraken_take_profit_price: float = 0.0
    nado_close_side: str = ""
    kraken_close_side: str = ""
    opened_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "nado_product_id": self.nado_product_id,
            "kraken_symbol": self.kraken_symbol,
            "nado_side": self.nado_side,
            "kraken_side": self.kraken_side,
            "requested_notional_usd": self.requested_notional_usd,
            "effective_notional_usd": self.effective_notional_usd,
            "nado_qty": self.nado_qty,
            "kraken_qty": self.kraken_qty,
            "nado_entry": self.nado_entry,
            "kraken_entry": self.kraken_entry,
            "requested_margin_usd": self.requested_margin_usd,
            "sizing_source": self.sizing_source,
            "nado_network": self.nado_network,
            "nado_subaccount_name": self.nado_subaccount_name,
            "nado_subaccount_hex": self.nado_subaccount_hex,
            "nado_owner_address": self.nado_owner_address,
            "nado_linked_signer_address": self.nado_linked_signer_address,
            "kraken_account": self.kraken_account,
            "kraken_account_symbol": self.kraken_account_symbol,
            "kraken_api_fingerprint": self.kraken_api_fingerprint,
            "kraken_subaccount_mode": self.kraken_subaccount_mode,
            "kraken_requested_leverage": self.kraken_requested_leverage,
            "kraken_margin_mode": self.kraken_margin_mode,
            "execution_mode": self.execution_mode,
            "effective_venue": self.effective_venue,
            "nado_requested_leverage": self.nado_requested_leverage,
            "nado_margin_mode": self.nado_margin_mode,
            "nado_liquidation_price": self.nado_liquidation_price,
            "kraken_liquidation_price": self.kraken_liquidation_price,
            "liquidation_buffer_pct": self.liquidation_buffer_pct,
            "kraken_sandbox": self.kraken_sandbox,
            "pair_stop_loss_pct": self.pair_stop_loss_pct,
            "pair_take_profit_pct": self.pair_take_profit_pct,
            "nado_stop_price": self.nado_stop_price,
            "kraken_stop_price": self.kraken_stop_price,
            "nado_take_profit_price": self.nado_take_profit_price,
            "kraken_take_profit_price": self.kraken_take_profit_price,
            "nado_close_side": self.nado_close_side,
            "kraken_close_side": self.kraken_close_side,
            "opened_at": self.opened_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PairState":
        payload = dict(data)
        legacy_notional = float(payload.pop("notional_usd", 0.0) or 0.0)
        payload.setdefault("requested_notional_usd", legacy_notional)
        payload.setdefault("effective_notional_usd", legacy_notional)
        payload.setdefault("requested_margin_usd", 0.0)
        payload.setdefault("sizing_source", "notional")
        payload.setdefault("nado_network", "")
        payload.setdefault("nado_subaccount_name", "")
        payload.setdefault("nado_subaccount_hex", "")
        payload.setdefault("nado_owner_address", "")
        payload.setdefault("nado_linked_signer_address", "")
        payload.setdefault("kraken_account", "")
        payload.setdefault("kraken_account_symbol", "")
        payload.setdefault("kraken_api_fingerprint", "")
        payload.setdefault("kraken_subaccount_mode", "")
        payload.setdefault("kraken_requested_leverage", 0.0)
        payload.setdefault("kraken_margin_mode", "")
        payload.setdefault("execution_mode", "hedged")
        payload.setdefault("effective_venue", "hedged")
        payload.setdefault("nado_requested_leverage", 0.0)
        payload.setdefault("nado_margin_mode", "")
        payload.setdefault("nado_liquidation_price", 0.0)
        payload.setdefault("kraken_liquidation_price", 0.0)
        payload.setdefault("liquidation_buffer_pct", 0.0)
        payload.setdefault("kraken_sandbox", None)
        payload.setdefault("pair_stop_loss_pct", 0.0)
        payload.setdefault("pair_take_profit_pct", 0.0)
        payload.setdefault("nado_stop_price", 0.0)
        payload.setdefault("kraken_stop_price", 0.0)
        payload.setdefault("nado_take_profit_price", 0.0)
        payload.setdefault("kraken_take_profit_price", 0.0)
        payload.setdefault("nado_close_side", "")
        payload.setdefault("kraken_close_side", "")
        return cls(**payload)

    @property
    def notional_usd(self) -> float:
        return self.effective_notional_usd


@dataclass
class PairSizingPlan:
    symbol: str
    nado_product_id: int
    kraken_symbol: str
    requested_notional_usd: float
    nado_mid: float
    kraken_mid: float
    nado_min_qty: float
    kraken_min_qty: float
    common_min_qty: float
    nado_min_notional_usd: float
    kraken_min_notional_usd: float
    common_min_notional_usd: float
    nado_target_qty: float
    kraken_target_qty: float
    common_qty: float
    nado_qty: float
    kraken_qty: float
    nado_effective_notional_usd: float
    kraken_effective_notional_usd: float
    effective_notional_usd: float
    can_execute: bool
    blocked_reason: str = ""


class DeltaNeutralEngine:
    def __init__(
        self,
        nado: "NadoTrader",
        kraken: KrakenTrader,
        *,
        volume_per_leg_usd: float = 100.0,
        drift_bps: int = 50,           # rebalancear se delta > 0.5% do notional
        max_pair_loss_pct: float = 0.03,  # 3% do notional total → desmonta
        slippage_bps: int = 100,
    ):
        self.nado = nado
        self.kraken = kraken
        self.volume_per_leg = float(volume_per_leg_usd)
        self.drift_bps = int(drift_bps)
        self.max_pair_loss_pct = float(max_pair_loss_pct)
        self.slippage_bps = int(slippage_bps)

        self._nado_symbol_map = self.nado.get_symbol_to_product_map()
        self._kraken_symbol_map = self.kraken.get_symbol_to_product_map(
            product_filter=list(self._nado_symbol_map.keys())
        )

    def _get_protective_stop_loss_pct(self) -> float:
        raw = float(getattr(self, "protective_stop_loss_pct", 0.0) or 0.0)
        return max(raw, 0.0)

    def _get_protective_take_profit_pct(self) -> float:
        raw = float(getattr(self, "protective_take_profit_pct", 0.0) or 0.0)
        return max(raw, 0.0)

    def protective_stop_price(self, entry_price: float, side: str) -> float:
        pct = self._get_protective_stop_loss_pct()
        if pct <= 0 or entry_price <= 0:
            return 0.0
        if side == "long":
            return entry_price * (1 - pct)
        return entry_price * (1 + pct)

    def protective_take_profit_price(self, entry_price: float, side: str) -> float:
        pct = self._get_protective_take_profit_pct()
        if pct <= 0 or entry_price <= 0:
            return 0.0
        if side == "long":
            return entry_price * (1 + pct)
        return entry_price * (1 - pct)

    @staticmethod
    def protective_close_side(side: str) -> str:
        return "sell" if side == "long" else "buy"

    def build_pair_protection_plan(
        self,
        *,
        nado_side: str,
        kraken_side: str,
        nado_entry: float,
        kraken_entry: float,
    ) -> dict:
        return {
            "pair_stop_loss_pct": self._get_protective_stop_loss_pct(),
            "pair_take_profit_pct": self._get_protective_take_profit_pct(),
            "nado_stop_price": self.protective_stop_price(nado_entry, nado_side),
            "kraken_stop_price": self.protective_stop_price(kraken_entry, kraken_side),
            "nado_take_profit_price": self.protective_take_profit_price(nado_entry, nado_side),
            "kraken_take_profit_price": self.protective_take_profit_price(kraken_entry, kraken_side),
            "nado_close_side": self.protective_close_side(nado_side),
            "kraken_close_side": self.protective_close_side(kraken_side),
        }

    def _attach_pair_protective_orders(
        self,
        *,
        symbol: str,
        pid: int,
        kraken_symbol: str,
        nado_side: str,
        kraken_side: str,
        nado_qty: float,
        kraken_qty: float,
        protection_plan: dict,
    ) -> None:
        stop_pct = float(protection_plan.get("pair_stop_loss_pct") or 0.0)
        take_profit_pct = float(protection_plan.get("pair_take_profit_pct") or 0.0)
        if stop_pct <= 0 and take_profit_pct <= 0:
            return

        trigger_slippage_pct = float(
            getattr(self, "protective_stop_trigger_slippage_pct", 0.01) or 0.01
        )
        nado_stop = float(protection_plan.get("nado_stop_price") or 0.0)
        kraken_stop = float(protection_plan.get("kraken_stop_price") or 0.0)
        nado_take_profit = float(protection_plan.get("nado_take_profit_price") or 0.0)
        kraken_take_profit = float(protection_plan.get("kraken_take_profit_price") or 0.0)

        if stop_pct > 0 and nado_stop > 0:
            try:
                self.nado.place_stop_loss(
                    product_id=pid,
                    quantity=nado_qty,
                    trigger_price=nado_stop,
                    is_long=nado_side == "long",
                    slippage_pct=trigger_slippage_pct,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ falha ao anexar stop loss da Nado em %s: %s", symbol, exc)

        if stop_pct > 0 and kraken_stop > 0:
            try:
                self.kraken.place_stop_loss(
                    symbol=kraken_symbol,
                    quantity=kraken_qty,
                    trigger_price=kraken_stop,
                    is_long=kraken_side == "long",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ falha ao anexar stop loss da Kraken em %s: %s", symbol, exc)

        if take_profit_pct > 0 and nado_take_profit > 0:
            try:
                self.nado.place_take_profit(
                    product_id=pid,
                    quantity=nado_qty,
                    trigger_price=nado_take_profit,
                    is_long=nado_side == "long",
                    slippage_pct=trigger_slippage_pct,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ falha ao anexar take profit da Nado em %s: %s", symbol, exc)

        if take_profit_pct > 0 and kraken_take_profit > 0:
            try:
                self.kraken.place_take_profit(
                    symbol=kraken_symbol,
                    quantity=kraken_qty,
                    trigger_price=kraken_take_profit,
                    is_long=kraken_side == "long",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ falha ao anexar take profit da Kraken em %s: %s", symbol, exc)

    def _assert_nado_trade_ready(self) -> None:
        assert_trade_ready = getattr(self.nado, "assert_trade_ready", None)
        if callable(assert_trade_ready):
            assert_trade_ready()

    def _validate_saved_state_context(
        self,
        state: PairState,
        *,
        allow_legacy: bool,
    ) -> None:
        has_identity = bool(
            state.nado_subaccount_name
            or state.nado_subaccount_hex
            or state.kraken_api_fingerprint
        )
        if not has_identity:
            message = (
                "state legado sem identidade de subconta. "
                "A migracao recomenda zerar o ambiente antigo antes do modo estrito."
            )
            if allow_legacy:
                logger.warning("⚠️ %s", message)
                return
            raise RuntimeError(message)

        nado_context = getattr(self.nado, "get_isolation_context", lambda: {})()
        kraken_context = getattr(self.kraken, "get_isolation_context", lambda: {})()
        mismatches: List[str] = []

        expected_nado_subaccount = str(nado_context.get("subaccount_name") or "")
        expected_nado_network = str(nado_context.get("network") or "")
        if state.nado_network and state.nado_network != expected_nado_network:
            mismatches.append(f"Nado network={state.nado_network} atual={expected_nado_network}")
        if state.nado_subaccount_name and state.nado_subaccount_name != expected_nado_subaccount:
            mismatches.append(
                f"Nado subaccount={state.nado_subaccount_name} atual={expected_nado_subaccount}"
            )
        expected_nado_hex = str(nado_context.get("subaccount_hex") or "")
        if state.nado_subaccount_hex and state.nado_subaccount_hex != expected_nado_hex:
            mismatches.append("Nado subaccount_hex nao bate com o estado salvo")
        expected_nado_owner = str(nado_context.get("owner_address") or "")
        if state.nado_owner_address and state.nado_owner_address != expected_nado_owner:
            mismatches.append("Nado owner_address nao bate com o estado salvo")
        expected_linked = str(nado_context.get("linked_signer_address") or "")
        if state.nado_linked_signer_address and state.nado_linked_signer_address != expected_linked:
            mismatches.append("Nado linked signer nao bate com o estado salvo")
        expected_account = str(kraken_context.get("account") or "")
        if state.kraken_account and state.kraken_account != expected_account:
            mismatches.append(f"Kraken account={state.kraken_account} atual={expected_account}")
        expected_symbol = str(kraken_context.get("account_symbol") or "")
        if state.kraken_account_symbol and state.kraken_account_symbol != expected_symbol:
            mismatches.append("Kraken account_symbol nao bate com o estado salvo")
        expected_fingerprint = str(kraken_context.get("api_fingerprint") or "")
        if state.kraken_api_fingerprint and state.kraken_api_fingerprint != expected_fingerprint:
            mismatches.append("Kraken API fingerprint nao bate com o estado salvo")
        expected_mode = str(kraken_context.get("subaccount_mode") or "")
        if state.kraken_subaccount_mode and state.kraken_subaccount_mode != expected_mode:
            mismatches.append("Kraken subaccount_mode nao bate com o estado salvo")
        expected_sandbox = kraken_context.get("sandbox")
        if state.kraken_sandbox is not None and expected_sandbox is not None and state.kraken_sandbox != expected_sandbox:
            mismatches.append("Kraken sandbox nao bate com o estado salvo")
        if mismatches:
            raise RuntimeError(
                "Contexto salvo nao confere com o ambiente atual: " + "; ".join(mismatches)
            )

    # ═══════════════════════════════════════════════════════════
    #  SÍMBOLOS COMPARTILHADOS
    # ═══════════════════════════════════════════════════════════
    def common_symbols(self) -> List[str]:
        """Símbolos listados em AMBAS as exchanges (único que dá pra hedgear)."""
        return sorted(set(self._nado_symbol_map) & set(self._kraken_symbol_map))

    @staticmethod
    def _fractional_step(value: float) -> Fraction:
        return Fraction(str(round(float(value), 12))).limit_denominator(10**12)

    @classmethod
    def _least_common_quantity_step(cls, left_step: float, right_step: float) -> float:
        left = float(left_step or 0.0)
        right = float(right_step or 0.0)
        if left <= 0:
            return max(right, 0.0)
        if right <= 0:
            return max(left, 0.0)

        left_fraction = cls._fractional_step(left)
        right_fraction = cls._fractional_step(right)
        common_denominator = math.lcm(left_fraction.denominator, right_fraction.denominator)
        left_units = left_fraction.numerator * (common_denominator // left_fraction.denominator)
        right_units = right_fraction.numerator * (common_denominator // right_fraction.denominator)
        common_units = math.lcm(left_units, right_units)
        return float(Fraction(common_units, common_denominator))

    @staticmethod
    def _round_down_to_step(quantity: float, step: float) -> float:
        qty = float(quantity or 0.0)
        step_value = float(step or 0.0)
        if qty <= 0:
            return 0.0
        if step_value <= 0:
            return qty
        units = int(qty / step_value)
        return round(units * step_value, 12)

    @staticmethod
    def _is_valid_market_price(price: float) -> bool:
        value = float(price or 0.0)
        return math.isfinite(value) and 0.0 < value <= MAX_REASONABLE_MARKET_PRICE_USD

    def _infer_nado_min_quantity(self, product_id: int) -> float:
        get_increment = getattr(self.nado, "_get_size_increment_x18", None)
        if callable(get_increment):
            try:
                increment = int(get_increment(product_id))
            except Exception:  # noqa: BLE001
                return 0.0
            if increment > 0:
                return increment / 1e18
        return 0.0

    def _infer_kraken_min_quantity(self, symbol: str) -> float:
        market_getter = getattr(getattr(self.kraken, "client", None), "market", None)
        if callable(market_getter):
            market = market_getter(symbol)
            precision = (market.get("precision") or {}).get("amount")
            min_amount = ((market.get("limits") or {}).get("amount") or {}).get("min")
            candidates: list[float] = []
            if isinstance(precision, int):
                candidates.append(10 ** (-precision))
            elif precision is not None:
                try:
                    candidates.append(float(precision))
                except (TypeError, ValueError):
                    pass
            if min_amount is not None:
                try:
                    candidates.append(float(min_amount))
                except (TypeError, ValueError):
                    pass
            positives = [candidate for candidate in candidates if candidate > 0]
            if positives:
                return max(positives)
        return 0.0

    def build_pair_sizing_plan(
        self,
        symbol: str,
        notional_usd: Optional[float] = None,
    ) -> PairSizingPlan:
        requested_notional = float(notional_usd or self.volume_per_leg)
        pid = self._nado_symbol_map[symbol]
        kraken_symbol = self._kraken_symbol_map[symbol]
        nado_mid = float(self.nado.get_market_mid_price(pid) or 0.0)
        kraken_mid = float(self.kraken.get_market_mid_price(kraken_symbol) or 0.0)

        if not self._is_valid_market_price(nado_mid) or not self._is_valid_market_price(kraken_mid):
            return PairSizingPlan(
                symbol=symbol,
                nado_product_id=pid,
                kraken_symbol=kraken_symbol,
                requested_notional_usd=requested_notional,
                nado_mid=nado_mid,
                kraken_mid=kraken_mid,
                nado_min_qty=0.0,
                kraken_min_qty=0.0,
                common_min_qty=0.0,
                nado_min_notional_usd=0.0,
                kraken_min_notional_usd=0.0,
                common_min_notional_usd=0.0,
                nado_target_qty=0.0,
                kraken_target_qty=0.0,
                common_qty=0.0,
                nado_qty=0.0,
                kraken_qty=0.0,
                nado_effective_notional_usd=0.0,
                kraken_effective_notional_usd=0.0,
                effective_notional_usd=0.0,
                can_execute=False,
                blocked_reason=f"precos invalidos (nado={nado_mid:.4f} kraken={kraken_mid:.4f})",
            )

        nado_min_qty = self._infer_nado_min_quantity(pid)
        kraken_min_qty = self._infer_kraken_min_quantity(kraken_symbol)
        common_min_qty = self._least_common_quantity_step(nado_min_qty, kraken_min_qty)
        nado_min_notional = nado_min_qty * nado_mid if nado_min_qty > 0 else 0.0
        kraken_min_notional = kraken_min_qty * kraken_mid if kraken_min_qty > 0 else 0.0
        common_min_notional = (
            max(common_min_qty * nado_mid, common_min_qty * kraken_mid)
            if common_min_qty > 0
            else max(nado_min_notional, kraken_min_notional)
        )

        nado_target_qty = float(self.nado.round_quantity_to_increment(pid, requested_notional / nado_mid))
        kraken_target_qty = float(
            self.kraken.round_quantity_to_increment(kraken_symbol, requested_notional / kraken_mid)
        )
        max_common_qty = min(nado_target_qty, kraken_target_qty)
        planned_common_qty = (
            self._round_down_to_step(max_common_qty, common_min_qty)
            if common_min_qty > 0
            else max_common_qty
        )
        nado_qty = float(self.nado.round_quantity_to_increment(pid, planned_common_qty))
        kraken_qty = float(self.kraken.round_quantity_to_increment(kraken_symbol, planned_common_qty))
        actual_nado_notional = nado_qty * nado_mid
        actual_kraken_notional = kraken_qty * kraken_mid
        actual_notional = (actual_nado_notional + actual_kraken_notional) / 2 if nado_qty > 0 and kraken_qty > 0 else 0.0

        blocked_reason = ""
        if nado_qty <= 0 or kraken_qty <= 0:
            blocked_reason = (
                "nocional abaixo do minimo executavel | "
                f"Nado ~${nado_min_notional:.2f} | "
                f"Kraken ~${kraken_min_notional:.2f} | "
                f"comum ~${common_min_notional:.2f}"
            )

        return PairSizingPlan(
            symbol=symbol,
            nado_product_id=pid,
            kraken_symbol=kraken_symbol,
            requested_notional_usd=requested_notional,
            nado_mid=nado_mid,
            kraken_mid=kraken_mid,
            nado_min_qty=nado_min_qty,
            kraken_min_qty=kraken_min_qty,
            common_min_qty=common_min_qty,
            nado_min_notional_usd=nado_min_notional,
            kraken_min_notional_usd=kraken_min_notional,
            common_min_notional_usd=common_min_notional,
            nado_target_qty=nado_target_qty,
            kraken_target_qty=kraken_target_qty,
            common_qty=planned_common_qty,
            nado_qty=nado_qty,
            kraken_qty=kraken_qty,
            nado_effective_notional_usd=actual_nado_notional,
            kraken_effective_notional_usd=actual_kraken_notional,
            effective_notional_usd=actual_notional,
            can_execute=nado_qty > 0 and kraken_qty > 0,
            blocked_reason=blocked_reason,
        )

    # ═══════════════════════════════════════════════════════════
    #  ABERTURA
    # ═══════════════════════════════════════════════════════════
    def open_pair(
        self,
        symbol: str,
        nado_side: str = "long",
        notional_usd: Optional[float] = None,
        *,
        attach_default_protective_orders: bool = True,
        kraken_leverage: Optional[float] = None,
        kraken_margin_mode: Optional[str] = None,
        nado_leverage: Optional[float] = None,
        nado_margin_mode: Optional[str] = None,
    ) -> Optional[PairState]:
        """
        Abre perna na Nado (nado_side) e perna oposta na Kraken.

        Rollback: se a 2ª perna falhar, a 1ª é fechada automaticamente.
        """
        self._assert_nado_trade_ready()
        notional = float(notional_usd or self.volume_per_leg)
        validate_subaccount_rule = getattr(self.kraken, "validate_entry_subaccount_rule", None)
        if callable(validate_subaccount_rule):
            validate_subaccount_rule(
                require_subaccount=getattr(self, "kraken_require_subaccount", False),
                declared_is_subaccount=getattr(self, "kraken_api_is_subaccount", False),
            )
        if symbol not in self._nado_symbol_map:
            logger.error("❌ %s não está listado na Nado", symbol)
            return None
        if symbol not in self._kraken_symbol_map:
            logger.error("❌ %s não está listado na Kraken (venue=%s)",
                         symbol, self.kraken.venue)
            return None

        pid = self._nado_symbol_map[symbol]
        kraken_symbol = self._kraken_symbol_map[symbol]
        nado_is_buy = nado_side == "long"
        kraken_is_buy = not nado_is_buy
        kraken_side = "short" if nado_is_buy else "long"
        requested_kraken_leverage = float(kraken_leverage or 0.0)
        requested_kraken_margin_mode = str(kraken_margin_mode or "").strip().lower()
        requested_nado_leverage = float(nado_leverage or 0.0)
        requested_nado_margin_mode = str(nado_margin_mode or "").strip().lower()

        existing_nado_pos = self.nado.get_perp_position_size(pid)
        if abs(existing_nado_pos) > 1e-9:
            logger.error(
                "❌ %s",
                scenario_message(
                    EXISTING_POSITION_RISK,
                    f"Nado ja tem posicao aberta em {symbol}: {existing_nado_pos:+.6f}",
                ),
            )
            return None
        existing_kraken_pos = self.kraken.get_position(kraken_symbol)
        if abs(existing_kraken_pos.size) > 1e-9:
            logger.error(
                "❌ %s",
                scenario_message(
                    EXISTING_POSITION_RISK,
                    f"Kraken ja tem posicao aberta em {kraken_symbol}: {existing_kraken_pos.size:+.6f}",
                ),
            )
            return None

        conflicts = self.kraken.get_market_order_conflicts(kraken_symbol, is_buy=kraken_is_buy)
        if conflicts:
            ids = ", ".join(c.order_id for c in conflicts)
            logger.error(
                "❌ %s",
                scenario_message(
                    KRAKEN_SELF_FILL_RISK,
                    f"Kraken bloqueado por ordens abertas em {kraken_symbol} ({ids})",
                ),
            )
            return None

        sizing = self.build_pair_sizing_plan(symbol, notional)
        nado_mid = sizing.nado_mid
        kraken_mid = sizing.kraken_mid
        nado_qty = sizing.nado_qty
        kraken_qty = sizing.kraken_qty
        actual_notional = sizing.effective_notional_usd
        if not sizing.can_execute:
            logger.error("❌ %s", sizing.blocked_reason)
            return None

        if requested_kraken_leverage > 0 or requested_kraken_margin_mode:
            self.kraken.configure_futures_risk_context(
                kraken_symbol,
                leverage=requested_kraken_leverage if requested_kraken_leverage > 0 else None,
                margin_mode=requested_kraken_margin_mode or None,
            )

        logger.info("╔═══ ABRINDO PAR DELTA-NEUTRO ═══")
        logger.info("║ Símbolo:  %s", symbol)
        logger.info("║ Notional solicitado: $%.2f por perna", notional)
        logger.info("║ Notional efetivo:    ~$%.2f por perna", actual_notional)
        if sizing.common_min_notional_usd > 0:
            logger.info(
                "║ Mínimo executável:  Nado ~$%.2f | Kraken ~$%.2f | comum ~$%.2f",
                sizing.nado_min_notional_usd,
                sizing.kraken_min_notional_usd,
                sizing.common_min_notional_usd,
            )
        logger.info("║ NADO:     %s  qty=%.6f  @ ~%.4f", nado_side.upper(), nado_qty, nado_mid)
        logger.info("║ KRAKEN:   %s  qty=%.6f  @ ~%.4f", kraken_side.upper(), kraken_qty, kraken_mid)
        if requested_kraken_leverage > 0 or requested_kraken_margin_mode:
            logger.info(
                "║ Kraken cfg: leverage=%s mode=%s",
                f"{requested_kraken_leverage:.2f}x" if requested_kraken_leverage > 0 else "-",
                requested_kraken_margin_mode or "-",
            )
        logger.info("╚═══════════════════════════════")

        # Perna 1 — Nado
        try:
            nado_res = self.nado.place_market_order(
                product_id=pid,
                quantity=nado_qty,
                is_buy=nado_is_buy,
                slippage_bps=self.slippage_bps,
                margin_mode=requested_nado_margin_mode or "cross",
                leverage=requested_nado_leverage or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ %s", scenario_message(NADO_REJECTED, f"Perna Nado falhou: {exc}"))
            return None

        if requested_nado_margin_mode == "isolated":
            detected_mode = ""
            try:
                for position in getattr(self.nado, "get_all_positions", lambda: [])():
                    if getattr(position, "product_id", None) == pid:
                        detected_mode = str(getattr(position, "margin_mode", "") or "").lower()
                        break
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ %s", scenario_message(NADO_REJECTED, f"falha ao validar isolated Nado: {exc}"))
            if detected_mode != "isolated":
                logger.error("❌ modo isolated nao confirmado na Nado (detectado=%s)", detected_mode or "-")
                try:
                    self.nado.place_market_order(
                        product_id=pid,
                        quantity=nado_qty,
                        is_buy=not nado_is_buy,
                        slippage_bps=self.slippage_bps,
                        reduce_only=True,
                    )
                except Exception as exc2:  # noqa: BLE001
                    logger.error("   ❌ %s", scenario_message(PARTIAL_UNWIND_RISK, f"Falha no rollback Nado: {exc2}"))
                return None

        # Perna 2 — Kraken (hedge oposto)
        try:
            self.kraken.place_market_order(
                symbol=kraken_symbol,
                quantity=kraken_qty,
                is_buy=kraken_is_buy,
                margin_mode=requested_kraken_margin_mode or None,
                leverage=requested_kraken_leverage or None,
            )
            if requested_kraken_margin_mode:
                time.sleep(1)
                kraken_pos = self.kraken.get_position(kraken_symbol)
                detected_mode = str(getattr(kraken_pos, "margin_mode", "") or "").lower()
                if detected_mode and detected_mode != requested_kraken_margin_mode:
                    logger.warning(
                        "⚠️ Kraken confirmou margin=%s embora solicitado=%s; mantendo posicao e registrando modo efetivo",
                        detected_mode,
                        requested_kraken_margin_mode,
                    )
                elif requested_kraken_margin_mode == "isolated" and not detected_mode:
                    logger.warning("⚠️ isolated solicitado na Kraken, mas a API nao retornou modo; mantendo posicao")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ %s", scenario_message(KRAKEN_SELF_FILL_RISK, f"Perna Kraken falhou: {exc}"))
            try:
                self.nado.place_market_order(
                    product_id=pid, quantity=nado_qty, is_buy=not nado_is_buy,
                    slippage_bps=self.slippage_bps,
                    reduce_only=True,
                )
                logger.info("   ↩️ %s", scenario_message(ROLLBACK_EXECUTED, "perna Nado revertida"))
            except Exception as exc2:  # noqa: BLE001
                logger.error(
                    "   ❌ %s",
                    scenario_message(PARTIAL_UNWIND_RISK, f"Falha no rollback Nado: {exc2}"),
                )
            return None

        protection_plan = (
            self.build_pair_protection_plan(
                nado_side=nado_side,
                kraken_side=kraken_side,
                nado_entry=nado_mid,
                kraken_entry=kraken_mid,
            )
            if attach_default_protective_orders
            else {}
        )

        state = PairState(
            symbol=symbol,
            nado_product_id=pid,
            kraken_symbol=kraken_symbol,
            nado_side=nado_side,
            kraken_side=kraken_side,
            requested_notional_usd=notional,
            effective_notional_usd=actual_notional,
            nado_qty=nado_qty,
            kraken_qty=kraken_qty,
            nado_entry=nado_mid,
            kraken_entry=kraken_mid,
            nado_network=str(getattr(self.nado, "network", "")),
            nado_subaccount_name=str(getattr(self.nado, "subaccount_name", "")),
            nado_subaccount_hex=str(getattr(self.nado, "subaccount_hex", "")),
            nado_owner_address=str(getattr(self.nado, "owner_address", getattr(self.nado, "owner", ""))),
            nado_linked_signer_address=str(getattr(self.nado, "linked_signer_address", "") or ""),
            kraken_account=str(getattr(self.kraken, "account", "") or ""),
            kraken_account_symbol=str(getattr(self.kraken, "account_symbol", "") or ""),
            kraken_api_fingerprint=str(getattr(self.kraken, "api_fingerprint", "") or ""),
            kraken_subaccount_mode=str(
                getattr(self.kraken, "get_isolation_context", lambda: {})().get("subaccount_mode", "")
            ),
            kraken_requested_leverage=requested_kraken_leverage,
            kraken_margin_mode=(detected_mode or requested_kraken_margin_mode) if requested_kraken_margin_mode else requested_kraken_margin_mode,
            execution_mode="hedged",
            effective_venue="hedged",
            nado_requested_leverage=requested_nado_leverage,
            nado_margin_mode=requested_nado_margin_mode,
            kraken_sandbox=getattr(self.kraken, "sandbox", None),
            pair_stop_loss_pct=float(protection_plan.get("pair_stop_loss_pct") or 0.0),
            pair_take_profit_pct=float(protection_plan.get("pair_take_profit_pct") or 0.0),
            nado_stop_price=float(protection_plan.get("nado_stop_price") or 0.0),
            kraken_stop_price=float(protection_plan.get("kraken_stop_price") or 0.0),
            nado_take_profit_price=float(protection_plan.get("nado_take_profit_price") or 0.0),
            kraken_take_profit_price=float(protection_plan.get("kraken_take_profit_price") or 0.0),
            nado_close_side=str(protection_plan.get("nado_close_side") or ""),
            kraken_close_side=str(protection_plan.get("kraken_close_side") or ""),
        )
        if attach_default_protective_orders:
            self._attach_pair_protective_orders(
                symbol=symbol,
                pid=pid,
                kraken_symbol=kraken_symbol,
                nado_side=nado_side,
                kraken_side=kraken_side,
                nado_qty=nado_qty,
                kraken_qty=kraken_qty,
                protection_plan=protection_plan,
            )
            logger.info(
                "plano delta-neutro | Nado stop=%.4f tp=%.4f fecha=%s | Kraken stop=%.4f tp=%.4f fecha=%s",
                state.nado_stop_price,
                state.nado_take_profit_price,
                state.nado_close_side.upper() if state.nado_close_side else "-",
                state.kraken_stop_price,
                state.kraken_take_profit_price,
                state.kraken_close_side.upper() if state.kraken_close_side else "-",
            )
        logger.info("✅ Par aberto. Delta líquido ~0. Monitorar via status.")
        return state

    @staticmethod
    def _state_effective_venue(state: PairState) -> str:
        venue = str(state.effective_venue or "").strip().lower()
        mode = str(state.execution_mode or "").strip().lower()
        if venue in {"nado", "dex"} or mode in {"nado_only", "dex_only"}:
            return "nado"
        if venue in {"kraken", "cex"} or mode in {"kraken_only", "cex_only"}:
            return "kraken"
        if state.nado_qty > 0 and state.kraken_qty <= 0:
            return "nado"
        if state.kraken_qty > 0 and state.nado_qty <= 0:
            return "kraken"
        return "hedged"

    def _status_nado_only(self, state: PairState) -> Dict[str, float]:
        nado_mid = self.nado.get_market_mid_price(state.nado_product_id)
        nado_pos_qty = self.nado.get_perp_position_size(state.nado_product_id)
        nado_pnl = nado_pos_qty * (nado_mid - state.nado_entry) if state.nado_entry else 0.0
        net_delta_usd = nado_pos_qty * nado_mid
        notional = abs(net_delta_usd) or state.effective_notional_usd
        exposure_bps = (abs(net_delta_usd) / notional) * 10000 if notional else 0.0
        report = {
            "symbol": state.symbol,
            "requested_notional_usd": state.requested_notional_usd,
            "effective_notional_usd": state.effective_notional_usd,
            "nado_mid": nado_mid,
            "kraken_mid": 0.0,
            "nado_qty": nado_pos_qty,
            "kraken_qty": 0.0,
            "nado_pnl_usd": nado_pnl,
            "kraken_pnl_usd": 0.0,
            "kraken_leverage": 0.0,
            "kraken_requested_leverage": 0.0,
            "kraken_margin_mode": "",
            "total_pnl_usd": nado_pnl,
            "net_delta_usd": net_delta_usd,
            "drift_bps": exposure_bps,
            "execution_mode": state.execution_mode,
            "effective_venue": "nado",
            "nado_margin_mode": state.nado_margin_mode,
            "nado_requested_leverage": state.nado_requested_leverage,
        }
        logger.info("┌─ STATUS SOLO NADO/DEX %s ─┐", state.symbol)
        logger.info("│ Notional req/eff: $%.2f / $%.2f", state.requested_notional_usd, state.effective_notional_usd)
        logger.info(
            "│ Nado  %+.6f @ %.4f -> PnL=%.2f  mode=%s lev=%s",
            nado_pos_qty,
            nado_mid,
            nado_pnl,
            state.nado_margin_mode or "-",
            f"{state.nado_requested_leverage:.2f}x" if state.nado_requested_leverage > 0 else "-",
        )
        logger.info("│ Exposicao direcional: $%.2f", net_delta_usd)
        logger.info("│ PnL total:            $%.2f", nado_pnl)
        logger.info("└─────────────────┘")
        return report

    def _status_kraken_only(self, state: PairState) -> Dict[str, float]:
        try:
            kraken_pos = self.kraken.get_position(state.kraken_symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ %s", scenario_message(KRAKEN_POSITION_PARSE_ERROR, str(exc)))
            raise
        kraken_mid = kraken_pos.mark_price or self.kraken.get_market_mid_price(state.kraken_symbol)
        kraken_pnl = (
            kraken_pos.unrealized_pnl
            if abs(kraken_pos.unrealized_pnl) > 0
            else kraken_pos.size * (kraken_mid - state.kraken_entry)
        )
        net_delta_usd = kraken_pos.size * kraken_mid
        notional = abs(net_delta_usd) or state.effective_notional_usd
        exposure_bps = (abs(net_delta_usd) / notional) * 10000 if notional else 0.0
        report = {
            "symbol": state.symbol,
            "requested_notional_usd": state.requested_notional_usd,
            "effective_notional_usd": state.effective_notional_usd,
            "nado_mid": 0.0,
            "kraken_mid": kraken_mid,
            "nado_qty": 0.0,
            "kraken_qty": kraken_pos.size,
            "nado_pnl_usd": 0.0,
            "kraken_pnl_usd": kraken_pnl,
            "kraken_leverage": kraken_pos.leverage,
            "kraken_requested_leverage": state.kraken_requested_leverage,
            "kraken_margin_mode": state.kraken_margin_mode,
            "total_pnl_usd": kraken_pnl,
            "net_delta_usd": net_delta_usd,
            "drift_bps": exposure_bps,
            "execution_mode": state.execution_mode,
            "effective_venue": "kraken",
        }
        logger.info("┌─ STATUS SOLO KRAKEN/CEX %s ─┐", state.symbol)
        logger.info("│ Notional req/eff: $%.2f / $%.2f", state.requested_notional_usd, state.effective_notional_usd)
        logger.info(
            "│ Kraken %+.6f @ %.4f -> PnL=%.2f  lev=%.2fx mode=%s",
            kraken_pos.size,
            kraken_mid,
            kraken_pnl,
            kraken_pos.leverage,
            state.kraken_margin_mode or "-",
        )
        logger.info("│ Exposicao direcional: $%.2f", net_delta_usd)
        logger.info("│ PnL total:            $%.2f", kraken_pnl)
        logger.info("└─────────────────┘")
        return report

    # ═══════════════════════════════════════════════════════════
    #  STATUS (DRIFT + PnL)
    # ═══════════════════════════════════════════════════════════
    def status(self, state: PairState) -> Dict[str, float]:
        self._validate_saved_state_context(state, allow_legacy=True)
        venue = self._state_effective_venue(state)
        if venue == "nado":
            return self._status_nado_only(state)
        if venue == "kraken":
            return self._status_kraken_only(state)
        protection_plan = {
            "pair_stop_loss_pct": state.pair_stop_loss_pct,
            "pair_take_profit_pct": state.pair_take_profit_pct,
            "nado_stop_price": state.nado_stop_price,
            "kraken_stop_price": state.kraken_stop_price,
            "nado_take_profit_price": state.nado_take_profit_price,
            "kraken_take_profit_price": state.kraken_take_profit_price,
            "nado_close_side": state.nado_close_side,
            "kraken_close_side": state.kraken_close_side,
        }
        if not any(
            [
                protection_plan["pair_stop_loss_pct"],
                protection_plan["pair_take_profit_pct"],
                protection_plan["nado_stop_price"],
                protection_plan["kraken_stop_price"],
                protection_plan["nado_take_profit_price"],
                protection_plan["kraken_take_profit_price"],
            ]
        ):
            protection_plan = self.build_pair_protection_plan(
                nado_side=state.nado_side,
                kraken_side=state.kraken_side,
                nado_entry=state.nado_entry,
                kraken_entry=state.kraken_entry,
            )
        nado_mid = self.nado.get_market_mid_price(state.nado_product_id)
        nado_pos_qty = self.nado.get_perp_position_size(state.nado_product_id)
        try:
            kraken_pos = self.kraken.get_position(state.kraken_symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ %s", scenario_message(KRAKEN_POSITION_PARSE_ERROR, str(exc)))
            raise
        kraken_mid = kraken_pos.mark_price or self.kraken.get_market_mid_price(state.kraken_symbol)

        # PnL de cada perna (marcação a mercado, ignorando funding)
        nado_pnl = nado_pos_qty * (nado_mid - state.nado_entry)
        kraken_pnl = (
            kraken_pos.unrealized_pnl
            if abs(kraken_pos.unrealized_pnl) > 0
            else kraken_pos.size * (kraken_mid - state.kraken_entry)
        )

        # Delta líquido em USD (quanto de exposição direcional sobrou)
        net_delta_usd = nado_pos_qty * nado_mid + kraken_pos.size * kraken_mid
        notional_total = state.effective_notional_usd * 2
        drift_bps = (abs(net_delta_usd) / notional_total) * 10000 if notional_total else 0

        report = {
            "symbol": state.symbol,
            "requested_notional_usd": state.requested_notional_usd,
            "effective_notional_usd": state.effective_notional_usd,
            "nado_mid": nado_mid,
            "kraken_mid": kraken_mid,
            "nado_qty": nado_pos_qty,
            "kraken_qty": kraken_pos.size,
            "nado_pnl_usd": nado_pnl,
            "kraken_pnl_usd": kraken_pnl,
            "kraken_leverage": kraken_pos.leverage,
            "kraken_requested_leverage": state.kraken_requested_leverage,
            "kraken_margin_mode": state.kraken_margin_mode,
            "total_pnl_usd": nado_pnl + kraken_pnl,
            "net_delta_usd": net_delta_usd,
            "drift_bps": drift_bps,
            "pair_stop_loss_pct": float(protection_plan.get("pair_stop_loss_pct") or 0.0),
            "pair_take_profit_pct": float(protection_plan.get("pair_take_profit_pct") or 0.0),
            "nado_stop_price": float(protection_plan.get("nado_stop_price") or 0.0),
            "kraken_stop_price": float(protection_plan.get("kraken_stop_price") or 0.0),
            "nado_take_profit_price": float(protection_plan.get("nado_take_profit_price") or 0.0),
            "kraken_take_profit_price": float(protection_plan.get("kraken_take_profit_price") or 0.0),
            "nado_close_side": str(protection_plan.get("nado_close_side") or ""),
            "kraken_close_side": str(protection_plan.get("kraken_close_side") or ""),
        }
        logger.info("┌─ STATUS %s ─┐", state.symbol)
        logger.info("│ Notional req/eff: $%.2f / $%.2f",
                    state.requested_notional_usd, state.effective_notional_usd)
        if state.nado_subaccount_name or state.kraken_account or state.kraken_api_fingerprint:
            logger.info(
                "│ Contexto: Nado=%s | Kraken=%s | api=%s | mode=%s",
                state.nado_subaccount_name or "-",
                state.kraken_account or "-",
                state.kraken_api_fingerprint or "-",
                state.kraken_subaccount_mode or "-",
            )
        logger.info("│ Nado  %+.6f  @ %.4f → PnL=%.2f", nado_pos_qty, nado_mid, nado_pnl)
        logger.info("│ Kraken %+.6f @ %.4f → PnL=%.2f  lev=%.2fx",
                    kraken_pos.size, kraken_mid, kraken_pnl, kraken_pos.leverage)
        if state.kraken_requested_leverage > 0 or state.kraken_margin_mode:
            logger.info(
                "│ Kraken alvo: lev=%s mode=%s",
                f"{state.kraken_requested_leverage:.2f}x" if state.kraken_requested_leverage > 0 else "-",
                state.kraken_margin_mode or "-",
            )
        if report["pair_stop_loss_pct"] > 0 or report["pair_take_profit_pct"] > 0:
            logger.info(
                "│ Plano par: stop=%.2f%% | alvo=%.2f%%",
                report["pair_stop_loss_pct"] * 100,
                report["pair_take_profit_pct"] * 100,
            )
            logger.info(
                "│ Nado  stop=%.4f tp=%.4f fecha=%s",
                report["nado_stop_price"],
                report["nado_take_profit_price"],
                report["nado_close_side"].upper() if report["nado_close_side"] else "-",
            )
            logger.info(
                "│ Kraken stop=%.4f tp=%.4f fecha=%s",
                report["kraken_stop_price"],
                report["kraken_take_profit_price"],
                report["kraken_close_side"].upper() if report["kraken_close_side"] else "-",
            )
        logger.info("│ Delta liquido: $%.2f (%.1f bps do notional)", net_delta_usd, drift_bps)
        logger.info("│ PnL total:     $%.2f", nado_pnl + kraken_pnl)
        logger.info("└─────────────────┘")
        if drift_bps > max(self.drift_bps, 200):
            logger.warning("⚠️ %s", scenario_message(DRIFT_HIGH, f"drift em {drift_bps:.1f} bps"))
        return report

    # ═══════════════════════════════════════════════════════════
    #  REBALANCEAMENTO
    # ═══════════════════════════════════════════════════════════
    def rebalance(self, state: PairState) -> bool:
        """Se drift > drift_bps, envia ordem corretiva na perna mais descoberta."""
        self._validate_saved_state_context(state, allow_legacy=False)
        if self._state_effective_venue(state) != "hedged":
            logger.info("rebalance nao se aplica a estado solo (%s)", self._state_effective_venue(state))
            return False
        self._assert_nado_trade_ready()
        st = self.status(state)
        if st["drift_bps"] <= self.drift_bps:
            logger.info("   drift %.1f bps ≤ threshold %d bps — sem ajuste",
                        st["drift_bps"], self.drift_bps)
            return False

        # Quanto em USD falta zerar o delta
        delta_usd = st["net_delta_usd"]
        # Ajuste mais barato: abrir perna oposta na exchange cuja liquidez é melhor.
        # Default: ajustar via Kraken (geralmente mais líquida).
        kraken_mid = st["kraken_mid"]
        qty = abs(delta_usd) / kraken_mid
        qty = self.kraken.round_quantity_to_increment(state.kraken_symbol, qty)
        if qty <= 0:
            logger.info("   drift muito pequeno para ajustar (qty=0)")
            return False

        is_buy = delta_usd < 0  # delta negativo = curto → precisa comprar
        conflicts = self.kraken.get_market_order_conflicts(state.kraken_symbol, is_buy=is_buy)
        if conflicts:
            ids = ", ".join(c.order_id for c in conflicts)
            logger.error(
                "❌ %s",
                scenario_message(
                    KRAKEN_SELF_FILL_RISK,
                    f"rebalance bloqueado em {state.kraken_symbol} por ordens abertas ({ids})",
                ),
            )
            return False
        logger.info("⚖️ Rebalance: delta=$%.2f → ajuste Kraken %s qty=%.6f",
                    delta_usd, "BUY" if is_buy else "SELL", qty)
        validate_subaccount_rule = getattr(self.kraken, "validate_entry_subaccount_rule", None)
        if callable(validate_subaccount_rule):
            validate_subaccount_rule(
                require_subaccount=getattr(self, "kraken_require_subaccount", False),
                declared_is_subaccount=getattr(self, "kraken_api_is_subaccount", False),
            )
        self.kraken.place_market_order(state.kraken_symbol, qty, is_buy=is_buy)
        return True

    # ═══════════════════════════════════════════════════════════
    #  STOP GLOBAL + UNWIND
    # ═══════════════════════════════════════════════════════════
    def should_unwind(self, state: PairState) -> bool:
        self._validate_saved_state_context(state, allow_legacy=False)
        st = self.status(state)
        multiplier = 2 if self._state_effective_venue(state) == "hedged" else 1
        notional_total = state.effective_notional_usd * multiplier
        loss_pct = st["total_pnl_usd"] / notional_total if notional_total else 0
        if loss_pct <= -self.max_pair_loss_pct:
            logger.warning(
                "🛑 %s",
                scenario_message(
                    STOP_GLOBAL_TRIGGERED,
                    f"PnL {loss_pct * 100:.2f}% <= -{self.max_pair_loss_pct * 100:.2f}%",
                ),
            )
            return True
        return False

    def unwind(self, state: PairState) -> None:
        self._validate_saved_state_context(state, allow_legacy=False)
        venue = self._state_effective_venue(state)
        if venue in {"hedged", "nado"}:
            self._assert_nado_trade_ready()
        logger.info("🧹 Desmontando %s %s", "par" if venue == "hedged" else f"solo {venue}", state.symbol)
        try:
            if venue in {"hedged", "nado"}:
                self.nado.cancel_all_orders(state.nado_product_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("   ?? falha ao cancelar ordens da Nado em %s: %s", state.symbol, exc)
        try:
            if venue in {"hedged", "kraken"}:
                self.kraken.cancel_all_orders(state.kraken_symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("   ?? falha ao cancelar ordens da Kraken em %s: %s", state.symbol, exc)
        # Fecha Nado
        if venue in {"hedged", "nado"}:
            try:
                nado_pos = self.nado.get_perp_position_size(state.nado_product_id)
                if abs(nado_pos) > 1e-9:
                    self.nado.place_market_order(
                        product_id=state.nado_product_id,
                        quantity=abs(nado_pos),
                        is_buy=nado_pos < 0,  # long ativo → vender; short → comprar
                        slippage_bps=self.slippage_bps,
                        reduce_only=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ %s", scenario_message(PARTIAL_UNWIND_RISK, f"falha ao fechar Nado: {exc}"))
        # Fecha Kraken
        if venue in {"hedged", "kraken"}:
            try:
                self.kraken.close_position(state.kraken_symbol)
            except Exception as exc:  # noqa: BLE001
                logger.error("   ❌ %s", scenario_message(PARTIAL_UNWIND_RISK, f"falha ao fechar Kraken: {exc}"))
        logger.info("✅ Unwind finalizado")

    # ═══════════════════════════════════════════════════════════
    #  LOOP DE FARMING (opcional)
    # ═══════════════════════════════════════════════════════════

    def partial_unwind_quantities(
        self,
        state: PairState,
        *,
        nado_qty: float,
        kraken_qty: float,
    ) -> Optional[PairState]:
        self._validate_saved_state_context(state, allow_legacy=False)
        self._assert_nado_trade_ready()
        nado_pos = self.nado.get_perp_position_size(state.nado_product_id)
        kraken_pos = self.kraken.get_position(state.kraken_symbol)
        close_nado_qty = min(
            abs(nado_pos),
            self.nado.round_quantity_to_increment(state.nado_product_id, float(nado_qty)),
        )
        close_kraken_qty = min(
            abs(kraken_pos.size),
            self.kraken.round_quantity_to_increment(state.kraken_symbol, float(kraken_qty)),
        )
        if close_nado_qty <= 0 or close_kraken_qty <= 0:
            logger.warning(
                "?? partial unwind sem quantidade executavel em %s (nado=%s kraken=%s)",
                state.symbol,
                close_nado_qty,
                close_kraken_qty,
            )
            return state

        logger.info(
            "?? Partial unwind %s | Nado qty=%.6f | Kraken qty=%.6f",
            state.symbol,
            close_nado_qty,
            close_kraken_qty,
        )
        try:
            self.nado.place_market_order(
                product_id=state.nado_product_id,
                quantity=close_nado_qty,
                is_buy=nado_pos < 0,
                slippage_bps=self.slippage_bps,
                reduce_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("   ? %s", scenario_message(PARTIAL_UNWIND_RISK, f"falha parcial Nado: {exc}"))
            return state
        try:
            self.kraken.place_market_order(
                state.kraken_symbol,
                close_kraken_qty,
                is_buy=kraken_pos.size < 0,
                reduce_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("   ? %s", scenario_message(PARTIAL_UNWIND_RISK, f"falha parcial Kraken: {exc}"))
            return state

        remaining_nado = max(state.nado_qty - close_nado_qty, 0.0)
        remaining_kraken = max(state.kraken_qty - close_kraken_qty, 0.0)
        if remaining_nado <= 1e-9 or remaining_kraken <= 1e-9:
            return None

        remaining_ratio = min(
            remaining_nado / state.nado_qty if state.nado_qty else 0.0,
            remaining_kraken / state.kraken_qty if state.kraken_qty else 0.0,
        )
        if remaining_ratio <= 1e-9:
            return None

        return PairState(
            symbol=state.symbol,
            nado_product_id=state.nado_product_id,
            kraken_symbol=state.kraken_symbol,
            nado_side=state.nado_side,
            kraken_side=state.kraken_side,
            requested_notional_usd=state.requested_notional_usd * remaining_ratio,
            effective_notional_usd=state.effective_notional_usd * remaining_ratio,
            nado_qty=remaining_nado,
            kraken_qty=remaining_kraken,
            nado_entry=state.nado_entry,
            kraken_entry=state.kraken_entry,
            nado_network=state.nado_network,
            nado_subaccount_name=state.nado_subaccount_name,
            nado_subaccount_hex=state.nado_subaccount_hex,
            nado_owner_address=state.nado_owner_address,
            nado_linked_signer_address=state.nado_linked_signer_address,
            kraken_account=state.kraken_account,
            kraken_account_symbol=state.kraken_account_symbol,
            kraken_api_fingerprint=state.kraken_api_fingerprint,
            kraken_subaccount_mode=state.kraken_subaccount_mode,
            kraken_requested_leverage=state.kraken_requested_leverage,
            kraken_margin_mode=state.kraken_margin_mode,
            kraken_sandbox=state.kraken_sandbox,
            pair_stop_loss_pct=state.pair_stop_loss_pct,
            pair_take_profit_pct=state.pair_take_profit_pct,
            nado_stop_price=state.nado_stop_price,
            kraken_stop_price=state.kraken_stop_price,
            nado_take_profit_price=state.nado_take_profit_price,
            kraken_take_profit_price=state.kraken_take_profit_price,
            nado_close_side=state.nado_close_side,
            kraken_close_side=state.kraken_close_side,
            opened_at=state.opened_at,
        )

    def farm_loop(
        self,
        state: PairState,
        *,
        check_interval_secs: int = 60,
        max_iterations: Optional[int] = None,
    ) -> None:
        """
        Roda indefinidamente: monitora drift, rebalanceia, aplica stop global.
        Ctrl+C para sair (sem fechar posições — use `unwind` explicitamente).
        """
        self._validate_saved_state_context(state, allow_legacy=False)
        self._assert_nado_trade_ready()
        i = 0
        logger.info("🔁 Farm loop iniciado (interval=%ds)", check_interval_secs)
        try:
            while True:
                i += 1
                logger.info("—— iteração #%d ——", i)
                if self.should_unwind(state):
                    self.unwind(state)
                    return
                self.rebalance(state)
                if max_iterations and i >= max_iterations:
                    logger.info("Max iterações atingido. Saindo (posições intactas).")
                    return
                time.sleep(check_interval_secs)
        except KeyboardInterrupt:
            logger.info("↩️ Farm loop interrompido pelo usuário. Posições intactas.")
