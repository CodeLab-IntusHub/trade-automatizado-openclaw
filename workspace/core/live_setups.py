from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Sequence

import pandas as pd

from .delta_neutral import PairState
from .setups import (
    SETUP_CATALOG,
    _hybrid_15m_long_signal,
    _hybrid_15m_profile_params,
    _hybrid_15m_short_signal,
    calculate_divergence_volume_signal,
    calculate_triangle_breakout_signal,
    get_divergence_volume_config,
    get_funding_arb_config,
    get_triangle_breakout_config,
    normalize_hybrid_profile,
    normalize_setup_key,
)


@dataclass(frozen=True)
class SetupRuntimeSignal:
    setup_key: str
    timeframe: str
    action: str
    side: str = ""
    reason: str = ""
    reference_entry_price: float = 0.0
    stop_price: float = 0.0
    take_profit: float = 0.0
    take_profit_targets: list[float] = field(default_factory=list)
    target_weights: list[float] = field(default_factory=list)
    close_after_bars: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagedSetupState:
    setup_key: str
    symbol: str
    timeframe: str
    side: str
    pair_state: PairState
    hybrid_profile: str = ""
    reference_entry_price: float = 0.0
    stop_price: float = 0.0
    take_profit: float = 0.0
    targets_hit: int = 0
    close_after_bars: int = 0
    entry_reason: str = ""
    execution_mode: str = "hedged"
    effective_venue: str = "hedged"
    margin_mode: str = ""
    leverage: float = 0.0
    liquidation_price: float = 0.0
    liquidation_buffer_pct: float = 0.0
    opened_bar_at: str = ""
    opened_at_ts: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["pair_state"] = self.pair_state.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "ManagedSetupState":
        data = dict(payload)
        data["pair_state"] = PairState.from_dict(data["pair_state"])
        data.setdefault("hybrid_profile", "")
        data.setdefault("reference_entry_price", 0.0)
        data.setdefault("stop_price", 0.0)
        data.setdefault("take_profit", 0.0)
        data.setdefault("targets_hit", 0)
        data.setdefault("close_after_bars", 0)
        data.setdefault("entry_reason", "")
        data.setdefault("execution_mode", "hedged")
        data.setdefault("effective_venue", "hedged")
        data.setdefault("margin_mode", "")
        data.setdefault("leverage", 0.0)
        data.setdefault("liquidation_price", 0.0)
        data.setdefault("liquidation_buffer_pct", 0.0)
        data.setdefault("opened_bar_at", "")
        data.setdefault("opened_at_ts", 0.0)
        data.setdefault("metadata", {})
        return cls(**data)


def _build_three_target_ladder(entry_price: float, final_target: float) -> tuple[list[float], list[float]]:
    if entry_price <= 0 or final_target <= 0 or abs(final_target - entry_price) < 1e-9:
        return [], []
    step = (final_target - entry_price) / 3.0
    targets = [
        float(entry_price + step),
        float(entry_price + step * 2),
        float(final_target),
    ]
    return targets, [1 / 3, 1 / 3, 1 / 3]


def _build_r_multiple_ladder(entry_price: float, stop_price: float, side: str) -> tuple[list[float], list[float]]:
    if entry_price <= 0 or stop_price <= 0 or abs(entry_price - stop_price) < 1e-9:
        return [], []
    risk = abs(entry_price - stop_price)
    multiples = [1.0, 1.5, 2.0, 3.0]
    if side == "long":
        targets = [float(entry_price + risk * multiple) for multiple in multiples]
    else:
        targets = [float(entry_price - risk * multiple) for multiple in multiples]
    return targets, [0.25, 0.25, 0.25, 0.25]


def _low_stoch_near_ema_support(row: pd.Series, recent: pd.DataFrame, near_pct: float) -> bool:
    recent_low = float(recent["low"].min())
    for col in ["ema8", "ema21", "ema80", "ema200"]:
        level = float(row[col])
        if level > 0 and recent_low <= level * (1 + near_pct):
            return True
    return False


def _low_stoch_near_ema_resistance(row: pd.Series, recent: pd.DataFrame, near_pct: float) -> bool:
    recent_high = float(recent["high"].max())
    for col in ["ema8", "ema21", "ema80", "ema200"]:
        level = float(row[col])
        if level > 0 and recent_high >= level * (1 - near_pct):
            return True
    return False


def _low_stoch_long_stop(entry_price: float, row: pd.Series, recent: pd.DataFrame) -> float | None:
    atr = float(row["atr14"])
    if entry_price <= 0 or atr <= 0 or math.isnan(atr):
        return None
    structure_stop = float(recent["low"].min()) - atr * 0.15
    atr_stop = entry_price - atr
    stop_price = min(structure_stop, atr_stop)
    if stop_price <= 0:
        return None
    risk_pct = (entry_price - stop_price) / entry_price
    if risk_pct < 0.01:
        stop_price = entry_price * 0.99
    elif risk_pct > 0.18:
        stop_price = atr_stop
        risk_pct = (entry_price - stop_price) / entry_price
        if risk_pct > 0.18 or stop_price <= 0:
            return None
    return float(stop_price)


def _low_stoch_short_stop(entry_price: float, row: pd.Series, recent: pd.DataFrame) -> float | None:
    atr = float(row["atr14"])
    if entry_price <= 0 or atr <= 0 or math.isnan(atr):
        return None
    structure_stop = float(recent["high"].max()) + atr * 0.15
    atr_stop = entry_price + atr
    stop_price = max(structure_stop, atr_stop)
    risk_pct = (stop_price - entry_price) / entry_price
    if risk_pct < 0.01:
        stop_price = entry_price * 1.01
    elif risk_pct > 0.18:
        stop_price = atr_stop
        risk_pct = (stop_price - entry_price) / entry_price
        if risk_pct > 0.18 or stop_price <= 0:
            return None
    return float(stop_price)


def _low_stoch_storm_long_4h_signal(df: pd.DataFrame, timeframe: str) -> SetupRuntimeSignal | None:
    if timeframe != "4h" or len(df) < 220:
        return None
    row = df.iloc[-1]
    prev = df.iloc[-2]
    required_cols = ["open", "high", "low", "close", "ema8", "ema21", "ema80", "ema200", "rsi14", "stoch_k", "stoch_d", "atr14"]
    if row[required_cols].isna().any() or prev[["close", "ema8", "ema80", "ema200", "stoch_k", "stoch_d"]].isna().any():
        return None

    lookback = 14
    breakout_lookback = 8
    recent = df.iloc[-lookback:]
    breakout_window = df.iloc[-(breakout_lookback + 1) : -1]
    if recent.empty or breakout_window.empty:
        return None

    close = float(row["close"])
    rsi14 = float(row["rsi14"])
    stoch_turn = (
        float(recent["stoch_k"].min()) <= 40.0
        and float(row["stoch_k"]) > float(row["stoch_d"])
        and (float(prev["stoch_k"]) <= float(prev["stoch_d"]) or float(row["stoch_k"]) > float(prev["stoch_k"]) + 1.5)
    )
    recovery = close > float(row["ema8"]) and (
        float(prev["close"]) <= float(prev["ema8"])
        or close > float(breakout_window["high"].max())
        or (float(prev["close"]) <= float(prev["ema80"]) and close > float(row["ema80"]))
        or (float(prev["close"]) <= float(prev["ema200"]) and close > float(row["ema200"]))
    )
    trend_guard = close > float(row["ema80"]) and 45.0 <= rsi14 <= 68.0
    structure = _low_stoch_near_ema_support(row, recent, 0.08) or close > float(breakout_window["high"].max())
    if not (stoch_turn and recovery and trend_guard and structure):
        return None

    stop_price = _low_stoch_long_stop(close, row, recent)
    if stop_price is None:
        return None
    risk_pct = (close - stop_price) / close
    if risk_pct > 0.06:
        return None
    targets, weights = _build_r_multiple_ladder(close, stop_price, "long")
    if not targets:
        return None
    return SetupRuntimeSignal(
        setup_key="low-stoch-storm",
        timeframe="4h",
        action="enter",
        side="long",
        reason="Low Stoch Storm LONG 4h: Stoch saiu de zona baixa, close>EMA80, RSI14 45-68 e risco<=6%",
        reference_entry_price=close,
        stop_price=stop_price,
        take_profit=targets[-1],
        take_profit_targets=targets,
        target_weights=weights,
        close_after_bars=80,
        metadata={
            "risk_pct": risk_pct * 100,
            "rsi14": rsi14,
            "stoch_k": float(row["stoch_k"]),
            "stoch_d": float(row["stoch_d"]),
            "ema80": float(row["ema80"]),
            "target_model": "1R/1.5R/2R/3R",
        },
    )


def _low_stoch_storm_short_4h_signal(df: pd.DataFrame, timeframe: str) -> SetupRuntimeSignal | None:
    if timeframe != "4h" or len(df) < 220:
        return None
    row = df.iloc[-1]
    prev = df.iloc[-2]
    required_cols = ["open", "high", "low", "close", "ema8", "ema21", "ema80", "ema200", "rsi14", "stoch_k", "stoch_d", "atr14"]
    if row[required_cols].isna().any() or prev[["close", "ema8", "ema80", "ema200", "stoch_k", "stoch_d"]].isna().any():
        return None

    lookback = 14
    breakout_lookback = 8
    recent = df.iloc[-lookback:]
    breakout_window = df.iloc[-(breakout_lookback + 1) : -1]
    if recent.empty or breakout_window.empty:
        return None

    close = float(row["close"])
    rsi14 = float(row["rsi14"])
    stoch_turn = (
        float(recent["stoch_k"].max()) >= 60.0
        and float(row["stoch_k"]) < float(row["stoch_d"])
        and (float(prev["stoch_k"]) >= float(prev["stoch_d"]) or float(row["stoch_k"]) < float(prev["stoch_k"]) - 1.5)
    )
    rejection = close < float(row["ema8"]) and (
        float(prev["close"]) >= float(prev["ema8"])
        or close < float(breakout_window["low"].min())
        or (float(prev["close"]) >= float(prev["ema80"]) and close < float(row["ema80"]))
        or (float(prev["close"]) >= float(prev["ema200"]) and close < float(row["ema200"]))
    )
    trend_guard = close < float(row["ema80"]) and 32.0 <= rsi14 <= 55.0
    structure = _low_stoch_near_ema_resistance(row, recent, 0.08) or close < float(breakout_window["low"].min())
    if not (stoch_turn and rejection and trend_guard and structure):
        return None

    stop_price = _low_stoch_short_stop(close, row, recent)
    if stop_price is None:
        return None
    risk_pct = (stop_price - close) / close
    if risk_pct > 0.06:
        return None
    targets, weights = _build_r_multiple_ladder(close, stop_price, "short")
    if not targets:
        return None
    return SetupRuntimeSignal(
        setup_key="low-stoch-storm",
        timeframe="4h",
        action="enter",
        side="short",
        reason="Low Stoch Storm SHORT 4h: Stoch saiu de zona alta, close<EMA80, RSI14 32-55 e risco<=6%",
        reference_entry_price=close,
        stop_price=stop_price,
        take_profit=targets[-1],
        take_profit_targets=targets,
        target_weights=weights,
        close_after_bars=80,
        metadata={
            "risk_pct": risk_pct * 100,
            "rsi14": rsi14,
            "stoch_k": float(row["stoch_k"]),
            "stoch_d": float(row["stoch_d"]),
            "ema80": float(row["ema80"]),
            "target_model": "1R/1.5R/2R/3R",
        },
    )


def _low_stoch_storm_4h_signal(df: pd.DataFrame, timeframe: str) -> SetupRuntimeSignal | None:
    return _low_stoch_storm_long_4h_signal(df, timeframe) or _low_stoch_storm_short_4h_signal(df, timeframe)


def _setup_exit_levels(state: ManagedSetupState) -> list[dict[str, Any]]:
    raw = state.metadata.get("target_levels")
    if not isinstance(raw, list):
        return []
    levels: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            levels.append(
                {
                    "price": float(item.get("price") or 0.0),
                    "nado_qty": float(item.get("nado_qty") or 0.0),
                    "kraken_qty": float(item.get("kraken_qty") or 0.0),
                    "label": str(item.get("label") or ""),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return levels


def _target_hit(side: str, live_price: float, target_price: float) -> bool:
    if target_price <= 0:
        return False
    if side == "long":
        return live_price >= target_price
    return live_price <= target_price


def _stop_hit(side: str, live_price: float, stop_price: float) -> bool:
    if stop_price <= 0:
        return False
    if side == "long":
        return live_price <= stop_price
    return live_price >= stop_price


def _check_setup_stop_and_targets(
    state: ManagedSetupState,
    *,
    live_price: float,
    stop_reason: str,
) -> SetupRuntimeSignal | None:
    if _stop_hit(state.side, live_price, state.stop_price):
        return SetupRuntimeSignal(state.setup_key, state.timeframe, "exit", side=state.side, reason=stop_reason)

    levels = _setup_exit_levels(state)
    if levels and state.targets_hit < len(levels):
        start_index = int(state.targets_hit)
        hit_levels: list[dict[str, Any]] = []
        for level in levels[start_index:]:
            if not _target_hit(state.side, live_price, float(level["price"])):
                break
            hit_levels.append(level)
        if hit_levels:
            end_index = start_index + len(hit_levels) - 1
            action = "exit" if end_index >= len(levels) - 1 else "partial_exit"
            if len(hit_levels) == 1:
                label = hit_levels[0]["label"] or f"TP{start_index + 1}"
            else:
                first_label = hit_levels[0]["label"] or f"TP{start_index + 1}"
                last_label = hit_levels[-1]["label"] or f"TP{end_index + 1}"
                label = f"{first_label}-{last_label}"
            return SetupRuntimeSignal(
                state.setup_key,
                state.timeframe,
                action,
                side=state.side,
                reason=f"{label} atingido",
                metadata={
                    "target_index": start_index,
                    "target_to_index": end_index,
                    "targets_advanced": len(hit_levels),
                    "nado_qty": sum(float(level["nado_qty"]) for level in hit_levels),
                    "kraken_qty": sum(float(level["kraken_qty"]) for level in hit_levels),
                },
            )
    if state.take_profit > 0 and _target_hit(state.side, live_price, state.take_profit):
        return SetupRuntimeSignal(state.setup_key, state.timeframe, "exit", side=state.side, reason="take profit final")
    return None


def evaluate_setup_entry(
    setup_key: str,
    df: pd.DataFrame,
    *,
    hybrid_profile: str | None = None,
    setup_context: dict[str, Any] | None = None,
) -> SetupRuntimeSignal | None:
    normalized = normalize_setup_key(setup_key)
    if df.empty:
        return None
    row = df.iloc[-1]
    timeframe = SETUP_CATALOG[normalized].timeframe
    setup_context = setup_context or {}

    if False:
        close = float(row["close"])
        strict = normalized.endswith("strict")
        ema_gap = (float(row["ema9"]) - float(row["ema21"])) / close if close else 0.0
        macd_gap = (float(row["macd"]) - float(row["macd_signal"])) / close if close else 0.0
        rsi_min, rsi_max = (55.0, 68.0) if strict else (55.0, 70.0)
        ema_gap_min = 0.0015 if strict else 0.0010
        macd_gap_min = 0.0008 if strict else 0.0005
        volume_ratio_min = 1.15 if strict else 1.05
        if (
            row["ema9"] > row["ema21"]
            and close > float(row["ema50"])
            and rsi_min < row["rsi"] < rsi_max
            and row["macd"] > row["macd_signal"]
            and ema_gap > ema_gap_min
            and macd_gap > macd_gap_min
            and float(row["volume"]) > float(row["volume_sma20"]) * volume_ratio_min
        ):
            final_target = float(close * 1.025)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=(
                    "Momentum STRICT: EMA9>EMA21, close>EMA50, RSI 55-68, volume>SMA20x1.15 e MACD/gap fortes"
                    if strict
                    else "Momentum refinado: EMA9>EMA21, close>EMA50, RSI 55-70, volume>SMA20x1.05 e MACD/gap confirmados"
                ),
                reference_entry_price=close,
                stop_price=float(close * 0.98),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
            )
        return None

    if normalized in {"grid", "grid-strict"}:
        strict = normalized.endswith("strict")
        entry_std = 2.4 if strict else 2.2
        rsi_threshold = 28 if strict else 30
        threshold = row["sma50"] - (entry_std * row["std50"])
        if row["close"] < threshold and float(row["rsi14"]) < rsi_threshold:
            close = float(row["close"])
            final_target = float(close * 1.02)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=(
                    "Grid STRICT: close abaixo de SMA50 - 2.4 desvios e RSI<28"
                    if strict
                    else "Grid refinado: close abaixo de SMA50 - 2.2 desvios e RSI<30"
                ),
                reference_entry_price=close,
                stop_price=float(close * (0.97 if strict else 0.965)),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=80,
            )
        return None

    if normalized == "delta-neutral":
        if len(df) < 2:
            return None
        prev_close = float(df.iloc[-2]["close"])
        curr_close = float(row["close"])
        move = (curr_close - prev_close) / prev_close if prev_close else 0.0
        min_move = float(setup_context.get("min_move_pct") or 0.003)
        if abs(move) > min_move:
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long" if move > 0 else "short",
                reason=f"delta-neutral refinado: variacao de candle {move * 100:.2f}% acima de {min_move * 100:.2f}%",
                reference_entry_price=curr_close,
                close_after_bars=1,
            )
        return None

    if normalized in {"institutional-strict", "institutional-strict-4h"}:
        strict = normalized.endswith("strict")
        close = float(row["close"])
        rsi_min, rsi_max = (52.0, 65.0) if strict else (50.0, 70.0)
        volume_ratio_min = 1.15 if strict else 1.05
        ema_gap = (float(row["ema9"]) - float(row["ema21"])) / close if close > 0 else 0.0
        macd_gap = (float(row["macd"]) - float(row["macd_signal"])) / close if close > 0 else 0.0
        macd_gap_min = 0.002 if strict else 0.001
        macd_gap_max = 0.005 if strict else float("inf")
        quality_ok = (
            row["ema9"] > row["ema21"]
            and close > float(row["ema50"])
            and rsi_min < float(row["rsi"]) < rsi_max
            and float(row["volume"]) > float(row["volume_sma20"]) * volume_ratio_min
            and macd_gap_min < macd_gap < macd_gap_max
            and (not strict or ema_gap > 0.001)
        )
        if quality_ok:
            stop_price = float(close * 0.98)
            if strict:
                targets, weights = _build_r_multiple_ladder(close, stop_price, "long")
                final_target = float(targets[-1]) if targets else float(close * 1.06)
            else:
                final_target = float(close * 1.025)
                targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=(
                    "Institutional STRICT: EMA9>EMA21, close>EMA50, RSI 52-65, volume>SMA20x1.15, EMA gap>0.10%, MACD gap 0.20%-0.50% e alvos 1R/1.5R/2R/3R"
                    if strict
                    else "Institutional refinado: EMA9>EMA21, close>EMA50, RSI 50-70, volume>SMA20x1.05 e MACD gap>0.10%"
                ),
                reference_entry_price=close,
                stop_price=stop_price,
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=8 if strict else 0,
            )
        return None

    if normalized == "hybrid":
        resolved_profile = normalize_hybrid_profile(hybrid_profile)
        atr = float(row["atr14"])
        close = float(row["close"])
        if (
            row["rsi14"] < 32
            and row["stoch_k"] < 25
            and row["volume"] > row["volume_sma20"] * 1.2
            and row["close"] > row["ema50"]
        ):
            sl_mult = 1.0 if resolved_profile != "degen" else 1.2
            tp_mult = {"conservative": 2.0, "moderate": 2.5, "degen": 3.0}[resolved_profile]
            final_target = float(close + atr * tp_mult)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=f"HYBRID LONG confirmado ({resolved_profile})",
                reference_entry_price=close,
                stop_price=float(close - atr * sl_mult),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
            )
        if (
            row["rsi14"] > 68
            and row["stoch_k"] > 75
            and row["volume"] > row["volume_sma20"] * 1.2
            and row["close"] < row["ema50"]
        ):
            sl_mult = 1.0 if resolved_profile != "degen" else 1.2
            tp_mult = {"conservative": 2.0, "moderate": 2.5, "degen": 3.0}[resolved_profile]
            final_target = float(close - atr * tp_mult)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="short",
                reason=f"HYBRID SHORT confirmado ({resolved_profile})",
                reference_entry_price=close,
                stop_price=float(close + atr * sl_mult),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
            )
        return None

    if normalized == "hybrid-15m":
        resolved_profile = normalize_hybrid_profile(hybrid_profile)
        stop_loss_atr_mult, take_profit_atr_mult, max_bars = _hybrid_15m_profile_params(resolved_profile)
        atr = float(row["atr14"])
        close = float(row["close"])
        if _hybrid_15m_long_signal(df, len(df) - 1):
            final_target = float(close + atr * take_profit_atr_mult)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=f"HYBRID 15m LONG confirmado ({resolved_profile}) em compressao/POL",
                reference_entry_price=close,
                stop_price=float(close - atr * stop_loss_atr_mult),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=max_bars,
            )
        if _hybrid_15m_short_signal(df, len(df) - 1):
            final_target = float(close - atr * take_profit_atr_mult)
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="short",
                reason=f"HYBRID 15m SHORT confirmado ({resolved_profile}) em compressao/POL",
                reference_entry_price=close,
                stop_price=float(close + atr * stop_loss_atr_mult),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=max_bars,
            )
        return None

    if normalized == "bollinger-mean-reversion":
        close = float(row["close"])
        atr = float(row.get("atr14", 0.0) or 0.0)
        strict = normalized.endswith("strict")
        volume_ratio = float(row.get("volume_ratio", 0.0) or 0.0)
        volume_ratio_min = 1.20 if strict else 1.05
        quality_ok = atr > 0 and volume_ratio >= volume_ratio_min
        long_ok = quality_ok and close <= float(row["bb_lower"]) - (0.20 * atr) and float(row["rsi14"]) < 35
        short_ok = quality_ok and close >= float(row["bb_upper"]) + (0.20 * atr) and float(row["rsi14"]) > 72
        if long_ok:
            final_target = float(min(close * 1.02, float(row["bb_middle"])))
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="long",
                reason=(
                    "Bollinger STRICT LONG: close<=bb_lower-0.20ATR, RSI<35 e volume>SMA20x1.20"
                    if strict
                    else "Bollinger LONG refinado: close<=bb_lower-0.20ATR, RSI<35 e volume>SMA20x1.05"
                ),
                reference_entry_price=close,
                stop_price=float(close * 0.985),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=16,
            )
        if short_ok:
            final_target = float(max(close * 0.98, float(row["bb_middle"])))
            targets, weights = _build_three_target_ladder(close, final_target)
            return SetupRuntimeSignal(
                setup_key=normalized,
                timeframe=timeframe,
                action="enter",
                side="short",
                reason=(
                    "Bollinger STRICT SHORT: close>=bb_upper+0.20ATR, RSI>72 e volume>SMA20x1.20"
                    if strict
                    else "Bollinger SHORT refinado: close>=bb_upper+0.20ATR, RSI>72 e volume>SMA20x1.05"
                ),
                reference_entry_price=close,
                stop_price=float(close * 1.015),
                take_profit=final_target,
                take_profit_targets=targets,
                target_weights=weights,
                close_after_bars=16,
            )
        return None

    if normalized == "low-stoch-storm":
        return _low_stoch_storm_4h_signal(df, timeframe)

    if normalized in {"divergence-and-volume-15m", "divergence-and-volume-1h", "divergence-and-volume-4h"}:
        config = get_divergence_volume_config(timeframe=timeframe)
        signal = calculate_divergence_volume_signal(df, config=config)
        if signal is None:
            return None
        targets = [float(target) for target in signal["target_prices"]]
        weights = [float(weight) for weight in signal["target_weights"]]
        return SetupRuntimeSignal(
            setup_key=normalized,
            timeframe=timeframe,
            action="enter",
            side=str(signal["side"]),
            reason=f"Divergence and Volume {timeframe} {signal['divergence_type']} {signal['pattern_type']} | fib={float(signal['fibonacci_level']):.3f} | vol={float(signal['volume_ratio']):.2f}x",
            reference_entry_price=float(signal["entry_price"]),
            stop_price=float(signal["stop_price"]),
            take_profit=float(signal["take_profit"]),
            take_profit_targets=targets,
            target_weights=weights,
            close_after_bars=config.max_hold_bars,
            metadata={
                "pattern_type": str(signal["pattern_type"]),
                "divergence_type": str(signal["divergence_type"]),
                "risk_reward": float(signal["risk_reward"]),
                "invalidation_price": float(signal["invalidation_price"]),
                "fibonacci_level": float(signal["fibonacci_level"]),
                "fibonacci_price": float(signal["fibonacci_price"]),
                "fibonacci_orientation": str(signal["fibonacci_orientation"]),
                "volume_ratio": float(signal["volume_ratio"]),
                "first_pivot_price": float(signal["first_pivot_price"]),
                "second_pivot_price": float(signal["second_pivot_price"]),
                "first_pivot_rsi": float(signal["first_pivot_rsi"]),
                "second_pivot_rsi": float(signal["second_pivot_rsi"]),
            },
        )

    if False:
        signal = calculate_triangle_breakout_signal(df, config=get_triangle_breakout_config())
        if signal is None:
            return None
        return SetupRuntimeSignal(
            setup_key=normalized,
            timeframe=timeframe,
            action="enter",
            side=str(signal["side"]),
            reason=f"Triangle {signal['pattern_type']} breakout",
            reference_entry_price=float(row["close"]),
            stop_price=float(signal["stop_price"]),
            take_profit=float(signal["target_price"]),
            take_profit_targets=_build_three_target_ladder(float(row["close"]), float(signal["target_price"]))[0],
            target_weights=_build_three_target_ladder(float(row["close"]), float(signal["target_price"]))[1],
            metadata={
                "pattern_type": signal["pattern_type"],
                "upper_bound": float(signal["upper_bound"]),
                "lower_bound": float(signal["lower_bound"]),
                "pattern_height": float(signal["pattern_height"]),
            },
        )

    if normalized == "funding-arb":
        config = get_funding_arb_config()
        funding_rate = float(setup_context.get("funding_rate") or 0.0)
        threshold = float(setup_context.get("funding_threshold") or config.min_rate)
        if abs(funding_rate) < threshold:
            return None
        spread_bps = float(setup_context.get("spread_bps") or 0.0)
        max_spread_bps = float(setup_context.get("max_spread_bps") or config.max_spread_bps)
        if abs(spread_bps) > max_spread_bps:
            return None
        max_hold_hours = int(setup_context.get("max_hold_hours") or config.max_hold_hours)
        max_hold_intervals = max(1, max_hold_hours // 8)
        min_expected_carry_pct = float(setup_context.get("min_expected_carry_pct") or 0.15)
        expected_carry_pct = abs(funding_rate) * 100 * max_hold_intervals
        if expected_carry_pct < min_expected_carry_pct:
            return None
        return SetupRuntimeSignal(
            setup_key=normalized,
            timeframe=timeframe,
            action="enter",
            side="long" if funding_rate > 0 else "short",
            reason=f"Funding arb refinado | funding={funding_rate * 100:.4f}%/8h | spread={spread_bps:.2f}bps | carry_exp={expected_carry_pct:.3f}%",
            metadata={
                "entry_funding_rate": funding_rate,
                "funding_threshold": threshold,
                "neutral_exit_rate": float(setup_context.get("neutral_exit_rate") or config.exit_rate),
                "max_hold_hours": max_hold_hours,
                "max_spread_bps": max_spread_bps,
                "entry_spread_bps": spread_bps,
                "min_expected_carry_pct": min_expected_carry_pct,
                "expected_carry_pct": expected_carry_pct,
            },
        )

    raise ValueError(f"setup live nao suportado: {setup_key}")


def evaluate_setup_exit(
    state: ManagedSetupState,
    df: pd.DataFrame,
    *,
    live_price: float,
    setup_context: dict[str, Any] | None = None,
) -> SetupRuntimeSignal | None:
    normalized = normalize_setup_key(state.setup_key)
    if df.empty:
        return None
    row = df.iloc[-1]
    side = state.side
    entry_price = state.reference_entry_price or state.pair_state.kraken_entry or state.pair_state.nado_entry
    opened_bar = pd.Timestamp(state.opened_bar_at) if state.opened_bar_at else None
    bars_open = int((df["timestamp"] > opened_bar).sum()) if opened_bar is not None else 0
    setup_context = setup_context or {}
    if bool((state.metadata or {}).get("tracking_only")):
        stop_or_target = _check_setup_stop_and_targets(
            state,
            live_price=live_price,
            stop_reason=f"{normalized} stop loss",
        )
        if stop_or_target is not None:
            return stop_or_target

    if False:
        return _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Momentum stop loss")

    if normalized in {"grid", "grid-strict"}:
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Grid stop loss")
        if stop_or_target is not None:
            return stop_or_target
        if row["close"] > row["sma50"]:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Grid retorno a SMA50")
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Grid timeout")
        return None

    if normalized == "delta-neutral":
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="janela de 1 candle concluida")
        return None

    if normalized == "institutional-strict":
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Institutional stop loss")
        if stop_or_target is not None:
            return stop_or_target
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Institutional timeout")
        return None

    if normalized == "hybrid":
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="HYBRID stop loss")
        if stop_or_target is not None:
            return stop_or_target
        if side == "long":
            if row["rsi14"] > 60 or row["stoch_k"] > 80:
                return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="HYBRID saida manual RSI/Stoch")
            return None
        if row["rsi14"] < 40 or row["stoch_k"] < 20:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="HYBRID saida manual RSI/Stoch")
        return None

    if normalized == "hybrid-15m":
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="HYBRID 15m stop loss")
        if stop_or_target is not None:
            return stop_or_target
        if side == "long":
            if row["rsi14"] > 58 or row["stoch_k"] > 78:
                return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="HYBRID 15m saida manual RSI/Stoch")
        else:
            if row["rsi14"] < 42 or row["stoch_k"] < 22:
                return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="HYBRID 15m saida manual RSI/Stoch")
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="HYBRID 15m timeout")
        return None

    if normalized == "bollinger-mean-reversion":
        hit_mid = (side == "long" and float(row["close"]) >= float(row["bb_middle"])) or (
            side == "short" and float(row["close"]) <= float(row["bb_middle"])
        )
        if hit_mid:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Bollinger retorno a bb_mid")
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Bollinger stop 1.5%")
        if stop_or_target is not None:
            return stop_or_target
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Bollinger timeout 16 barras")
        return None

    if normalized == "low-stoch-storm":
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Low Stoch Storm stop loss")
        if stop_or_target is not None:
            return stop_or_target
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Low Stoch Storm timeout 80 candles 4h")
        return None

    if normalized in {"divergence-and-volume-15m", "divergence-and-volume-1h", "divergence-and-volume-4h"}:
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Divergence and Volume stop loss")
        if stop_or_target is not None:
            return stop_or_target
        invalidation_price = float((state.metadata or {}).get("invalidation_price") or 0.0)
        if invalidation_price > 0:
            close = float(row["close"])
            if side == "long" and close <= invalidation_price:
                return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Divergence and Volume invalidacao por fechamento")
            if side == "short" and close >= invalidation_price:
                return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Divergence and Volume invalidacao por fechamento")
        if state.close_after_bars and bars_open >= state.close_after_bars:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Divergence and Volume timeout")
        return None

    if False:
        upper_bound = float(state.metadata.get("upper_bound", 0.0))
        lower_bound = float(state.metadata.get("lower_bound", 0.0))
        prev_close = float(df.iloc[-2]["close"]) if len(df) >= 2 else float(row["close"])
        current_close = float(row["close"])
        inside_prev = lower_bound <= prev_close <= upper_bound if upper_bound > lower_bound else False
        inside_curr = lower_bound <= current_close <= upper_bound if upper_bound > lower_bound else False
        if inside_prev and inside_curr:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Triangle reentrada no padrao")
        stop_or_target = _check_setup_stop_and_targets(state, live_price=live_price, stop_reason="Triangle stop/invalidation")
        if stop_or_target is not None:
            return stop_or_target
        return None

    if normalized == "funding-arb":
        config = get_funding_arb_config()
        metadata = state.metadata or {}
        current_rate = float(setup_context.get("funding_rate") or 0.0)
        neutral_exit_rate = float(metadata.get("neutral_exit_rate") or config.exit_rate)
        max_hold_hours = int(metadata.get("max_hold_hours") or config.max_hold_hours)
        max_spread_bps = float(metadata.get("max_spread_bps") or config.max_spread_bps)
        current_spread_bps = abs(float(setup_context.get("spread_bps") or 0.0))
        hours_open = max(0.0, (float(setup_context.get("now_ts") or 0.0) - state.opened_at_ts) / 3600.0) if state.opened_at_ts else 0.0
        if abs(current_rate) <= neutral_exit_rate:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Funding voltou para faixa neutra")
        expected_positive = side == "long"
        if (expected_positive and current_rate < 0) or ((not expected_positive) and current_rate > 0):
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Funding virou contra a direcao do carry")
        if current_spread_bps >= max_spread_bps:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Spread perdeu atratividade")
        if max_hold_hours > 0 and hours_open >= max_hold_hours:
            return SetupRuntimeSignal(normalized, state.timeframe, "exit", side=side, reason="Funding arb max hold atingido")
        return None

    raise ValueError(f"setup live nao suportado: {state.setup_key}")


def _directional_pnl_pct(side: str, entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if side == "long":
        return (current_price - entry_price) / entry_price
    return (entry_price - current_price) / entry_price


def state_symbol_keys(states: Sequence[ManagedSetupState]) -> set[str]:
    return {state.symbol for state in states}
