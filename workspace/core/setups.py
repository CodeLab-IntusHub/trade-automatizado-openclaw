from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import product
import logging
import math
from typing import TYPE_CHECKING, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # evita import circular em runtime
    from workspace.config import Settings


@dataclass(frozen=True)
class SetupDefinition:
    key: str
    label: str
    description: str
    entry_rule: str
    exit_rule: str
    profile: str
    timeframe: str = "1h"


@dataclass(frozen=True)
class SetupExecutionConfig:
    execution_mode: str = ""
    allowed_execution_modes: tuple[str, ...] = ("hedged",)
    nado_margin_mode: str = "cross"
    kraken_margin_mode: str = "cross"
    leverage_by_profile: dict[str, float] = None
    liquidation_buffer_pct_min: float = 10.0
    stop_model: str = ""
    tp_model: str = ""
    kraken_leverage: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def leverage_for_profile(self, profile: str | None) -> float:
        leverage_map = self.leverage_by_profile or DEFAULT_RISK_PROFILE_LEVERAGE
        normalized = normalize_hybrid_profile(profile)
        return float(leverage_map.get(normalized, leverage_map[DEFAULT_HYBRID_PROFILE]))


@dataclass(frozen=True)
class BacktestResult:
    key: str
    setup: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    profit_factor: float
    sharpe_ratio: float
    best_trade: float
    worst_trade: float
    max_drawdown: float
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HybridProfileDefinition:
    key: str
    label: str
    position_fraction: float
    stop_loss_atr_mult: float
    take_profit_atr_mult: float
    daily_loss_limit_pct: float
    monthly_loss_limit_pct: float
    max_open_positions: int


@dataclass(frozen=True)
class TriangleBreakoutConfig:
    pivot_window: int
    contraction_max_ratio: float
    volume_multiplier: float
    breakout_buffer_atr_mult: float
    flat_threshold_atr_mult: float
    slope_threshold_atr_mult: float
    stop_atr_mult: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FundingArbConfig:
    min_rate: float
    exit_rate: float
    max_hold_intervals: int
    max_spread_bps: float

    @property
    def max_hold_hours(self) -> int:
        return self.max_hold_intervals * 8

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["max_hold_hours"] = self.max_hold_hours
        return payload


@dataclass(frozen=True)
class DivergenceVolumeConfig:
    rsi_period: int = 14
    volume_avg_period: int = 20
    volume_factor: float = 1.0
    fibonacci_tolerance_pct: float = 0.0
    divergence_lookback: int = 32
    fibonacci_lookback: int = 120
    min_gap: int = 3
    rsi_delta: float = 1.5
    fibonacci_tolerance_atr: float = 0.75
    atr_buffer: float = 0.005
    fibonacci_levels: tuple[float, ...] = (1.0, 1.618, 2.0, 2.618)
    target_levels: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5)
    target_weights: tuple[float, ...] = (0.25, 0.25, 0.25, 0.25)
    min_reward_risk: float = 1.0
    max_hold_bars: int = 36

    def __post_init__(self) -> None:
        """Escada de alvos coerente e invariante do tipo, nao da fabrica.

        Estes campos decidem onde o capital sai da posicao. Validar so no
        caminho do settings deixava duas respostas para o mesmo estado
        invalido: fatal vindo do arquivo, e silenciosamente reparado para pesos
        iguais vindo do construtor -- inclusive por um `config=` explicito.
        """
        if not self.target_levels:
            raise ValueError("target_levels vazio: um setup precisa de pelo menos um alvo")
        if len(self.target_levels) != len(self.target_weights):
            raise ValueError(
                f"target_weights tem {len(self.target_weights)} itens para "
                f"{len(self.target_levels)} alvos em target_levels -- precisam casar"
            )
        if sum(float(weight) for weight in self.target_weights) <= 0:
            raise ValueError("target_weights precisa ter soma positiva para distribuir a saida")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CalibrationCandidateResult:
    candidate_key: str
    config: dict
    eligible: bool
    rejection_reason: str
    median_sharpe_ratio: float
    median_total_pnl: float
    median_max_drawdown: float
    median_total_trades: float
    trade_qualified_symbols: int
    successful_symbols: int
    per_symbol: Dict[str, BacktestResult]
    errors: Dict[str, str]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["per_symbol"] = {key: value.to_dict() for key, value in self.per_symbol.items()}
        return payload


@dataclass
class _HybridPosition:
    side: str
    entry_price: float
    entry_time: pd.Timestamp
    entry_index: int
    position_size_usd: float
    equity_snapshot: float
    stop_loss: float
    take_profit: float


@dataclass
class _HybridRiskState:
    initial_equity: float = 10_000.0
    current_equity: float = 10_000.0
    position_fraction: float = 0.02
    stop_loss_atr_mult: float = 1.0
    take_profit_atr_mult: float = 2.5
    fee_rate: float = 0.002
    daily_loss_limit_pct: float = 0.10
    monthly_loss_limit_pct: float = 0.20
    max_open_positions: int = 2
    daily_pnl_usd: float = 0.0
    monthly_pnl_usd: float = 0.0
    consecutive_losses: int = 0
    cooldown_bars_remaining: int = 0
    current_day: object | None = None
    current_month: tuple[int, int] | None = None

    def sync_periods(self, timestamp: pd.Timestamp) -> None:
        day = timestamp.date()
        month = (timestamp.year, timestamp.month)
        if self.current_day != day:
            self.daily_pnl_usd = 0.0
            self.current_day = day
        if self.current_month != month:
            self.monthly_pnl_usd = 0.0
            self.current_month = month

    def can_open(self, open_positions: int) -> bool:
        if open_positions >= self.max_open_positions:
            return False
        if self.daily_pnl_usd <= -(self.initial_equity * self.daily_loss_limit_pct):
            return False
        if self.monthly_pnl_usd <= -(self.initial_equity * self.monthly_loss_limit_pct):
            return False
        if self.cooldown_bars_remaining > 0:
            return False
        return True

    def position_size(self) -> float:
        return max(self.current_equity * self.position_fraction, 0.0)

    def register_close(self, net_pnl_usd: float) -> bool:
        self.current_equity += net_pnl_usd
        self.daily_pnl_usd += net_pnl_usd
        self.monthly_pnl_usd += net_pnl_usd

        if net_pnl_usd < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= 2:
                self.cooldown_bars_remaining = 2
                self.consecutive_losses = 0
                return True
        else:
            self.consecutive_losses = 0
        return False

    def consume_cooldown_bar(self) -> None:
        if self.cooldown_bars_remaining > 0:
            self.cooldown_bars_remaining -= 1


SETUP_CATALOG: Dict[str, SetupDefinition] = {
    "grid": SetupDefinition(
        key="grid",
        label="Grid Strategy",
        description="Compra em excesso estatistico abaixo da media com RSI baixo, stop e timeout.",
        entry_rule="Close abaixo de SMA50 - 2.2 desvios e RSI<30.",
        exit_rule="Sai no retorno a SMA50, TP 2%, SL 3.5% ou timeout.",
        profile="mean-reversion",
        timeframe="1h",
    ),
    "grid-strict": SetupDefinition(
        key="grid-strict",
        label="Grid Strict",
        description="Grid/mean reversion 1h calibrado para quedas mais extremas e RSI baixo.",
        entry_rule="Close abaixo de SMA50 - 2.4 desvios e RSI<28.",
        exit_rule="Sai no retorno a SMA50, TP 2%, SL 3.0% ou timeout.",
        profile="mean-reversion-strict",
        timeframe="1h",
    ),
    "delta-neutral": SetupDefinition(
        key="delta-neutral",
        label="Delta-Neutral Strategy",
        description="Setup delta-neutro dependente de spread real entre venues; nao deve ser validado por serie sintetica single-leg.",
        entry_rule="Exige edge/spread real informado pela execucao live ou contexto da venue.",
        exit_rule="Fecha por normalizacao do spread real, limite de tempo ou guardrail operacional.",
        profile="market-neutral",
        timeframe="1h",
    ),
    "institutional-strict": SetupDefinition(
        key="institutional-strict",
        label="Institutional Strict",
        description="Institucional 1h calibrado com tendencia EMA50, volume, janela RSI mais estreita e MACD forte.",
        entry_rule="EMA9>EMA21, close>EMA50, RSI 52-65, volume>SMA20x1.15, EMA gap > 0.10% e MACD gap entre 0.20% e 0.50%.",
        exit_rule="Alvos parciais em 1R, 1.5R, 2R e 2.5R, stop loss de 2.0% ou timeout de 8 candles.",
        profile="balanced-trend-strict",
        timeframe="1h",
    ),
    "institutional-strict-4h": SetupDefinition(
        key="institutional-strict-4h",
        label="Institutional Strict 4H",
        description="Institucional 4h calibrado com tendencia EMA50, volume, janela RSI mais estreita e MACD forte.",
        entry_rule="EMA9>EMA21, close>EMA50, RSI 52-65, volume>SMA20x1.15, EMA gap > 0.10% e MACD gap entre 0.20% e 0.50%.",
        exit_rule="Alvos parciais em 1R, 1.5R, 2R e 3R, stop loss de 2.0% ou timeout de 8 candles 4h.",
        profile="balanced-trend-strict",
        timeframe="4h",
    ),
    "hybrid": SetupDefinition(
        key="hybrid",
        label="HYBRID Strategy",
        description="Setup 4h com RSI, Stoch, EMA50, ATR e gestao de risco por posicao.",
        entry_rule="LONG: RSI<32, Stoch<25, volume>SMA20x1.2 e close>EMA50 | SHORT: inverso.",
        exit_rule="SL ATRx1.0, TP ATRx2.5 e saida manual por RSI/Stoch.",
        profile="hybrid-mean-reversion",
        timeframe="4h",
    ),
    "hybrid-15m": SetupDefinition(
        key="hybrid-15m",
        label="HYBRID 15m Scalp",
        description="Scalp 15m com compressao, impulso, pullback na regiao de liquidez/POL e confirmacao por EMA9/EMA21, MACD, RSI, Stoch e ATR.",
        entry_rule=(
            "LONG: compressao + impulso + pullback na EMA21/POL, EMA9>EMA21, MACD>signal, RSI<45, Stoch<35 e volume>SMA20x1.05 | "
            "SHORT: inverso."
        ),
        exit_rule="Stop por ATR do setup, take profit fixo em 3R, saida manual por RSI/Stoch e timeout maximo por barras.",
        profile="hybrid-scalp",
        timeframe="15m",
    ),
    "bollinger-mean-reversion": SetupDefinition(
        key="bollinger-mean-reversion",
        label="Bollinger Mean Reversion",
        description="Reversao a media em 15m usando Bollinger Bands, RSI, deslocamento por ATR e volume.",
        entry_rule="LONG: close<=bb_lower-0.20ATR, RSI<35 e volume>SMA20x1.05 | SHORT: close>=bb_upper+0.20ATR, RSI>72 e volume>SMA20x1.05.",
        exit_rule="Alvo em bb_mid, SL fixo 1.5%, TP max 2.0% ou timeout de 16 barras.",
        profile="mean-reversion-intraday",
        timeframe="15m",
    ),
    "funding-arb": SetupDefinition(
        key="funding-arb",
        label="Funding Arbitrage",
        description="Bot ativo delta-neutro que entra quando o funding da Kraken sai da faixa neutra.",
        entry_rule="Funding suficientemente positivo/negativo em simbolos comuns abre par proprio hedgeado.",
        exit_rule="Sai por funding neutro, spread sem atratividade, max hold ou stop global do par.",
        profile="carry-market-neutral",
        timeframe="1h",
    ),
    "low-stoch-storm": SetupDefinition(
        key="low-stoch-storm",
        label="Low Stoch Storm",
        description="Setup 4h de reversao/continuacao apos estocastico sair de zona extrema, com suporte/resistencia em EMAs e filtro de tendencia/risco.",
        entry_rule="LONG/SHORT 4h: Stoch sai de zona extrema, preco recupera/perde EMA8 ou rompe estrutura, filtro EMA80/RSI e risco <=6%.",
        exit_rule="TPs em 1R, 1.5R, 2R e 3R; stop pela estrutura/ATR; timeout de 80 candles 4h.",
        profile="low-stoch-storm",
        timeframe="4h",
    ),
    "divergence-and-volume-15m": SetupDefinition(
        key="divergence-and-volume-15m",
        label="Divergence and Volume 15m",
        description="Setup experimental de reversao 15m por divergencia RSI, volume, zona Fibonacci e candle de reversao.",
        entry_rule="LONG/SHORT 15m: divergencia RSI + volume>SMA + Fibonacci + padrao hammer/engulfing/shooting star.",
        exit_rule="Stop por extremidade/estrutura, alvos 1R/1.5R/2R/2.5R no live e timeout de 48 candles 15m.",
        profile="divergence-volume-experimental",
        timeframe="15m",
    ),
    "divergence-and-volume-1h": SetupDefinition(
        key="divergence-and-volume-1h",
        label="Divergence and Volume 1h",
        description="Setup experimental de reversao 1h por divergencia RSI, volume, zona Fibonacci e candle de reversao.",
        entry_rule="LONG/SHORT 1h: divergencia RSI + volume>SMA + Fibonacci + padrao hammer/engulfing/shooting star.",
        exit_rule="Stop por extremidade/estrutura, alvos 1R/1.5R/2R/2.5R no live e timeout de 36 candles 1h.",
        profile="divergence-volume-experimental",
        timeframe="1h",
    ),
    "divergence-and-volume-4h": SetupDefinition(
        key="divergence-and-volume-4h",
        label="Divergence and Volume 4h",
        description="Setup experimental de reversao 4h por divergencia RSI, volume, zona Fibonacci e candle de reversao.",
        entry_rule="LONG/SHORT 4h: divergencia RSI + volume>SMA + Fibonacci + padrao hammer/engulfing/shooting star.",
        exit_rule="Stop por extremidade/estrutura, alvos 1R/1.5R/2R/2.5R no live e timeout de 24 candles 4h.",
        profile="divergence-volume-experimental",
        timeframe="4h",
    ),
    "divergence-and-volume": SetupDefinition(
        key="divergence-and-volume",
        label="Divergence and Volume",
        description="Alias operacional padrão da variante 1h do Divergence and Volume.",
        entry_rule="Alias para divergence-and-volume-1h.",
        exit_rule="Alias para divergence-and-volume-1h.",
        profile="divergence-volume-experimental",
        timeframe="1h",
    ),
}


TIMEFRAME_CONFIG = {
    "15m": {
        "freq": "15min",
        "candles_per_day": 96,
        "drift": 0.00005,
        "vol": 0.0075,
        "wick_sigma": 0.0040,
        "close_noise": 25.0,
    },
    "1h": {
        "freq": "1h",
        "candles_per_day": 24,
        "drift": 0.0002,
        "vol": 0.0150,
        "wick_sigma": 0.0080,
        "close_noise": 100.0,
    },
    "4h": {
        "freq": "4h",
        "candles_per_day": 6,
        "drift": 0.00065,
        "vol": 0.0280,
        "wick_sigma": 0.0140,
        "close_noise": 175.0,
    },
}

DEFAULT_CORE_LIQUID_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
DEFAULT_HYBRID_REAL_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"]
DEFAULT_HYBRID_PROFILE = "moderate"
DEFAULT_TRIANGLE_REAL_SYMBOLS = list(DEFAULT_CORE_LIQUID_SYMBOLS)
DEFAULT_TRIANGLE_REAL_DAYS = 180
DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS = ["ETH/USDT", "XMR/USDT"]
DEFAULT_DIVERGENCE_AND_VOLUME_REAL_DAYS = 120
DEFAULT_LOW_STOCH_REAL_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
DEFAULT_LOW_STOCH_REAL_DAYS = 120
DEFAULT_FUNDING_ARB_REAL_SYMBOLS = list(DEFAULT_CORE_LIQUID_SYMBOLS)
DEFAULT_FUNDING_ARB_REAL_DAYS = 120
DEFAULT_SCALP_KRAKEN_LEVERAGE = 5.0
DEFAULT_SCALP_KRAKEN_MARGIN_MODE = "cross"
EXECUTION_MODE_HEDGED = "hedged"
EXECUTION_MODE_NADO_ONLY = "nado_only"
EXECUTION_MODE_KRAKEN_ONLY = "kraken_only"
MARGIN_MODE_CROSS = "cross"
MARGIN_MODE_ISOLATED = "isolated"
DIRECTIONAL_SETUP_KEYS = {
    "grid-strict",
    "institutional-strict",
    "bollinger-mean-reversion",
    "low-stoch-storm",
    "divergence-and-volume",
    "divergence-and-volume-15m",
    "divergence-and-volume-1h",
    "divergence-and-volume-4h",
}
HEDGED_ONLY_SETUP_KEYS = {"delta-neutral", "funding-arb"}
DEPRECATED_SETUP_KEYS = {"grid", "hybrid", "hybrid-15m"}
ACTIVE_SETUP_KEYS = [
    "delta-neutral",
    "grid-strict",
    "institutional-strict",
    "bollinger-mean-reversion",
    "funding-arb",
    "low-stoch-storm",
    "divergence-and-volume-15m",
    "divergence-and-volume-1h",
    "divergence-and-volume-4h",
]
DEFAULT_RISK_PROFILE_LEVERAGE: Dict[str, float] = {
    "conservative": 1.0,
    "moderate": 5.0,
    "degen": 10.0,
}
TRIANGLE_BREAKOUT_DEFAULT_CONFIG = TriangleBreakoutConfig(
    pivot_window=2,
    contraction_max_ratio=0.80,
    volume_multiplier=2.0,
    breakout_buffer_atr_mult=0.50,
    flat_threshold_atr_mult=0.05,
    slope_threshold_atr_mult=0.02,
    stop_atr_mult=0.8,
)
FUNDING_ARB_DEFAULT_CONFIG = FundingArbConfig(
    min_rate=0.00030,
    exit_rate=0.00002,
    max_hold_intervals=9,
    max_spread_bps=20.0,
)
DIVERGENCE_AND_VOLUME_DEFAULT_CONFIG = DivergenceVolumeConfig()
DIVERGENCE_AND_VOLUME_CONFIGS: dict[str, DivergenceVolumeConfig] = {
    "15m": DivergenceVolumeConfig(divergence_lookback=32, fibonacci_lookback=160, min_gap=3, rsi_delta=1.5, fibonacci_tolerance_atr=0.75, atr_buffer=0.005, max_hold_bars=48),
    "1h": DivergenceVolumeConfig(divergence_lookback=32, fibonacci_lookback=120, min_gap=3, rsi_delta=1.5, fibonacci_tolerance_atr=0.75, atr_buffer=0.005, max_hold_bars=36),
    "4h": DivergenceVolumeConfig(divergence_lookback=28, fibonacci_lookback=90, min_gap=3, rsi_delta=2.0, fibonacci_tolerance_atr=0.75, atr_buffer=0.005, max_hold_bars=24),
}
DEFAULT_FUNDING_ARB_MIN_RATE = FUNDING_ARB_DEFAULT_CONFIG.min_rate
DEFAULT_FUNDING_ARB_EXIT_RATE = FUNDING_ARB_DEFAULT_CONFIG.exit_rate
DEFAULT_FUNDING_ARB_MAX_HOLD_INTERVALS = FUNDING_ARB_DEFAULT_CONFIG.max_hold_intervals
DEFAULT_FUNDING_ARB_MAX_SPREAD_BPS = FUNDING_ARB_DEFAULT_CONFIG.max_spread_bps
HYBRID_PROFILE_MAP: Dict[str, HybridProfileDefinition] = {
    "conservative": HybridProfileDefinition(
        key="conservative",
        label="Conservador",
        position_fraction=0.01,
        stop_loss_atr_mult=1.0,
        take_profit_atr_mult=2.0,
        daily_loss_limit_pct=0.05,
        monthly_loss_limit_pct=0.10,
        max_open_positions=1,
    ),
    "moderate": HybridProfileDefinition(
        key="moderate",
        label="Moderado",
        position_fraction=0.02,
        stop_loss_atr_mult=1.0,
        take_profit_atr_mult=2.5,
        daily_loss_limit_pct=0.10,
        monthly_loss_limit_pct=0.20,
        max_open_positions=2,
    ),
    "degen": HybridProfileDefinition(
        key="degen",
        label="Degen",
        position_fraction=0.04,
        stop_loss_atr_mult=1.2,
        take_profit_atr_mult=3.0,
        daily_loss_limit_pct=0.15,
        monthly_loss_limit_pct=0.30,
        max_open_positions=3,
    ),
}

_DIRECTIONAL_MODES = (EXECUTION_MODE_HEDGED, EXECUTION_MODE_KRAKEN_ONLY, EXECUTION_MODE_NADO_ONLY)


def _profile_leverage_map(default: float | None = None) -> dict[str, float]:
    if default is None:
        return dict(DEFAULT_RISK_PROFILE_LEVERAGE)
    return {key: float(default) for key in DEFAULT_RISK_PROFILE_LEVERAGE}


SETUP_EXECUTION_DEFAULTS: Dict[str, SetupExecutionConfig] = {
    "delta-neutral": SetupExecutionConfig(
        execution_mode=EXECUTION_MODE_HEDGED,
        allowed_execution_modes=(EXECUTION_MODE_HEDGED,),
        nado_margin_mode=MARGIN_MODE_CROSS,
        kraken_margin_mode=MARGIN_MODE_CROSS,
        leverage_by_profile=dict(DEFAULT_RISK_PROFILE_LEVERAGE),
        liquidation_buffer_pct_min=10.0,
        stop_model="pair",
        tp_model="pair",
    ),
    "funding-arb": SetupExecutionConfig(
        execution_mode=EXECUTION_MODE_HEDGED,
        allowed_execution_modes=(EXECUTION_MODE_HEDGED,),
        nado_margin_mode=MARGIN_MODE_CROSS,
        kraken_margin_mode=MARGIN_MODE_CROSS,
        leverage_by_profile=dict(DEFAULT_RISK_PROFILE_LEVERAGE),
        liquidation_buffer_pct_min=10.0,
        stop_model="funding",
        tp_model="funding",
    ),
    "hybrid-15m": SetupExecutionConfig(
        allowed_execution_modes=_DIRECTIONAL_MODES,
        nado_margin_mode=MARGIN_MODE_ISOLATED,
        kraken_margin_mode=DEFAULT_SCALP_KRAKEN_MARGIN_MODE,
        leverage_by_profile=dict(DEFAULT_RISK_PROFILE_LEVERAGE),
        liquidation_buffer_pct_min=20.0,
        stop_model="setup",
        tp_model="three-targets",
        kraken_leverage=DEFAULT_SCALP_KRAKEN_LEVERAGE,
    ),
    "bollinger-mean-reversion": SetupExecutionConfig(
        allowed_execution_modes=_DIRECTIONAL_MODES,
        nado_margin_mode=MARGIN_MODE_ISOLATED,
        kraken_margin_mode=DEFAULT_SCALP_KRAKEN_MARGIN_MODE,
        leverage_by_profile=dict(DEFAULT_RISK_PROFILE_LEVERAGE),
        liquidation_buffer_pct_min=20.0,
        stop_model="setup",
        tp_model="three-targets",
        kraken_leverage=DEFAULT_SCALP_KRAKEN_LEVERAGE,
    ),
}

for _setup_key in (
    "grid-strict",
    "institutional-strict",
    "institutional-strict-4h",
    "low-stoch-storm",
    "divergence-and-volume",
    "divergence-and-volume-15m",
    "divergence-and-volume-1h",
    "divergence-and-volume-4h",
):
    SETUP_EXECUTION_DEFAULTS.setdefault(
        _setup_key,
        SetupExecutionConfig(
            allowed_execution_modes=_DIRECTIONAL_MODES,
            nado_margin_mode=MARGIN_MODE_ISOLATED,
            kraken_margin_mode=MARGIN_MODE_CROSS,
            leverage_by_profile=dict(DEFAULT_RISK_PROFILE_LEVERAGE),
            liquidation_buffer_pct_min=15.0,
            stop_model="setup",
            tp_model="three-targets",
        ),
    )


def normalize_setup_key(raw: str) -> str:
    key = raw.strip().lower().replace("_", "-")
    aliases = {
        "delta": "delta-neutral",
        "delta_neutral": "delta-neutral",
        "grid_strict": "grid-strict",
        "institutional_strict": "institutional-strict",
        "institutional_strict_4h": "institutional-strict-4h",
        "institutional-strict-4h": "institutional-strict-4h",
        "institutional-4h": "institutional-strict-4h",
        "hybrid15": "hybrid-15m",
        "hybrid-15": "hybrid-15m",
        "hybrid-scalp": "hybrid-15m",
        "bollinger": "bollinger-mean-reversion",
        "bollinger-mean": "bollinger-mean-reversion",
        "funding": "funding-arb",
        "funding_arb": "funding-arb",
        "low-stoch": "low-stoch-storm",
        "low_stoch": "low-stoch-storm",
        "low-stoch-storm": "low-stoch-storm",
        "low_stoch_storm": "low-stoch-storm",
        "stoch-storm": "low-stoch-storm",
        "rsi-divergence": "divergence-and-volume-4h",
        "divergence-and-volume": "divergence-and-volume-1h",
        "divergence-volume": "divergence-and-volume-1h",
        "divergence_and_volume": "divergence-and-volume-1h",
        "volume-divergence": "divergence-and-volume-1h",
        "volume_divergence": "divergence-and-volume-1h",
        "divergence-and-volume-4h": "divergence-and-volume-4h",
        "divergence-and-volume-15m": "divergence-and-volume-15m",
        "divergence-and-volume-1h": "divergence-and-volume-1h",
    }
    return aliases.get(key, key)


def normalize_timeframe(raw: str | None) -> str:
    if raw is None:
        return "1h"
    key = raw.strip().lower()
    aliases = {
        "15": "15m",
        "15m": "15m",
        "15min": "15m",
        "15mins": "15m",
        "1h": "1h",
        "60": "1h",
        "60m": "1h",
        "60min": "1h",
        "1hr": "1h",
        "hour": "1h",
        "4h": "4h",
        "240": "4h",
        "240m": "4h",
        "240min": "4h",
        "4hr": "4h",
    }
    normalized = aliases.get(key)
    if normalized is None:
        raise ValueError(f"timeframe invalido: {raw}")
    return normalized


def normalize_hybrid_profile(raw: str | None) -> str:
    if raw is None:
        return DEFAULT_HYBRID_PROFILE
    key = raw.strip().lower().replace("_", "-")
    aliases = {
        "conservador": "conservative",
        "conservative": "conservative",
        "moderado": "moderate",
        "moderate": "moderate",
        "degen": "degen",
    }
    normalized = aliases.get(key)
    if normalized is None:
        raise ValueError(f"perfil hybrid invalido: {raw}")
    return normalized


def normalize_execution_mode(raw: str | None) -> str:
    if raw is None:
        return ""
    key = raw.strip().lower().replace("-", "_")
    aliases = {
        "hedged": EXECUTION_MODE_HEDGED,
        "hedge": EXECUTION_MODE_HEDGED,
        "espelhado": EXECUTION_MODE_HEDGED,
        "delta_neutral": EXECUTION_MODE_HEDGED,
        "delta_neutro": EXECUTION_MODE_HEDGED,
        "delta": EXECUTION_MODE_HEDGED,
        "protegido": EXECUTION_MODE_HEDGED,
        "nado": EXECUTION_MODE_NADO_ONLY,
        "dex": EXECUTION_MODE_NADO_ONLY,
        "dex_only": EXECUTION_MODE_NADO_ONLY,
        "dexonly": EXECUTION_MODE_NADO_ONLY,
        "somente_dex": EXECUTION_MODE_NADO_ONLY,
        "so_dex": EXECUTION_MODE_NADO_ONLY,
        "apenas_dex": EXECUTION_MODE_NADO_ONLY,
        "nado_dex": EXECUTION_MODE_NADO_ONLY,
        "nado_only": EXECUTION_MODE_NADO_ONLY,
        "nadoonly": EXECUTION_MODE_NADO_ONLY,
        "kraken": EXECUTION_MODE_KRAKEN_ONLY,
        "cex": EXECUTION_MODE_KRAKEN_ONLY,
        "cex_only": EXECUTION_MODE_KRAKEN_ONLY,
        "cexonly": EXECUTION_MODE_KRAKEN_ONLY,
        "somente_cex": EXECUTION_MODE_KRAKEN_ONLY,
        "so_cex": EXECUTION_MODE_KRAKEN_ONLY,
        "apenas_cex": EXECUTION_MODE_KRAKEN_ONLY,
        "kraken_cex": EXECUTION_MODE_KRAKEN_ONLY,
        "kraken_only": EXECUTION_MODE_KRAKEN_ONLY,
        "krakenonly": EXECUTION_MODE_KRAKEN_ONLY,
    }
    normalized = aliases.get(key)
    if normalized is None:
        raise ValueError(f"modo de execucao invalido: {raw}")
    return normalized


def normalize_margin_mode(raw: str | None) -> str:
    if raw is None or not raw.strip():
        return ""
    key = raw.strip().lower()
    if key not in {MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED}:
        raise ValueError(f"margin mode invalido: {raw}")
    return key


def is_directional_setup(raw_setup_key: str) -> bool:
    return normalize_setup_key(raw_setup_key) in DIRECTIONAL_SETUP_KEYS


def is_hedged_only_setup(raw_setup_key: str) -> bool:
    return normalize_setup_key(raw_setup_key) in HEDGED_ONLY_SETUP_KEYS


def get_setup_execution_config(raw_setup_key: str) -> SetupExecutionConfig:
    normalized = normalize_setup_key(raw_setup_key)
    return SETUP_EXECUTION_DEFAULTS.get(normalized, SetupExecutionConfig())


def _settings_for(settings: "Settings | None") -> "Settings":
    """Settings recebido, ou o carregado da raiz do projeto.

    Recebe por parametro para que teste e chamador possam injetar sem mexer em
    variavel de ambiente global.
    """
    from workspace.config import load_settings

    return load_settings() if settings is None else settings


def _setup_int(settings: "Settings", setup_key: str, field: str, env: str, default: int) -> int:
    return settings.get_int(f"setups.{setup_key}.{field}", env=env, default=default)


def _setup_float(settings: "Settings", setup_key: str, field: str, env: str, default: float) -> float:
    return settings.get_float(f"setups.{setup_key}.{field}", env=env, default=default)


def _setup_tuple(
    settings: "Settings",
    setup_key: str,
    field: str,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    """Lista numerica de setup (niveis e pesos de alvo).

    Estas nao tinham como ser ajustadas por meio nenhum -- vinham so do default
    do codigo, o que contraria "nenhum parametro de setup hardcoded".
    """
    from workspace.config import ConfigError

    dotted = f"setups.{setup_key}.{field}"
    raw = settings.get_list(dotted, default=list(default))
    try:
        return tuple(float(item) for item in raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"valor invalido para '{dotted}': {raw!r} nao e lista de numeros") from exc


TRIANGLE_BREAKOUT_SETUP_KEY = "triangle-breakout"


def divergence_volume_setup_key(timeframe: str | None) -> str:
    """Chave de settings do divergence, com e sem timeframe.

    Existe para que live e backtest resolvam a MESMA chave: os caminhos de
    backtest nao passavam timeframe e caiam na chave sem sufixo, entao
    validavam uma config diferente da que opera.
    """
    normalized = normalize_timeframe(timeframe) if timeframe else None
    return f"divergence-and-volume-{normalized}" if normalized else "divergence-and-volume"


def get_triangle_breakout_config(
    config: TriangleBreakoutConfig | None = None,
    *,
    settings: "Settings | None" = None,
) -> TriangleBreakoutConfig:
    if config is not None:
        return config
    cfg = _settings_for(settings)
    key = TRIANGLE_BREAKOUT_SETUP_KEY
    defaults = TRIANGLE_BREAKOUT_DEFAULT_CONFIG
    return TriangleBreakoutConfig(
        pivot_window=_setup_int(cfg, key, "pivot_window", "TRIANGLE_PIVOT_WINDOW", defaults.pivot_window),
        contraction_max_ratio=_setup_float(cfg, key, "contraction_max_ratio", "TRIANGLE_CONTRACTION_MAX_RATIO", defaults.contraction_max_ratio),
        volume_multiplier=_setup_float(cfg, key, "volume_multiplier", "TRIANGLE_VOLUME_MULTIPLIER", defaults.volume_multiplier),
        breakout_buffer_atr_mult=_setup_float(cfg, key, "breakout_buffer_atr_mult", "TRIANGLE_BREAKOUT_BUFFER_ATR_MULT", defaults.breakout_buffer_atr_mult),
        flat_threshold_atr_mult=_setup_float(cfg, key, "flat_threshold_atr_mult", "TRIANGLE_FLAT_THRESHOLD_ATR_MULT", defaults.flat_threshold_atr_mult),
        slope_threshold_atr_mult=_setup_float(cfg, key, "slope_threshold_atr_mult", "TRIANGLE_SLOPE_THRESHOLD_ATR_MULT", defaults.slope_threshold_atr_mult),
        stop_atr_mult=_setup_float(cfg, key, "stop_atr_mult", "TRIANGLE_STOP_ATR_MULT", defaults.stop_atr_mult),
    )


FUNDING_ARB_SETUP_KEY = "funding-arb"


def get_funding_arb_config(
    config: FundingArbConfig | None = None,
    *,
    settings: "Settings | None" = None,
) -> FundingArbConfig:
    if config is not None:
        return config
    cfg = _settings_for(settings)
    key = FUNDING_ARB_SETUP_KEY
    defaults = FUNDING_ARB_DEFAULT_CONFIG
    hold_hours = _setup_int(cfg, key, "max_hold_hours", "FUNDING_ARB_MAX_HOLD_HOURS", defaults.max_hold_hours)
    max_hold_intervals = max(1, math.ceil(hold_hours / 8))
    return FundingArbConfig(
        min_rate=_setup_float(cfg, key, "min_rate", "FUNDING_ARB_MIN_RATE", defaults.min_rate),
        exit_rate=_setup_float(cfg, key, "exit_rate", "FUNDING_ARB_EXIT_RATE", defaults.exit_rate),
        max_hold_intervals=max_hold_intervals,
        max_spread_bps=_setup_float(cfg, key, "max_spread_bps", "FUNDING_ARB_MAX_SPREAD_BPS", defaults.max_spread_bps),
    )


def get_divergence_volume_config(
    config: DivergenceVolumeConfig | None = None,
    *,
    timeframe: str | None = None,
    settings: "Settings | None" = None,
) -> DivergenceVolumeConfig:
    """Config do divergence-and-volume, calibravel por timeframe.

    As env vars sao unicas para os tres timeframes: um
    `DIVERGENCE_AND_VOLUME_RSI_PERIOD` vale para 15m, 1h e 4h ao mesmo tempo,
    entao nao ha como ajustar um sem mexer nos outros. A chave de settings
    inclui o timeframe (`setups.divergence-and-volume-4h.rsi_period`), que e o
    que torna a calibracao por timeframe possivel.
    """
    from workspace.config import ConfigError

    if config is not None:
        return config
    cfg = _settings_for(settings)
    normalized_tf = normalize_timeframe(timeframe) if timeframe else None
    defaults = (
        DIVERGENCE_AND_VOLUME_CONFIGS.get(normalized_tf, DIVERGENCE_AND_VOLUME_DEFAULT_CONFIG)
        if normalized_tf
        else DIVERGENCE_AND_VOLUME_DEFAULT_CONFIG
    )
    key = divergence_volume_setup_key(timeframe)

    target_levels = _setup_tuple(cfg, key, "target_levels", defaults.target_levels)
    target_weights = _setup_tuple(cfg, key, "target_weights", defaults.target_weights)
    if not target_levels:
        # `len([]) != len([])` e falso, entao a escada vazia passava -- e o
        # sinal quebrava depois em `target_prices[-1]`, longe da causa.
        raise ConfigError(
            f"setups.{key}: target_levels esta vazio; um setup precisa de pelo menos um alvo."
        )
    if len(target_levels) != len(target_weights):
        # Pesos em quantidade diferente dos alvos distribuem capital de forma
        # que ninguem pediu; barrar aqui e barato, depois da entrada nao e.
        raise ConfigError(
            f"setups.{key}: target_weights tem {len(target_weights)} itens para "
            f"{len(target_levels)} alvos em target_levels -- precisam casar."
        )

    return DivergenceVolumeConfig(
        rsi_period=_setup_int(cfg, key, "rsi_period", "DIVERGENCE_AND_VOLUME_RSI_PERIOD", defaults.rsi_period),
        volume_avg_period=_setup_int(cfg, key, "volume_avg_period", "DIVERGENCE_AND_VOLUME_VOLUME_AVG_PERIOD", defaults.volume_avg_period),
        volume_factor=_setup_float(cfg, key, "volume_factor", "DIVERGENCE_AND_VOLUME_VOLUME_FACTOR", defaults.volume_factor),
        fibonacci_tolerance_pct=_setup_float(cfg, key, "fibonacci_tolerance_pct", "DIVERGENCE_AND_VOLUME_FIBONACCI_TOLERANCE_PCT", defaults.fibonacci_tolerance_pct),
        divergence_lookback=_setup_int(cfg, key, "divergence_lookback", "DIVERGENCE_AND_VOLUME_DIVERGENCE_LOOKBACK", defaults.divergence_lookback),
        fibonacci_lookback=_setup_int(cfg, key, "fibonacci_lookback", "DIVERGENCE_AND_VOLUME_FIBONACCI_LOOKBACK", defaults.fibonacci_lookback),
        min_gap=_setup_int(cfg, key, "min_gap", "DIVERGENCE_AND_VOLUME_MIN_GAP", defaults.min_gap),
        rsi_delta=_setup_float(cfg, key, "rsi_delta", "DIVERGENCE_AND_VOLUME_RSI_DELTA", defaults.rsi_delta),
        fibonacci_tolerance_atr=_setup_float(cfg, key, "fibonacci_tolerance_atr", "DIVERGENCE_AND_VOLUME_FIBONACCI_TOLERANCE_ATR", defaults.fibonacci_tolerance_atr),
        atr_buffer=_setup_float(cfg, key, "atr_buffer", "DIVERGENCE_AND_VOLUME_ATR_BUFFER", defaults.atr_buffer),
        fibonacci_levels=_setup_tuple(cfg, key, "fibonacci_levels", defaults.fibonacci_levels),
        target_levels=target_levels,
        target_weights=target_weights,
        min_reward_risk=_setup_float(cfg, key, "min_reward_risk", "DIVERGENCE_AND_VOLUME_MIN_REWARD_RISK", defaults.min_reward_risk),
        max_hold_bars=_setup_int(cfg, key, "max_hold_bars", "DIVERGENCE_AND_VOLUME_MAX_HOLD_BARS", defaults.max_hold_bars),
    )


def validate_setup_settings(*, settings: "Settings | None" = None) -> None:
    """Resolve toda config de setup uma vez, para o erro aparecer no boot.

    Sem isto, um valor invalido so estoura dentro do loop de scan -- que
    captura `Exception`, loga um warning e faz `break`. O bot fica de pe,
    nao abre nada e nao falha: a "falha barulhenta" prometida virava
    degradacao silenciosa, com raio maior (o `break` mata os demais setups
    daquele simbolo).

    Chamar no boot, antes do loop.
    """
    cfg = _settings_for(settings)
    get_triangle_breakout_config(settings=cfg)
    get_funding_arb_config(settings=cfg)
    for timeframe in ("15m", "1h", "4h"):
        get_divergence_volume_config(timeframe=timeframe, settings=cfg)
    get_divergence_volume_config(settings=cfg)
    _log_setup_config_origins(cfg)


def _log_setup_config_origins(cfg: "Settings") -> None:
    """Diz qual camada venceu em cada campo sobrescrito.

    Sem isto, um operador que define `setups.triangle-breakout.pivot_window` e
    tem `TRIANGLE_PIVOT_WINDOW` no env ve o valor do env sem nenhuma pista de
    que o settings foi ignorado -- e conclui que settings.json nao funciona.
    """
    watched = (
        (TRIANGLE_BREAKOUT_SETUP_KEY, "pivot_window", "TRIANGLE_PIVOT_WINDOW"),
        (TRIANGLE_BREAKOUT_SETUP_KEY, "contraction_max_ratio", "TRIANGLE_CONTRACTION_MAX_RATIO"),
        (TRIANGLE_BREAKOUT_SETUP_KEY, "volume_multiplier", "TRIANGLE_VOLUME_MULTIPLIER"),
        (TRIANGLE_BREAKOUT_SETUP_KEY, "stop_atr_mult", "TRIANGLE_STOP_ATR_MULT"),
        (FUNDING_ARB_SETUP_KEY, "min_rate", "FUNDING_ARB_MIN_RATE"),
        (FUNDING_ARB_SETUP_KEY, "exit_rate", "FUNDING_ARB_EXIT_RATE"),
        (FUNDING_ARB_SETUP_KEY, "max_hold_hours", "FUNDING_ARB_MAX_HOLD_HOURS"),
        (FUNDING_ARB_SETUP_KEY, "max_spread_bps", "FUNDING_ARB_MAX_SPREAD_BPS"),
    )
    encobertos = [
        f"{key}.{field} (env {env})"
        for key, field, env in watched
        if cfg.origin(f"setups.{key}.{field}", env=env).layer == "env"
        and _dig_present(cfg, f"setups.{key}.{field}")
    ]
    if encobertos:
        logger.warning(
            "settings de setup ignorados porque a env tem precedencia: %s",
            ", ".join(encobertos),
        )


def _dig_present(cfg: "Settings", dotted: str) -> bool:
    """True se a chave existe em algum arquivo de settings."""
    sentinel = object()
    return cfg.get_json(dotted, default=sentinel) is not sentinel


def parse_setup_selection(raw: str | None) -> List[str]:
    if not raw or raw.strip().lower() == "all":
        return list(ACTIVE_SETUP_KEYS)
    selected: List[str] = []
    for chunk in raw.split(","):
        key = normalize_setup_key(chunk)
        if key in DEPRECATED_SETUP_KEYS:
            raise ValueError(f"setup removido/desativado: {chunk}")
        if key not in SETUP_CATALOG:
            raise ValueError(f"setup invalido: {chunk}")
        selected.append(key)
    return selected


def generate_operational_dataset(
    *,
    days: int = 90,
    initial_price: float = 45000.0,
    seed: int = 42,
    timeframe: str = "1h",
) -> pd.DataFrame:
    timeframe_key = normalize_timeframe(timeframe)
    config = TIMEFRAME_CONFIG[timeframe_key]
    candles = days * config["candles_per_day"]
    dates = pd.date_range(end=datetime.now(), periods=candles, freq=config["freq"])
    rng = np.random.default_rng(seed)

    returns = rng.normal(config["drift"], config["vol"], len(dates))
    prices = initial_price * np.exp(np.cumsum(returns))
    high = prices * (1 + np.abs(rng.normal(0, config["wick_sigma"], len(dates))))
    low = prices * (1 - np.abs(rng.normal(0, config["wick_sigma"], len(dates))))
    close = prices + rng.normal(0, config["close_noise"], len(dates))
    volume = rng.uniform(100000, 500000, len(dates))

    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": prices,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    df["high"] = df[["high", "close", "open"]].max(axis=1)
    df["low"] = df[["low", "close", "open"]].min(axis=1)
    df = _enrich_market_dataset(df)
    df.attrs["timeframe"] = timeframe_key
    df.attrs["source"] = "synthetic"
    return df


def run_operational_backtests(
    *,
    setup_keys: Iterable[str] | None = None,
    days: int = 90,
    initial_price: float = 45000.0,
    seed: int = 42,
    timeframe: str | None = None,
    hybrid_profile: str | None = None,
) -> tuple[pd.DataFrame, Dict[str, BacktestResult]]:
    selected = list(setup_keys or SETUP_CATALOG.keys())
    if not selected:
        raise ValueError("nenhum setup selecionado")

    resolved_hybrid_profile = normalize_hybrid_profile(hybrid_profile)
    triangle_config = get_triangle_breakout_config()
    funding_config = get_funding_arb_config()
    per_setup_timeframes = _resolve_setup_timeframes(selected, timeframe)
    datasets: dict[str, pd.DataFrame] = {}
    results: Dict[str, BacktestResult] = {}
    primary_df: pd.DataFrame | None = None

    for key in selected:
        normalized = normalize_setup_key(key)
        if normalized not in SETUP_CATALOG:
            raise ValueError(f"setup invalido: {key}")

        timeframe_key = per_setup_timeframes[normalized]
        if timeframe_key not in datasets:
            datasets[timeframe_key] = generate_operational_dataset(
                days=days,
                initial_price=initial_price,
                seed=seed,
                timeframe=timeframe_key,
            )
        df = datasets[timeframe_key]
        if primary_df is None:
            primary_df = df.copy()

        if normalized in {"grid", "grid-strict"}:
            results[normalized] = _backtest_grid(df, strict=normalized.endswith("strict"))
        elif normalized == "delta-neutral":
            results[normalized] = _backtest_delta_neutral(df)
        elif normalized == "institutional-strict":
            results[normalized] = _backtest_institutional(df, strict=True)
        elif normalized == "hybrid":
            results[normalized] = _backtest_hybrid(df, profile_key=resolved_hybrid_profile)
        elif normalized == "hybrid-15m":
            results[normalized] = _backtest_hybrid_15m(df, profile_key=resolved_hybrid_profile)
        elif normalized == "bollinger-mean-reversion":
            results[normalized] = _backtest_bollinger_mean_reversion(df, strict=False)
        elif normalized == "funding-arb":
            results[normalized] = _backtest_funding_arb(df, config=funding_config)
        elif normalized == "low-stoch-storm":
            results[normalized] = _backtest_low_stoch_storm(df)
        elif normalized in {"divergence-and-volume-15m", "divergence-and-volume-1h", "divergence-and-volume-4h"}:
            results[normalized] = _backtest_divergence_volume_reversal(
                df,
                config=get_divergence_volume_config(timeframe=timeframe_key),
                setup_key=normalized,
            )

    assert primary_df is not None
    primary_df.attrs["per_setup_timeframes"] = per_setup_timeframes
    primary_df.attrs["hybrid_profile"] = resolved_hybrid_profile
    return primary_df, results


def run_hybrid_real_backtests(
    *,
    symbols: Sequence[str] | None = None,
    days: int = 30,
    exchange_id: str = "binance",
    profile_key: str | None = None,
) -> tuple[Dict[str, BacktestResult], Dict[str, str]]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_HYBRID_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    resolved_profile = normalize_hybrid_profile(profile_key)
    exchange = _build_ccxt_exchange(exchange_id)
    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for symbol in selected:
        try:
            df = fetch_hybrid_real_dataset(exchange, symbol=symbol, days=days)
            results[symbol] = _backtest_hybrid(
                df,
                result_key="hybrid",
                result_label=SETUP_CATALOG["hybrid"].label,
                profile_key=resolved_profile,
            )
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)

    return results, errors


def run_triangle_real_backtests(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_TRIANGLE_REAL_DAYS,
    exchange_id: str = "binance",
    config: TriangleBreakoutConfig | None = None,
) -> tuple[Dict[str, BacktestResult], Dict[str, str]]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_TRIANGLE_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    resolved_config = get_triangle_breakout_config(config)
    exchange = _build_ccxt_exchange(exchange_id)
    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for symbol in selected:
        try:
            df = fetch_triangle_real_dataset(exchange, symbol=symbol, days=days)
            results[symbol] = _backtest_triangle_breakout(df, config=resolved_config)
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)

    return results, errors


def run_funding_real_backtests(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_FUNDING_ARB_REAL_DAYS,
    exchange_id: str = "krakenfutures",
    min_rate: float = DEFAULT_FUNDING_ARB_MIN_RATE,
    exit_rate: float = DEFAULT_FUNDING_ARB_EXIT_RATE,
    max_hold_intervals: int = DEFAULT_FUNDING_ARB_MAX_HOLD_INTERVALS,
    config: FundingArbConfig | None = None,
) -> tuple[Dict[str, BacktestResult], Dict[str, str]]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_FUNDING_ARB_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    resolved_config = get_funding_arb_config(config)
    if config is None:
        resolved_config = FundingArbConfig(
            min_rate=min_rate,
            exit_rate=exit_rate,
            max_hold_intervals=max_hold_intervals,
            max_spread_bps=resolved_config.max_spread_bps,
        )
    exchange = _build_ccxt_exchange(exchange_id)
    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for symbol in selected:
        try:
            history = fetch_funding_real_dataset(exchange, symbol=symbol, days=days)
            results[symbol] = _backtest_funding_history(
                history,
                config=resolved_config,
                result_key="funding-arb",
                result_label=SETUP_CATALOG["funding-arb"].label,
            )
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)

    return results, errors


def run_divergence_volume_real_backtests(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_DIVERGENCE_AND_VOLUME_REAL_DAYS,
    exchange_id: str = "binance",
    config: DivergenceVolumeConfig | None = None,
) -> tuple[Dict[str, BacktestResult], Dict[str, str]]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    resolved_config = get_divergence_volume_config(config)
    exchange = _build_ccxt_exchange(exchange_id)
    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for symbol in selected:
        try:
            df = fetch_divergence_volume_real_dataset(exchange, symbol=symbol, days=days, config=resolved_config)
            results[symbol] = _backtest_divergence_volume_reversal(df, config=resolved_config)
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)

    return results, errors


def run_low_stoch_real_backtests(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_LOW_STOCH_REAL_DAYS,
    exchange_id: str = "binance",
) -> tuple[Dict[str, BacktestResult], Dict[str, str]]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_LOW_STOCH_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    exchange = _build_ccxt_exchange(exchange_id)
    results: Dict[str, BacktestResult] = {}
    errors: Dict[str, str] = {}

    for symbol in selected:
        try:
            df = fetch_low_stoch_real_dataset(exchange, symbol=symbol, days=days)
            results[symbol] = _backtest_low_stoch_storm(df)
        except Exception as exc:  # noqa: BLE001
            errors[symbol] = str(exc)

    return results, errors


def fetch_triangle_real_dataset(exchange, *, symbol: str, days: int = DEFAULT_TRIANGLE_REAL_DAYS) -> pd.DataFrame:
    candles_per_day = TIMEFRAME_CONFIG["1h"]["candles_per_day"]
    requested_candles = max(days * candles_per_day, 120)
    warmup_candles = 240
    limit = requested_candles + warmup_candles
    raw = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=limit)
    if not raw:
        raise ValueError(f"sem candles retornados para {symbol}")

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if len(df) < 120:
        raise ValueError(f"dados insuficientes para {symbol}: {len(df)} candles")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = prepare_market_dataset(df)
    if len(df) > requested_candles:
        df = df.iloc[-requested_candles:].reset_index(drop=True)

    df.attrs["timeframe"] = "1h"
    df.attrs["source"] = "real"
    df.attrs["symbol"] = symbol
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    return df


def fetch_low_stoch_real_dataset(exchange, *, symbol: str, days: int = DEFAULT_LOW_STOCH_REAL_DAYS) -> pd.DataFrame:
    candles_per_day = TIMEFRAME_CONFIG["4h"]["candles_per_day"]
    requested_candles = max(days * candles_per_day, 120)
    warmup_candles = 240
    limit = requested_candles + warmup_candles
    resolved_symbol = _resolve_ccxt_swap_symbol(exchange, symbol)
    raw = exchange.fetch_ohlcv(resolved_symbol, timeframe="4h", limit=limit)
    if not raw:
        raise ValueError(f"sem candles retornados para {symbol}")

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if len(df) < 220:
        raise ValueError(f"dados insuficientes para {symbol}: {len(df)} candles")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = prepare_market_dataset(df)
    if len(df) > requested_candles:
        df = df.iloc[-requested_candles:].reset_index(drop=True)

    df.attrs["timeframe"] = "4h"
    df.attrs["source"] = "real"
    df.attrs["symbol"] = symbol
    df.attrs["ccxt_symbol"] = resolved_symbol
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    return df


def fetch_hybrid_real_dataset(exchange, *, symbol: str, days: int = 30) -> pd.DataFrame:
    candles_per_day = TIMEFRAME_CONFIG["4h"]["candles_per_day"]
    requested_candles = max(days * candles_per_day, 60)
    warmup_candles = 220
    limit = requested_candles + warmup_candles
    raw = exchange.fetch_ohlcv(symbol, timeframe="4h", limit=limit)
    if not raw:
        raise ValueError(f"sem candles retornados para {symbol}")

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if len(df) < 60:
        raise ValueError(f"dados insuficientes para {symbol}: {len(df)} candles")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = prepare_market_dataset(df)
    if len(df) > requested_candles:
        df = df.iloc[-requested_candles:].reset_index(drop=True)

    df.attrs["timeframe"] = "4h"
    df.attrs["source"] = "real"
    df.attrs["symbol"] = symbol
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    return df


def fetch_divergence_volume_real_dataset(
    exchange,
    *,
    symbol: str,
    days: int = DEFAULT_DIVERGENCE_AND_VOLUME_REAL_DAYS,
    config: DivergenceVolumeConfig | None = None,
) -> pd.DataFrame:
    resolved_config = get_divergence_volume_config(config)
    candles_per_day = TIMEFRAME_CONFIG["4h"]["candles_per_day"]
    requested_candles = max(days * candles_per_day, 120)
    warmup_candles = max(120, resolved_config.divergence_lookback + resolved_config.volume_avg_period + resolved_config.rsi_period)
    limit = requested_candles + warmup_candles
    resolved_symbol = _resolve_ccxt_swap_symbol(exchange, symbol)
    raw = exchange.fetch_ohlcv(resolved_symbol, timeframe="4h", limit=limit)
    if not raw:
        raise ValueError(f"sem candles retornados para {symbol}")

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if len(df) < 120:
        raise ValueError(f"dados insuficientes para {symbol}: {len(df)} candles")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = prepare_market_dataset(df)
    if len(df) > requested_candles:
        df = df.iloc[-requested_candles:].reset_index(drop=True)

    df.attrs["timeframe"] = "4h"
    df.attrs["source"] = "real"
    df.attrs["symbol"] = symbol
    df.attrs["ccxt_symbol"] = resolved_symbol
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    return df


def fetch_funding_real_dataset(exchange, *, symbol: str, days: int = DEFAULT_FUNDING_ARB_REAL_DAYS) -> pd.DataFrame:
    resolved_symbol = _resolve_ccxt_swap_symbol(exchange, symbol)
    limit = max(days * 3 + 20, 40)
    raw = exchange.fetch_funding_rate_history(resolved_symbol, limit=limit)
    if not raw:
        raise ValueError(f"sem funding history retornado para {symbol}")

    rows = []
    for item in raw:
        rate = item.get("fundingRate")
        ts = item.get("timestamp")
        if rate is None or ts is None:
            continue
        rows.append({"timestamp": pd.to_datetime(ts, unit="ms", utc=True).tz_localize(None), "funding_rate": float(rate)})

    df = pd.DataFrame(rows).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if len(df) < 20:
        raise ValueError(f"dados de funding insuficientes para {symbol}: {len(df)} linhas")

    df.attrs["timeframe"] = "8h"
    df.attrs["source"] = "real"
    df.attrs["symbol"] = symbol
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    return df


def _candidate_key(prefix: str, config_payload: dict) -> str:
    tokens = [prefix]
    for key, value in config_payload.items():
        if isinstance(value, float):
            tokens.append(f"{key}={value:.5f}".rstrip("0").rstrip("."))
        else:
            tokens.append(f"{key}={value}")
    return " | ".join(tokens)


def _median_metric(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(pd.Series(list(values), dtype="float64").median())


def _summarize_calibration_candidate(
    *,
    prefix: str,
    config_payload: dict,
    results: Dict[str, BacktestResult],
    errors: Dict[str, str],
    drawdown_cap: float,
    min_trades: int,
    min_trade_symbols: int,
) -> CalibrationCandidateResult:
    trade_qualified_symbols = sum(1 for result in results.values() if result.total_trades >= min_trades)
    eligible = True
    rejection_reason = ""

    if not results:
        eligible = False
        rejection_reason = "nenhum simbolo gerou resultado"
    else:
        median_drawdown = _median_metric([result.max_drawdown for result in results.values()])
        if median_drawdown > drawdown_cap:
            eligible = False
            rejection_reason = f"median max_drawdown {median_drawdown:.2f}% > cap {drawdown_cap:.2f}%"
        elif trade_qualified_symbols < min_trade_symbols:
            eligible = False
            rejection_reason = (
                f"trade-qualified symbols {trade_qualified_symbols} < minimo {min_trade_symbols} "
                f"(threshold={min_trades} trades)"
            )

    return CalibrationCandidateResult(
        candidate_key=_candidate_key(prefix, config_payload),
        config=config_payload,
        eligible=eligible,
        rejection_reason=rejection_reason,
        median_sharpe_ratio=_median_metric([result.sharpe_ratio for result in results.values()]),
        median_total_pnl=_median_metric([result.total_pnl for result in results.values()]),
        median_max_drawdown=_median_metric([result.max_drawdown for result in results.values()]),
        median_total_trades=_median_metric([float(result.total_trades) for result in results.values()]),
        trade_qualified_symbols=trade_qualified_symbols,
        successful_symbols=len(results),
        per_symbol=results,
        errors=errors,
    )


def _select_best_calibration_candidate(
    candidates: Sequence[CalibrationCandidateResult],
) -> CalibrationCandidateResult | None:
    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda candidate: (
            -candidate.median_sharpe_ratio,
            -candidate.median_total_pnl,
            candidate.median_max_drawdown,
            -candidate.median_total_trades,
            candidate.candidate_key,
        ),
    )[0]


def calibrate_triangle_real(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_TRIANGLE_REAL_DAYS,
    exchange_id: str = "binance",
    pivot_windows: Sequence[int] = (2, 3, 4),
    contraction_max_ratios: Sequence[float] = (0.80, 0.86, 0.92),
    volume_multipliers: Sequence[float] = (1.2, 1.5, 1.8),
    breakout_buffer_atr_mults: Sequence[float] = (0.15, 0.25, 0.35),
    flat_threshold_atr_mults: Sequence[float] = (0.03, 0.05, 0.07),
    slope_threshold_atr_mults: Sequence[float] = (0.01, 0.02, 0.03),
    stop_atr_mults: Sequence[float] = (0.8, 1.0, 1.2),
) -> tuple[list[CalibrationCandidateResult], CalibrationCandidateResult | None]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_TRIANGLE_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    exchange = _build_ccxt_exchange(exchange_id)
    datasets: dict[str, pd.DataFrame] = {}
    fetch_errors: dict[str, str] = {}
    for symbol in selected:
        try:
            datasets[symbol] = fetch_triangle_real_dataset(exchange, symbol=symbol, days=days)
        except Exception as exc:  # noqa: BLE001
            fetch_errors[symbol] = str(exc)

    candidates: list[CalibrationCandidateResult] = []
    for values in product(
        pivot_windows,
        contraction_max_ratios,
        volume_multipliers,
        breakout_buffer_atr_mults,
        flat_threshold_atr_mults,
        slope_threshold_atr_mults,
        stop_atr_mults,
    ):
        config = TriangleBreakoutConfig(
            pivot_window=int(values[0]),
            contraction_max_ratio=float(values[1]),
            volume_multiplier=float(values[2]),
            breakout_buffer_atr_mult=float(values[3]),
            flat_threshold_atr_mult=float(values[4]),
            slope_threshold_atr_mult=float(values[5]),
            stop_atr_mult=float(values[6]),
        )
        results: Dict[str, BacktestResult] = {}
        errors = dict(fetch_errors)
        for symbol, dataset in datasets.items():
            try:
                results[symbol] = _backtest_triangle_breakout(dataset, config=config)
            except Exception as exc:  # noqa: BLE001
                errors[symbol] = str(exc)
        candidates.append(
            _summarize_calibration_candidate(
                prefix="triangle",
                config_payload=config.to_dict(),
                results=results,
                errors=errors,
                drawdown_cap=12.0,
                min_trades=8,
                min_trade_symbols=3,
            )
        )

    return candidates, _select_best_calibration_candidate(candidates)


def calibrate_funding_real(
    *,
    symbols: Sequence[str] | None = None,
    days: int = DEFAULT_FUNDING_ARB_REAL_DAYS,
    exchange_id: str = "krakenfutures",
    min_rates: Sequence[float] = (0.00005, 0.00010, 0.00015, 0.00020, 0.00025),
    exit_rates: Sequence[float] = (0.00001, 0.00002, 0.00005),
    max_hold_intervals_list: Sequence[int] = (3, 6, 9, 12),
) -> tuple[list[CalibrationCandidateResult], CalibrationCandidateResult | None]:
    selected = [symbol.strip() for symbol in (symbols or DEFAULT_FUNDING_ARB_REAL_SYMBOLS) if symbol.strip()]
    if not selected:
        raise ValueError("nenhum simbolo informado")

    exchange = _build_ccxt_exchange(exchange_id)
    datasets: dict[str, pd.DataFrame] = {}
    fetch_errors: dict[str, str] = {}
    for symbol in selected:
        try:
            datasets[symbol] = fetch_funding_real_dataset(exchange, symbol=symbol, days=days)
        except Exception as exc:  # noqa: BLE001
            fetch_errors[symbol] = str(exc)

    candidates: list[CalibrationCandidateResult] = []
    for values in product(min_rates, exit_rates, max_hold_intervals_list):
        config = FundingArbConfig(
            min_rate=float(values[0]),
            exit_rate=float(values[1]),
            max_hold_intervals=int(values[2]),
            max_spread_bps=FUNDING_ARB_DEFAULT_CONFIG.max_spread_bps,
        )
        results: Dict[str, BacktestResult] = {}
        errors = dict(fetch_errors)
        for symbol, dataset in datasets.items():
            try:
                results[symbol] = _backtest_funding_history(
                    dataset,
                    config=config,
                    result_key="funding-arb",
                    result_label=SETUP_CATALOG["funding-arb"].label,
                )
            except Exception as exc:  # noqa: BLE001
                errors[symbol] = str(exc)
        candidates.append(
            _summarize_calibration_candidate(
                prefix="funding",
                config_payload=config.to_dict(),
                results=results,
                errors=errors,
                drawdown_cap=6.0,
                min_trades=3,
                min_trade_symbols=2,
            )
        )

    return candidates, _select_best_calibration_candidate(candidates)


def rank_backtest_results(results: Dict[str, BacktestResult]) -> List[BacktestResult]:
    return sorted(results.values(), key=lambda item: item.total_pnl, reverse=True)


def serialize_backtest_results(results: Dict[str, BacktestResult]) -> dict:
    return {key: result.to_dict() for key, result in results.items()}


def _resolve_setup_timeframes(selected: Sequence[str], timeframe: str | None) -> dict[str, str]:
    if timeframe is not None:
        normalized = normalize_timeframe(timeframe)
        return {normalize_setup_key(key): normalized for key in selected}

    return {
        normalize_setup_key(key): normalize_timeframe(SETUP_CATALOG[normalize_setup_key(key)].timeframe)
        for key in selected
    }


def _enrich_market_dataset(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    volume = enriched["volume"]

    enriched["ema8"] = close.ewm(span=8, adjust=False).mean()
    enriched["ema9"] = close.ewm(span=9, adjust=False).mean()
    enriched["ema21"] = close.ewm(span=21, adjust=False).mean()
    enriched["ema50"] = close.ewm(span=50, adjust=False).mean()
    enriched["ema80"] = close.ewm(span=80, adjust=False).mean()
    enriched["ema200"] = close.ewm(span=200, adjust=False).mean()
    enriched["rsi"] = _calculate_rsi(close, 14)
    enriched["rsi14"] = enriched["rsi"]
    enriched["macd"], enriched["macd_signal"] = _calculate_macd(close)
    enriched["bb_upper"], enriched["bb_middle"], enriched["bb_lower"] = _calculate_bollinger(close)
    enriched["volume_sma"] = volume.rolling(window=20).mean()
    enriched["volume_sma20"] = enriched["volume_sma"]
    enriched["volume_ratio"] = volume / enriched["volume_sma"]
    enriched["sma50"] = close.rolling(window=50).mean()
    enriched["std50"] = close.rolling(window=50).std()
    enriched["stoch_k"], enriched["stoch_d"] = _calculate_stochastic(high, low, close, 14, 3, 3)
    enriched["atr14"] = _calculate_atr(high, low, close, 14)
    pct_change = close.pct_change().fillna(0.0)
    enriched["synthetic_basis_bps"] = ((close - enriched["ema21"]) / close.replace(0, np.nan)).fillna(0.0) * 10000
    enriched["funding_rate_8h"] = ((pct_change.ewm(span=8, adjust=False).mean() * 0.12) + (enriched["synthetic_basis_bps"] / 10000 * 0.02)).clip(-0.00045, 0.00045)
    return enriched


def prepare_market_dataset(df: pd.DataFrame) -> pd.DataFrame:
    return _enrich_market_dataset(df)


def _calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _calculate_macd(prices: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _calculate_bollinger(
    prices: pd.Series,
    period: int = 20,
    std: int = 2,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    sma = prices.rolling(period).mean()
    std_val = prices.rolling(period).std()
    upper = sma + (std_val * std)
    lower = sma - (std_val * std)
    return upper, sma, lower


def _calculate_stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    smooth_k: int = 3,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    denominator = (highest_high - lowest_low).replace(0, np.nan)
    fast_k = ((close - lowest_low) / denominator) * 100
    stoch_k = fast_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
    stoch_d = stoch_k.rolling(window=d_period, min_periods=d_period).mean()
    return stoch_k.fillna(50.0), stoch_d.fillna(50.0)


def _calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    previous_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean().bfill()


def _capped_directional_exit(pnl_pct: float, *, take_profit: float, stop_loss: float) -> float | None:
    if pnl_pct >= take_profit:
        return take_profit
    if pnl_pct <= -stop_loss:
        return -stop_loss
    return None


def _momentum_quality_gate(row: pd.Series, *, strict: bool = False) -> bool:
    close = float(row["close"])
    if close <= 0:
        return False
    ema_gap = (float(row["ema9"]) - float(row["ema21"])) / close
    macd_gap = (float(row["macd"]) - float(row["macd_signal"])) / close
    rsi_min, rsi_max = (55.0, 68.0) if strict else (55.0, 70.0)
    ema_gap_min = 0.0015 if strict else 0.0010
    macd_gap_min = 0.0008 if strict else 0.0005
    volume_ratio_min = 1.15 if strict else 1.05
    return (
        float(row["ema9"]) > float(row["ema21"])
        and close > float(row["ema50"])
        and rsi_min < float(row["rsi"]) < rsi_max
        and float(row["macd"]) > float(row["macd_signal"])
        and ema_gap > ema_gap_min
        and macd_gap > macd_gap_min
        and float(row["volume"]) > float(row["volume_sma20"]) * volume_ratio_min
    )


def _institutional_quality_gate(row: pd.Series, *, strict: bool = False) -> bool:
    close = float(row["close"])
    rsi_min, rsi_max = (52.0, 65.0) if strict else (50.0, 70.0)
    volume_ratio_min = 1.15 if strict else 1.05
    ema_gap = (float(row["ema9"]) - float(row["ema21"])) / close if close > 0 else 0.0
    macd_gap = (float(row["macd"]) - float(row["macd_signal"])) / close if close > 0 else 0.0
    macd_gap_min = 0.002 if strict else 0.001
    macd_gap_max = 0.005 if strict else float("inf")
    return (
        float(row["ema9"]) > float(row["ema21"])
        and close > float(row["ema50"])
        and rsi_min < float(row["rsi"]) < rsi_max
        and float(row["volume"]) > float(row["volume_sma20"]) * volume_ratio_min
        and macd_gap_min < macd_gap < macd_gap_max
        and (not strict or ema_gap > 0.001)
    )


def _backtest_momentum(df: pd.DataFrame, *, strict: bool = False) -> BacktestResult:
    trades: list[dict] = []
    position: dict | None = None

    for i in range(21, len(df)):
        row = df.iloc[i]
        if position is None and _momentum_quality_gate(row, strict=strict):
            position = {"entry": row["close"], "time": row["timestamp"]}
        elif position is not None:
            pnl_pct = (row["close"] - position["entry"]) / position["entry"]
            exit_pnl = _capped_directional_exit(pnl_pct, take_profit=0.025, stop_loss=0.02)
            if exit_pnl is not None:
                trades.append({"pnl_pct": exit_pnl * (1 - 0.0015) * 100, "bars": i})
                position = None

    return _calc_metrics(trades, SETUP_CATALOG["grid-strict"])


def _backtest_grid(df: pd.DataFrame, *, strict: bool = False) -> BacktestResult:
    trades: list[dict] = []
    position: dict | None = None

    for i in range(50, len(df)):
        row = df.iloc[i]
        entry_std = 2.4 if strict else 2.2
        rsi_threshold = 28 if strict else 30
        stop_loss = 0.03 if strict else 0.035
        if row["close"] < (row["sma50"] - entry_std * row["std50"]) and float(row["rsi14"]) < rsi_threshold and position is None:
            position = {"entry": row["close"], "entry_index": i}
        elif position is not None:
            pnl_pct = (row["close"] - position["entry"]) / position["entry"]
            exit_pnl = pnl_pct if row["close"] > float(row["sma50"]) else None
            if exit_pnl is None:
                exit_pnl = _capped_directional_exit(pnl_pct, take_profit=0.02, stop_loss=stop_loss)
            if exit_pnl is None and i - int(position["entry_index"]) >= 80:
                exit_pnl = pnl_pct
            if exit_pnl is not None:
                trades.append({"pnl_pct": exit_pnl * (1 - 0.0015) * 100, "bars": i})
                position = None

    return _calc_metrics(trades, SETUP_CATALOG["grid-strict" if strict else "grid"])


def _backtest_delta_neutral(df: pd.DataFrame) -> BacktestResult:
    return _calc_metrics(
        [],
        SETUP_CATALOG["delta-neutral"],
        notes="delta-neutral requer spread real entre venues; simulacao sintetica single-leg desativada",
    )


def _backtest_institutional(df: pd.DataFrame, *, strict: bool = False) -> BacktestResult:
    trades: list[dict] = []
    position: dict | None = None

    for i in range(26, len(df)):
        row = df.iloc[i]
        if _institutional_quality_gate(row, strict=strict) and position is None:
            entry = float(row["close"])
            if strict:
                stop_price = entry * 0.98
                targets, weights = _build_r_multiple_ladder(entry, stop_price, "long")
                position = {
                    "side": "long",
                    "entry": entry,
                    "entry_index": i,
                    "stop_price": stop_price,
                    "target_prices": targets,
                    "target_weights": weights,
                    "realized_return": 0.0,
                    "remaining_weight": 1.0,
                    "targets_hit": 0,
                }
            else:
                position = {"entry": entry, "entry_index": i}
        elif position is not None:
            close = float(row["close"])
            pnl_pct = (close - float(position["entry"])) / float(position["entry"])
            if strict:
                targets = list(position["target_prices"])
                weights = list(position["target_weights"])
                while int(position["targets_hit"]) < len(targets):
                    target_index = int(position["targets_hit"])
                    target_price = float(targets[target_index])
                    if close < target_price:
                        break
                    target_weight = float(weights[target_index])
                    position["realized_return"] += target_weight * _hybrid_directional_return("long", float(position["entry"]), target_price)
                    position["remaining_weight"] = max(0.0, float(position["remaining_weight"]) - target_weight)
                    position["targets_hit"] = target_index + 1

                exit_price: float | None = None
                current_stop = float(position["entry"]) if int(position["targets_hit"]) > 0 else float(position["stop_price"])
                if int(position["targets_hit"]) >= len(targets):
                    exit_price = float(targets[-1])
                elif close <= current_stop:
                    exit_price = current_stop
                elif i - int(position["entry_index"]) >= 8:
                    exit_price = close
                if exit_price is not None:
                    trades.append({"pnl_pct": _ladder_trade_pnl_pct(position, exit_price), "bars": i})
                    position = None
                continue

            exit_pnl = _capped_directional_exit(pnl_pct, take_profit=0.025, stop_loss=0.02)
            if exit_pnl is not None:
                trades.append({"pnl_pct": exit_pnl * (1 - 0.0015) * 100, "bars": i})
                position = None

    return _calc_metrics(trades, SETUP_CATALOG["institutional-strict"])


def _bollinger_quality_entry(row: pd.Series, *, volume_ratio_min: float = 1.05) -> str:
    close = float(row["close"])
    atr = float(row.get("atr14", 0.0) or 0.0)
    volume_ratio = float(row.get("volume_ratio", 0.0) or 0.0)
    if atr <= 0 or volume_ratio < volume_ratio_min:
        return ""
    if close <= float(row["bb_lower"]) - (0.20 * atr) and float(row["rsi14"]) < 35:
        return "long"
    if close >= float(row["bb_upper"]) + (0.20 * atr) and float(row["rsi14"]) > 72:
        return "short"
    return ""


def _backtest_bollinger_mean_reversion(df: pd.DataFrame, *, strict: bool = False) -> BacktestResult:
    trades: list[dict] = []
    position: dict | None = None

    for i in range(20, len(df)):
        row = df.iloc[i]
        if position is None:
            side = _bollinger_quality_entry(row, volume_ratio_min=1.20 if strict else 1.05)
            if side == "long":
                position = {"side": "long", "entry": float(row["close"]), "entry_index": i}
            elif side == "short":
                position = {"side": "short", "entry": float(row["close"]), "entry_index": i}
            continue

        pnl_pct = _hybrid_directional_return(position["side"], position["entry"], float(row["close"]))
        bars_open = i - position["entry_index"]
        hit_mean = (position["side"] == "long" and row["close"] >= row["bb_middle"]) or (
            position["side"] == "short" and row["close"] <= row["bb_middle"]
        )
        max_bars = 16
        exit_pnl = None
        if hit_mean or bars_open >= max_bars:
            exit_pnl = pnl_pct
        elif pnl_pct >= 0.02:
            exit_pnl = 0.02
        elif pnl_pct <= -0.015:
            exit_pnl = -0.015
        if exit_pnl is not None:
            trades.append({"pnl_pct": exit_pnl * (1 - 0.0015) * 100, "bars": bars_open, "side": position["side"]})
            position = None

    if position is not None:
        last_row = df.iloc[-1]
        pnl_pct = _hybrid_directional_return(position["side"], position["entry"], float(last_row["close"]))
        trades.append({"pnl_pct": pnl_pct * (1 - 0.0015) * 100, "bars": len(df) - 1 - position["entry_index"], "side": position["side"]})

    return _calc_metrics(trades, SETUP_CATALOG["bollinger-mean-reversion"])


def _build_r_multiple_ladder(entry_price: float, stop_price: float, side: str) -> tuple[list[float], list[float]]:
    if entry_price <= 0 or stop_price <= 0 or abs(entry_price - stop_price) < 1e-9:
        return [], []
    risk = abs(entry_price - stop_price)
    multiples = [1.0, 1.5, 2.0, 2.5]
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


def calculate_low_stoch_storm_signal(df: pd.DataFrame) -> dict[str, object] | None:
    if len(df) < 220:
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
    if risk_pct > 0.04:
        return None
    targets, weights = _build_r_multiple_ladder(close, stop_price, "long")
    if not targets:
        return None
    return {
        "side": "long",
        "entry_price": close,
        "stop_price": stop_price,
        "target_prices": targets,
        "target_weights": weights,
        "max_hold_bars": 80,
        "risk_pct": risk_pct,
    }


def _target_reached(side: str, row: pd.Series, target_price: float) -> bool:
    if side == "long":
        return float(row["high"]) >= target_price
    return float(row["low"]) <= target_price


def _stop_reached(side: str, row: pd.Series, stop_price: float) -> bool:
    if side == "long":
        return float(row["low"]) <= stop_price
    return float(row["high"]) >= stop_price


def _ladder_trade_pnl_pct(position: dict, exit_price: float) -> float:
    side = str(position["side"])
    entry = float(position["entry"])
    remaining_weight = float(position.get("remaining_weight", 1.0))
    realized_return = float(position.get("realized_return", 0.0))
    total_return = realized_return + remaining_weight * _hybrid_directional_return(side, entry, exit_price)
    return total_return * (1 - 0.0015) * 100


def _backtest_low_stoch_storm(df: pd.DataFrame) -> BacktestResult:
    view = prepare_market_dataset(df)
    trades: list[dict] = []
    position: dict | None = None

    for i in range(220, len(view)):
        row = view.iloc[i]
        if position is None:
            signal = calculate_low_stoch_storm_signal(view.iloc[: i + 1])
            if signal is None:
                continue
            position = {
                "side": str(signal["side"]),
                "entry": float(signal["entry_price"]),
                "entry_index": i,
                "stop_price": float(signal["stop_price"]),
                "target_prices": [float(target) for target in signal["target_prices"]],
                "target_weights": [float(weight) for weight in signal["target_weights"]],
                "realized_return": 0.0,
                "remaining_weight": 1.0,
                "targets_hit": 0,
                "max_hold_bars": int(signal["max_hold_bars"]),
            }
            continue

        side = str(position["side"])
        bars_open = i - int(position["entry_index"])
        exit_price: float | None = None
        exit_reason = ""

        current_stop = float(position["entry"]) if int(position["targets_hit"]) > 0 else float(position["stop_price"])
        if _stop_reached(side, row, current_stop):
            exit_price = current_stop
            exit_reason = "stop_breakeven" if int(position["targets_hit"]) > 0 else "stop"
        else:
            targets = list(position["target_prices"])
            weights = list(position["target_weights"])
            while int(position["targets_hit"]) < len(targets):
                target_index = int(position["targets_hit"])
                target_price = float(targets[target_index])
                if not _target_reached(side, row, target_price):
                    break
                target_weight = float(weights[target_index])
                position["realized_return"] += target_weight * _hybrid_directional_return(side, float(position["entry"]), target_price)
                position["remaining_weight"] = max(0.0, float(position["remaining_weight"]) - target_weight)
                position["targets_hit"] = target_index + 1

            if int(position["targets_hit"]) >= len(targets):
                exit_price = float(targets[-1])
                exit_reason = "target_final"
            elif bars_open >= int(position["max_hold_bars"]):
                exit_price = float(row["close"])
                exit_reason = "timeout"

        if exit_price is not None:
            trades.append(
                {
                    "pnl_pct": _ladder_trade_pnl_pct(position, exit_price),
                    "bars": bars_open,
                    "side": side,
                    "exit_reason": exit_reason,
                    "targets_hit": int(position["targets_hit"]),
                }
            )
            position = None

    if position is not None:
        trades.append(
            {
                "pnl_pct": _ladder_trade_pnl_pct(position, float(view.iloc[-1]["close"])),
                "bars": len(view) - 1 - int(position["entry_index"]),
                "side": str(position["side"]),
                "exit_reason": "end_of_data",
                "targets_hit": int(position["targets_hit"]),
            }
        )

    return _calc_metrics(
        trades,
        SETUP_CATALOG["low-stoch-storm"],
        notes="low stoch storm | long/short 4h | slow stoch 25/75 + EMA structure + RSI filter | risk<=6% | TPs 1R/1.5R/2R/2.5R",
    )


def prepare_divergence_volume_dataset(df: pd.DataFrame, config: DivergenceVolumeConfig | None = None) -> pd.DataFrame:
    resolved = get_divergence_volume_config(config)
    view = df.copy()
    view["_divergence_volume_rsi"] = (
        view["rsi14"]
        if resolved.rsi_period == 14 and "rsi14" in view
        else _calculate_rsi(view["close"], resolved.rsi_period)
    )
    view["_divergence_volume_volume_sma"] = (
        view["volume_sma20"]
        if resolved.volume_avg_period == 20 and "volume_sma20" in view
        else view["volume"].rolling(window=resolved.volume_avg_period).mean()
    )
    return view


def identify_divergence_volume_reversal_pattern(df: pd.DataFrame) -> tuple[str, str]:
    if len(df) < 2:
        return "", ""
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    required = ["open", "high", "low", "close"]
    if prev[required].isna().any() or curr[required].isna().any():
        return "", ""

    prev_open = float(prev["open"])
    prev_close = float(prev["close"])
    curr_open = float(curr["open"])
    curr_high = float(curr["high"])
    curr_low = float(curr["low"])
    curr_close = float(curr["close"])
    candle_range = curr_high - curr_low
    if candle_range <= 0:
        return "", ""

    body = abs(curr_close - curr_open)
    body_for_wick = max(body, candle_range * 0.05)
    upper_wick = curr_high - max(curr_open, curr_close)
    lower_wick = min(curr_open, curr_close) - curr_low

    if prev_close < prev_open and curr_close > curr_open and curr_open <= prev_close and curr_close >= prev_open:
        return "long", "ENGULFING_BULLISH"
    if prev_close > prev_open and curr_close < curr_open and curr_open >= prev_close and curr_close <= prev_open:
        return "short", "ENGULFING_BEARISH"
    if curr_close >= curr_open and body <= candle_range * 0.35 and lower_wick >= body_for_wick * 2 and upper_wick <= candle_range * 0.30:
        return "long", "HAMMER"
    if curr_close <= curr_open and body <= candle_range * 0.35 and upper_wick >= body_for_wick * 2 and lower_wick <= candle_range * 0.30:
        return "short", "SHOOTING_STAR"
    return "", ""


def find_divergence_volume_pivots(df: pd.DataFrame, *, kind: str, lookback: int, pivot_window: int = 2) -> list[dict[str, float]]:
    if len(df) < pivot_window * 2 + 4:
        return []
    recent = df.tail(max(lookback, pivot_window * 2 + 4)).copy()
    value_col = "low" if kind == "low" else "high"
    pivots: list[dict[str, float]] = []

    for pos in range(pivot_window, len(recent) - pivot_window):
        row = recent.iloc[pos]
        value = float(row[value_col])
        rsi = float(row["_divergence_volume_rsi"])
        if not math.isfinite(value) or not math.isfinite(rsi):
            continue
        window = recent.iloc[pos - pivot_window : pos + pivot_window + 1][value_col]
        index_value = recent.index[pos]
        try:
            pivot_index = float(index_value)
        except (TypeError, ValueError):
            pivot_index = float(pos)
        if kind == "low" and value <= float(window.min()):
            pivots.append({"index": pivot_index, "price": value, "rsi": rsi})
        if kind == "high" and value >= float(window.max()):
            pivots.append({"index": pivot_index, "price": value, "rsi": rsi})
    return pivots


def detect_divergence_volume_rsi_divergence(df: pd.DataFrame, side: str, config: DivergenceVolumeConfig) -> dict[str, float | str] | None:
    kind = "low" if side == "long" else "high"
    pivots = find_divergence_volume_pivots(df, kind=kind, lookback=config.divergence_lookback)
    if len(pivots) < 1:
        return None
    current = df.iloc[-1]
    try:
        current_index = float(df.index[-1])
    except (TypeError, ValueError):
        current_index = float(len(df) - 1)
    candidates = [pivot for pivot in pivots if current_index - float(pivot["index"]) >= config.min_gap]
    if not candidates:
        return None
    first = min(candidates, key=lambda item: item["price"]) if side == "long" else max(candidates, key=lambda item: item["price"])
    current_price = float(current["low"] if side == "long" else current["high"])
    current_rsi = float(current["_divergence_volume_rsi"])
    bullish = side == "long" and current_price < first["price"] and current_rsi > first["rsi"] + config.rsi_delta
    bearish = side == "short" and current_price > first["price"] and current_rsi < first["rsi"] - config.rsi_delta
    if not (bullish or bearish):
        return None
    return {
        "type": "BULLISH" if side == "long" else "BEARISH",
        "first_pivot_price": first["price"],
        "first_pivot_rsi": first["rsi"],
        "second_pivot_price": current_price,
        "second_pivot_rsi": current_rsi,
    }


def divergence_volume_fibonacci_zone(df: pd.DataFrame, config: DivergenceVolumeConfig, *, side: str) -> dict[str, float | str] | None:
    row = df.iloc[-1]
    current_close = float(row["close"])
    if current_close <= 0 or not math.isfinite(current_close):
        return None
    recent = df.tail(max(config.fibonacci_lookback, 5))
    if recent.empty:
        return None
    atr = float(row["atr14"] if "atr14" in row and pd.notna(row["atr14"]) else 0.0)
    atr = max(atr, current_close * 0.001)
    tolerance_abs = atr * config.fibonacci_tolerance_atr
    candidates: list[dict[str, float | str]] = []
    if side == "short":
        anchor_pos = int(recent["low"].values.argmin())
        anchor_low = float(recent.iloc[anchor_pos]["low"])
        after_anchor = recent.iloc[anchor_pos:]
        swing_high = float(after_anchor["high"].max())
        base = swing_high - anchor_low
        if base <= 0:
            return None
        test_price = float(row["high"])
        for level in config.fibonacci_levels:
            candidates.append({"level": float(level), "price": anchor_low + base * float(level), "orientation": "extension_up", "swing_high": swing_high, "swing_low": anchor_low, "swing_range": base})
    else:
        anchor_pos = int(recent["high"].values.argmax())
        anchor_high = float(recent.iloc[anchor_pos]["high"])
        after_anchor = recent.iloc[anchor_pos:]
        swing_low = float(after_anchor["low"].min())
        base = anchor_high - swing_low
        if base <= 0:
            return None
        test_price = float(row["low"])
        for level in config.fibonacci_levels:
            candidates.append({"level": float(level), "price": anchor_high - base * float(level), "orientation": "extension_down", "swing_high": anchor_high, "swing_low": swing_low, "swing_range": base})

    nearest = min(candidates, key=lambda item: abs(float(item["price"]) - test_price))
    if abs(float(nearest["price"]) - test_price) > tolerance_abs:
        return None
    return nearest


def _divergence_volume_target_weights(config: DivergenceVolumeConfig, target_count: int) -> list[float]:
    weights = [float(weight) for weight in config.target_weights]
    if len(weights) != target_count:
        # Coerencia entre alvos e pesos agora e garantida por
        # `DivergenceVolumeConfig.__post_init__`; aqui `target_count` pode ser
        # menor que a escada configurada quando o sinal gera menos alvos que o
        # planejado, e a distribuicao uniforme e a resposta certa para isso.
        return [1 / target_count] * target_count
    total = sum(weights)
    return [weight / total for weight in weights]


def calculate_divergence_volume_signal(df: pd.DataFrame, config: DivergenceVolumeConfig | None = None) -> dict[str, object] | None:
    resolved = get_divergence_volume_config(config)
    min_rows = max(resolved.fibonacci_lookback + 8, resolved.divergence_lookback + 8, resolved.volume_avg_period + 3, resolved.rsi_period + 3, 90)
    if len(df) < min_rows:
        return None

    view = df if {"_divergence_volume_rsi", "_divergence_volume_volume_sma"}.issubset(df.columns) else prepare_divergence_volume_dataset(df, resolved)
    required = ["open", "high", "low", "close", "volume", "_divergence_volume_rsi", "_divergence_volume_volume_sma"]
    if view[required].tail(min_rows).isna().any().any():
        return None

    side, pattern_type = identify_divergence_volume_reversal_pattern(view)
    if not side:
        return None

    divergence = detect_divergence_volume_rsi_divergence(view, side, resolved)
    if divergence is None:
        return None

    fib = divergence_volume_fibonacci_zone(view, resolved, side=side)
    if fib is None:
        return None

    row = view.iloc[-1]
    prev = view.iloc[-2]
    volume = float(row["volume"])
    volume_sma = float(row["_divergence_volume_volume_sma"])
    if volume_sma <= 0 or volume <= volume_sma * resolved.volume_factor:
        return None

    atr = float(row["atr14"] if "atr14" in row and pd.notna(row["atr14"]) else 0.0)
    atr = max(atr, float(row["close"]) * 0.001)
    buffer = max(atr * resolved.atr_buffer, float(row["close"]) * 0.0002)

    if side == "long":
        entry_price = float(row["high"]) + buffer
        stop_price = float(row["low"]) - buffer
        invalidation_price = float(row["low"])
    else:
        entry_price = float(row["low"]) - buffer
        stop_price = float(row["high"]) + buffer
        invalidation_price = float(row["high"])

    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return None
    if side == "long":
        target_prices = [entry_price + risk * float(level) for level in resolved.target_levels]
    else:
        target_prices = [entry_price - risk * float(level) for level in resolved.target_levels]

    if stop_price <= 0 or entry_price <= 0 or any(target <= 0 for target in target_prices):
        return None
    if side == "long" and stop_price >= entry_price:
        return None
    if side == "short" and stop_price <= entry_price:
        return None

    reward_risk = abs(target_prices[-1] - entry_price) / risk if risk > 0 else 0.0
    if reward_risk < resolved.min_reward_risk:
        return None

    return {
        "side": side,
        "pattern_type": pattern_type,
        "divergence_type": divergence["type"],
        "entry_price": entry_price,
        "stop_price": float(stop_price),
        "take_profit": float(target_prices[-1]),
        "target_prices": [float(target) for target in target_prices],
        "target_weights": _divergence_volume_target_weights(resolved, len(target_prices)),
        "invalidation_price": float(invalidation_price),
        "risk_reward": float(reward_risk),
        "fibonacci_level": float(fib["level"]),
        "fibonacci_price": float(fib["price"]),
        "fibonacci_orientation": str(fib["orientation"]),
        "swing_high": float(fib["swing_high"]),
        "swing_low": float(fib["swing_low"]),
        "volume_ratio": float(volume / volume_sma),
        "entry_model": "stop_breakout_confirmed_market_entry",
        "buffer": float(buffer),
        "target_model": "1R/1.5R/2R/2.5R",
        "first_pivot_price": float(divergence["first_pivot_price"]),
        "second_pivot_price": float(divergence["second_pivot_price"]),
        "first_pivot_rsi": float(divergence["first_pivot_rsi"]),
        "second_pivot_rsi": float(divergence["second_pivot_rsi"]),
    }


def _divergence_volume_target_reached(side: str, row: pd.Series, target_price: float) -> bool:
    if side == "long":
        return float(row["high"]) >= target_price
    return float(row["low"]) <= target_price


def _divergence_volume_stop_reached(side: str, row: pd.Series, stop_price: float) -> bool:
    if side == "long":
        return float(row["low"]) <= stop_price
    return float(row["high"]) >= stop_price


def _divergence_volume_trade_pnl_pct(position: dict, exit_price: float) -> float:
    total_return = float(position["realized_return"]) + float(position["remaining_weight"]) * _hybrid_directional_return(
        str(position["side"]),
        float(position["entry"]),
        exit_price,
    )
    return total_return * (1 - 0.0015) * 100


def _backtest_divergence_volume_reversal(
    df: pd.DataFrame,
    *,
    config: DivergenceVolumeConfig | None = None,
    setup_key: str = "divergence-and-volume-4h",
) -> BacktestResult:
    resolved_config = get_divergence_volume_config(config)
    view = prepare_divergence_volume_dataset(df, resolved_config)
    trades: list[dict] = []
    position: dict | None = None
    min_rows = max(resolved_config.divergence_lookback, resolved_config.volume_avg_period, resolved_config.rsi_period) + 3

    for i in range(min_rows, len(view)):
        row = view.iloc[i]
        if position is None:
            signal = calculate_divergence_volume_signal(view.iloc[: i + 1], config=resolved_config)
            if signal is None:
                continue
            position = {
                "side": str(signal["side"]),
                "entry": float(signal["entry_price"]),
                "entry_index": i,
                "stop_price": float(signal["stop_price"]),
                "target_prices": [float(target) for target in signal["target_prices"]],
                "target_weights": [float(weight) for weight in signal["target_weights"]],
                "invalidation_price": float(signal["invalidation_price"]),
                "realized_return": 0.0,
                "remaining_weight": 1.0,
                "targets_hit": 0,
                "pattern_type": str(signal["pattern_type"]),
                "risk_reward": float(signal["risk_reward"]),
            }
            continue

        side = str(position["side"])
        bars_open = i - int(position["entry_index"])
        exit_price: float | None = None
        exit_reason = ""

        current_stop = float(position["entry"]) if int(position["targets_hit"]) > 0 else float(position["stop_price"])
        if _divergence_volume_stop_reached(side, row, current_stop):
            exit_price = current_stop
            exit_reason = "stop_breakeven" if int(position["targets_hit"]) > 0 else "stop"
        else:
            targets = list(position["target_prices"])
            weights = list(position["target_weights"])
            while int(position["targets_hit"]) < len(targets):
                target_index = int(position["targets_hit"])
                target_price = float(targets[target_index])
                if not _divergence_volume_target_reached(side, row, target_price):
                    break
                target_weight = float(weights[target_index])
                position["realized_return"] += target_weight * _hybrid_directional_return(side, float(position["entry"]), target_price)
                position["remaining_weight"] = max(0.0, float(position["remaining_weight"]) - target_weight)
                position["targets_hit"] = target_index + 1

            if int(position["targets_hit"]) >= len(targets):
                exit_price = float(targets[-1])
                exit_reason = "target_final"
            else:
                close = float(row["close"])
                invalidated = (side == "long" and close <= float(position["invalidation_price"])) or (
                    side == "short" and close >= float(position["invalidation_price"])
                )
                if invalidated:
                    exit_price = close
                    exit_reason = "invalidation"
                elif bars_open >= resolved_config.max_hold_bars:
                    exit_price = close
                    exit_reason = "timeout"

        if exit_price is not None:
            trades.append(
                {
                    "pnl_pct": _divergence_volume_trade_pnl_pct(position, exit_price),
                    "bars": bars_open,
                    "side": side,
                    "exit_reason": exit_reason,
                    "targets_hit": int(position["targets_hit"]),
                }
            )
            position = None

    if position is not None:
        last_close = float(view.iloc[-1]["close"])
        trades.append(
            {
                "pnl_pct": _divergence_volume_trade_pnl_pct(position, last_close),
                "bars": len(view) - 1 - int(position["entry_index"]),
                "side": str(position["side"]),
                "exit_reason": "end_of_data",
                "targets_hit": int(position["targets_hit"]),
            }
        )

    return _calc_metrics(
        trades,
        SETUP_CATALOG[normalize_setup_key(setup_key)],
        notes=(
            "divergence-and-volume "
            f"lookback={resolved_config.divergence_lookback} "
            f"fib_lookback={resolved_config.fibonacci_lookback} "
            f"rsi_delta={resolved_config.rsi_delta:.2f} "
            f"fib_tol_atr={resolved_config.fibonacci_tolerance_atr:.2f} "
            f"targets=1R/1.5R/2R/2.5R "
            f"max_hold={resolved_config.max_hold_bars}"
        ),
    )


def calculate_triangle_breakout_signal(
    df: pd.DataFrame,
    config: TriangleBreakoutConfig | None = None,
) -> dict | None:
    resolved_config = get_triangle_breakout_config(config)
    if len(df) < 24:
        return None

    recent = df.tail(40).reset_index(drop=True)
    if recent[["high", "low", "close", "atr14", "volume_sma20"]].isna().any().any():
        return None

    pivot_window = resolved_config.pivot_window
    if len(recent) <= pivot_window * 2:
        return None
    pivot_highs: list[tuple[int, float]] = []
    pivot_lows: list[tuple[int, float]] = []
    for idx in range(pivot_window, len(recent) - pivot_window):
        high_val = float(recent.iloc[idx]["high"])
        low_val = float(recent.iloc[idx]["low"])
        if high_val >= float(recent.iloc[idx - pivot_window: idx + pivot_window + 1]["high"].max()):
            pivot_highs.append((idx, high_val))
        if low_val <= float(recent.iloc[idx - pivot_window: idx + pivot_window + 1]["low"].min()):
            pivot_lows.append((idx, low_val))

    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return None

    high_a, high_b = pivot_highs[-2], pivot_highs[-1]
    low_a, low_b = pivot_lows[-2], pivot_lows[-1]
    if high_b[0] == high_a[0] or low_b[0] == low_a[0]:
        return None

    high_slope = (high_b[1] - high_a[1]) / (high_b[0] - high_a[0])
    low_slope = (low_b[1] - low_a[1]) / (low_b[0] - low_a[0])
    current_index = len(recent) - 1
    upper_now = high_b[1] + high_slope * (current_index - high_b[0])
    lower_now = low_b[1] + low_slope * (current_index - low_b[0])
    if upper_now <= lower_now:
        return None

    overlap_start = max(high_a[0], low_a[0])
    upper_start = high_b[1] + high_slope * (overlap_start - high_b[0])
    lower_start = low_b[1] + low_slope * (overlap_start - low_b[0])
    start_width = upper_start - lower_start
    current_width = upper_now - lower_now
    if (
        start_width <= 0
        or current_width <= 0
        or current_width >= start_width * resolved_config.contraction_max_ratio
    ):
        return None

    atr = float(recent.iloc[-1]["atr14"])
    flat_threshold = atr * resolved_config.flat_threshold_atr_mult
    slope_threshold = atr * resolved_config.slope_threshold_atr_mult
    pattern_type = ""
    if abs(high_slope) <= flat_threshold and low_slope > slope_threshold:
        pattern_type = "ascending"
    elif high_slope < -slope_threshold and abs(low_slope) <= flat_threshold:
        pattern_type = "descending"
    elif high_slope < -slope_threshold and low_slope > slope_threshold:
        pattern_type = "symmetric"
    else:
        return None

    row = recent.iloc[-1]
    volume_ok = float(row["volume"]) > float(row["volume_sma20"]) * resolved_config.volume_multiplier
    breakout_buffer = atr * resolved_config.breakout_buffer_atr_mult
    close = float(row["close"])
    height = max(start_width, atr)

    if volume_ok and close > upper_now + breakout_buffer:
        stop_price = max(lower_now, close - (atr * resolved_config.stop_atr_mult))
        return {
            "side": "long",
            "pattern_type": pattern_type,
            "upper_bound": float(upper_now),
            "lower_bound": float(lower_now),
            "target_price": float(close + height),
            "stop_price": float(stop_price),
            "pattern_height": float(height),
        }
    if volume_ok and close < lower_now - breakout_buffer:
        stop_price = min(upper_now, close + (atr * resolved_config.stop_atr_mult))
        return {
            "side": "short",
            "pattern_type": pattern_type,
            "upper_bound": float(upper_now),
            "lower_bound": float(lower_now),
            "target_price": float(close - height),
            "stop_price": float(stop_price),
            "pattern_height": float(height),
        }
    return None


def _backtest_triangle_breakout(
    df: pd.DataFrame,
    *,
    config: TriangleBreakoutConfig | None = None,
) -> BacktestResult:
    resolved_config = get_triangle_breakout_config(config)
    trades: list[dict] = []
    position: dict | None = None

    for i in range(24, len(df)):
        window = df.iloc[: i + 1]
        row = df.iloc[i]
        if position is None:
            signal = calculate_triangle_breakout_signal(window, config=resolved_config)
            if signal is None:
                continue
            position = {
                "side": signal["side"],
                "entry": float(row["close"]),
                "entry_index": i,
                "upper_bound": float(signal["upper_bound"]),
                "lower_bound": float(signal["lower_bound"]),
                "target_price": float(signal["target_price"]),
                "stop_price": float(signal["stop_price"]),
            }
            continue

        bars_open = i - position["entry_index"]
        prev_close = float(df.iloc[i - 1]["close"]) if i > 0 else float(row["close"])
        current_close = float(row["close"])
        inside_prev = position["lower_bound"] <= prev_close <= position["upper_bound"]
        inside_curr = position["lower_bound"] <= current_close <= position["upper_bound"]

        exit_price = None
        if inside_prev and inside_curr:
            exit_price = current_close
        elif position["side"] == "long":
            if float(row["low"]) <= position["stop_price"]:
                exit_price = float(position["stop_price"])
            elif float(row["high"]) >= position["target_price"]:
                exit_price = float(position["target_price"])
        else:
            if float(row["high"]) >= position["stop_price"]:
                exit_price = float(position["stop_price"])
            elif float(row["low"]) <= position["target_price"]:
                exit_price = float(position["target_price"])

        if exit_price is not None:
            pnl_pct = _hybrid_directional_return(position["side"], position["entry"], exit_price)
            trades.append({"pnl_pct": pnl_pct * (1 - 0.0015) * 100, "bars": bars_open, "side": position["side"]})
            position = None

    if position is not None:
        last_close = float(df.iloc[-1]["close"])
        pnl_pct = _hybrid_directional_return(position["side"], position["entry"], last_close)
        trades.append({"pnl_pct": pnl_pct * (1 - 0.0015) * 100, "bars": len(df) - 1 - position["entry_index"], "side": position["side"]})

    return _calc_metrics(
        trades,
        SETUP_CATALOG["grid-strict"],
        notes=(
            "triangle "
            f"pivot={resolved_config.pivot_window} "
            f"contract<={resolved_config.contraction_max_ratio:.2f} "
            f"vol>={resolved_config.volume_multiplier:.2f}x "
            f"buffer={resolved_config.breakout_buffer_atr_mult:.2f}atr "
            f"stop={resolved_config.stop_atr_mult:.2f}atr"
        ),
    )


def _backtest_funding_arb(
    df: pd.DataFrame,
    *,
    config: FundingArbConfig | None = None,
) -> BacktestResult:
    resolved_config = get_funding_arb_config(config)
    if df.attrs.get("source") == "synthetic":
        return _calc_metrics(
            [],
            SETUP_CATALOG["funding-arb"],
            notes="funding-arb requer historico real de funding/spread; simulacao sintetica desativada",
        )
    trades: list[dict] = []
    position: dict | None = None

    for i in range(20, len(df)):
        row = df.iloc[i]
        funding_rate = float(row["funding_rate_8h"])
        basis_bps = abs(float(row["synthetic_basis_bps"]))

        if position is None:
            if abs(funding_rate) < resolved_config.min_rate:
                continue
            position = {
                "side": "long" if funding_rate > 0 else "short",
                "entry_index": i,
                "carry_pct": 0.0,
                "entry_funding_rate": funding_rate,
            }
            continue

        position["carry_pct"] += abs(funding_rate) * 100
        bars_open = i - position["entry_index"]
        sign_flipped = funding_rate * position["entry_funding_rate"] < 0
        if (
            abs(funding_rate) <= resolved_config.exit_rate
            or sign_flipped
            or bars_open >= resolved_config.max_hold_intervals
            or basis_bps >= resolved_config.max_spread_bps
        ):
            pnl_pct = position["carry_pct"] - 0.10
            trades.append({"pnl_pct": pnl_pct, "bars": bars_open, "side": position["side"]})
            position = None

    if position is not None:
        pnl_pct = position["carry_pct"] - 0.10
        trades.append({"pnl_pct": pnl_pct, "bars": len(df) - 1 - position["entry_index"], "side": position["side"]})

    return _calc_metrics(
        trades,
        SETUP_CATALOG["funding-arb"],
        notes=(
            f"Funding arb sintetico | entry>={resolved_config.min_rate:.5f} | "
            f"exit<={resolved_config.exit_rate:.5f} | max_hold={resolved_config.max_hold_intervals} intervals "
            f"| spread<={resolved_config.max_spread_bps:.1f}bps"
        ),
    )


def _backtest_funding_history(
    df: pd.DataFrame,
    *,
    config: FundingArbConfig,
    result_key: str,
    result_label: str,
) -> BacktestResult:
    trades: list[dict] = []
    position: dict | None = None

    for i in range(len(df)):
        row = df.iloc[i]
        funding_rate = float(row["funding_rate"])
        if position is None:
            if abs(funding_rate) < config.min_rate:
                continue
            position = {
                "side": "long" if funding_rate > 0 else "short",
                "entry_index": i,
                "carry_pct": 0.0,
                "entry_funding_rate": funding_rate,
            }
            continue

        position["carry_pct"] += abs(funding_rate) * 100
        bars_open = i - position["entry_index"]
        sign_flipped = funding_rate * position["entry_funding_rate"] < 0
        if abs(funding_rate) <= config.exit_rate or sign_flipped or bars_open >= config.max_hold_intervals:
            trades.append({"pnl_pct": position["carry_pct"] - 0.10, "bars": bars_open, "side": position["side"]})
            position = None

    if position is not None:
        trades.append({"pnl_pct": position["carry_pct"] - 0.10, "bars": len(df) - 1 - position["entry_index"], "side": position["side"]})

    return _calc_metrics(
        trades,
        SetupDefinition(
            key=result_key,
            label=result_label,
            description=SETUP_CATALOG["funding-arb"].description,
            entry_rule=SETUP_CATALOG["funding-arb"].entry_rule,
            exit_rule=SETUP_CATALOG["funding-arb"].exit_rule,
            profile=SETUP_CATALOG["funding-arb"].profile,
            timeframe="8h",
        ),
        notes=(
            f"Funding arb real | entry>={config.min_rate:.5f} | "
            f"exit<={config.exit_rate:.5f} | max_hold={config.max_hold_intervals} intervals "
            f"| spread_guard={config.max_spread_bps:.1f}bps"
        ),
    )


def _backtest_hybrid(
    df: pd.DataFrame,
    *,
    result_key: str = "hybrid",
    result_label: str | None = None,
    profile_key: str | None = None,
) -> BacktestResult:
    definition = SETUP_CATALOG["hybrid"]
    resolved_profile = normalize_hybrid_profile(profile_key)
    profile = HYBRID_PROFILE_MAP[resolved_profile]
    risk = _build_hybrid_risk_state(resolved_profile)
    open_positions: list[_HybridPosition] = []
    trades: list[dict] = []

    for i in range(50, len(df)):
        row = df.iloc[i]
        timestamp = pd.Timestamp(row["timestamp"])
        risk.sync_periods(timestamp)

        if row[["rsi14", "stoch_k", "atr14", "ema50", "volume_sma20"]].isna().any():
            continue

        triggered_cooldown = False
        remaining_positions: list[_HybridPosition] = []
        for position in open_positions:
            closed_trade = _evaluate_hybrid_exit(position, row=row, current_index=i)
            if closed_trade is None:
                remaining_positions.append(position)
                continue

            triggered_cooldown = risk.register_close(closed_trade["pnl_usd"]) or triggered_cooldown
            trades.append(closed_trade)

        open_positions = remaining_positions

        if triggered_cooldown:
            continue

        if risk.cooldown_bars_remaining > 0:
            risk.consume_cooldown_bar()
            continue

        if not risk.can_open(len(open_positions)):
            continue

        if _hybrid_long_signal(row):
            open_positions.append(
                _HybridPosition(
                    side="long",
                    entry_price=float(row["close"]),
                    entry_time=timestamp,
                    entry_index=i,
                    position_size_usd=risk.position_size(),
                    equity_snapshot=risk.current_equity,
                    stop_loss=float(row["close"] - row["atr14"] * risk.stop_loss_atr_mult),
                    take_profit=float(row["close"] + row["atr14"] * risk.take_profit_atr_mult),
                )
            )
        elif _hybrid_short_signal(row):
            open_positions.append(
                _HybridPosition(
                    side="short",
                    entry_price=float(row["close"]),
                    entry_time=timestamp,
                    entry_index=i,
                    position_size_usd=risk.position_size(),
                    equity_snapshot=risk.current_equity,
                    stop_loss=float(row["close"] + row["atr14"] * risk.stop_loss_atr_mult),
                    take_profit=float(row["close"] - row["atr14"] * risk.take_profit_atr_mult),
                )
            )

    if open_positions:
        last_row = df.iloc[-1]
        for position in open_positions:
            trades.append(_close_hybrid_position(position, exit_price=float(last_row["close"]), exit_reason="EOD_EXIT", current_index=len(df) - 1))

    result = _calc_metrics(
        trades,
        SetupDefinition(
            key=result_key,
            label=result_label or definition.label,
            description=definition.description,
            entry_rule=definition.entry_rule,
            exit_rule=definition.exit_rule,
            profile=definition.profile,
            timeframe=definition.timeframe,
        ),
        notes=(
            f"Hybrid 4h | profile={profile.key}({profile.label}) | "
            f"risk {profile.position_fraction * 100:.1f}% | "
            f"SL ATRx{profile.stop_loss_atr_mult:.1f} | "
            f"TP ATRx{profile.take_profit_atr_mult:.1f} | "
            f"max_positions={profile.max_open_positions} | fee 0.2%"
        ),
    )
    return result


def _hybrid_15m_profile_params(profile_key: str | None) -> tuple[float, float, int]:
    resolved = normalize_hybrid_profile(profile_key)
    params = {
        "conservative": (0.7, 2.1, 6),
        "moderate": (0.8, 2.4, 8),
        "degen": (1.0, 3.0, 10),
    }
    return params[resolved]


def _hybrid_15m_pol_context(df: pd.DataFrame, index: int, side: str) -> bool:
    if index < 12:
        return False

    compression = df.iloc[index - 12 : index - 4]
    impulse = df.iloc[index - 4 : index]
    current = df.iloc[index]
    required_cols = ["open", "high", "low", "close", "ema9", "ema21", "atr14"]
    if compression[required_cols].isna().any().any() or impulse[required_cols].isna().any().any():
        return False
    if current[required_cols].isna().any():
        return False

    atr_ref = max(float(compression["atr14"].mean()), float(current["atr14"]), 1e-9)
    compression_high = float(compression["high"].max())
    compression_low = float(compression["low"].min())
    compression_range = compression_high - compression_low
    is_lateral = compression_range <= atr_ref * 4.0
    close = float(current["close"])
    ema9 = float(current["ema9"])
    ema21 = float(current["ema21"])
    open_price = float(current["open"])
    pullback_band = atr_ref * 0.35

    if side == "long":
        had_impulse = float(impulse["high"].max()) >= compression_high + atr_ref * 0.6
        near_pol = abs(close - ema21) <= pullback_band and float(current["low"]) <= ema21 + atr_ref * 0.15
        rejection = close > open_price and close >= ema9 - atr_ref * 0.20
        return is_lateral and had_impulse and near_pol and rejection

    had_impulse = float(impulse["low"].min()) <= compression_low - atr_ref * 0.6
    near_pol = abs(close - ema21) <= pullback_band and float(current["high"]) >= ema21 - atr_ref * 0.15
    rejection = close < open_price and close <= ema9 + atr_ref * 0.20
    return is_lateral and had_impulse and near_pol and rejection


def _hybrid_15m_long_signal(df: pd.DataFrame, index: int) -> bool:
    row = df.iloc[index]
    return (
        row["ema9"] > row["ema21"]
        and row["macd"] > row["macd_signal"]
        and row["close"] > row["ema21"]
        and row["rsi14"] < 45
        and row["stoch_k"] < 35
        and row["volume"] > row["volume_sma20"] * 1.05
        and _hybrid_15m_pol_context(df, index, "long")
    )


def _hybrid_15m_short_signal(df: pd.DataFrame, index: int) -> bool:
    row = df.iloc[index]
    return (
        row["ema9"] < row["ema21"]
        and row["macd"] < row["macd_signal"]
        and row["close"] < row["ema21"]
        and row["rsi14"] > 55
        and row["stoch_k"] > 65
        and row["volume"] > row["volume_sma20"] * 1.05
        and _hybrid_15m_pol_context(df, index, "short")
    )


def _evaluate_hybrid_15m_exit(
    position: _HybridPosition,
    *,
    row: pd.Series,
    current_index: int,
    max_bars: int,
) -> dict | None:
    bars_open = current_index - position.entry_index
    if position.side == "long":
        if row["low"] <= position.stop_loss:
            return _close_hybrid_position(position, exit_price=position.stop_loss, exit_reason="SCALP_SL_HIT", current_index=current_index)
        if row["high"] >= position.take_profit:
            return _close_hybrid_position(position, exit_price=position.take_profit, exit_reason="SCALP_TP_HIT", current_index=current_index)
        if row["rsi14"] > 58 or row["stoch_k"] > 78:
            return _close_hybrid_position(position, exit_price=float(row["close"]), exit_reason="SCALP_MANUAL_EXIT", current_index=current_index)
    else:
        if row["high"] >= position.stop_loss:
            return _close_hybrid_position(position, exit_price=position.stop_loss, exit_reason="SCALP_SL_HIT", current_index=current_index)
        if row["low"] <= position.take_profit:
            return _close_hybrid_position(position, exit_price=position.take_profit, exit_reason="SCALP_TP_HIT", current_index=current_index)
        if row["rsi14"] < 42 or row["stoch_k"] < 22:
            return _close_hybrid_position(position, exit_price=float(row["close"]), exit_reason="SCALP_MANUAL_EXIT", current_index=current_index)
    if max_bars > 0 and bars_open >= max_bars:
        return _close_hybrid_position(position, exit_price=float(row["close"]), exit_reason="SCALP_TIMEOUT", current_index=current_index)
    return None


def _backtest_hybrid_15m(
    df: pd.DataFrame,
    *,
    result_key: str = "hybrid-15m",
    result_label: str | None = None,
    profile_key: str | None = None,
) -> BacktestResult:
    definition = SETUP_CATALOG["hybrid-15m"]
    resolved_profile = normalize_hybrid_profile(profile_key)
    profile = HYBRID_PROFILE_MAP[resolved_profile]
    stop_loss_atr_mult, take_profit_atr_mult, max_bars = _hybrid_15m_profile_params(resolved_profile)
    risk = _build_hybrid_risk_state(resolved_profile)
    open_positions: list[_HybridPosition] = []
    trades: list[dict] = []

    for i in range(50, len(df)):
        row = df.iloc[i]
        timestamp = pd.Timestamp(row["timestamp"])
        risk.sync_periods(timestamp)

        if row[["ema9", "ema21", "macd", "macd_signal", "rsi14", "stoch_k", "atr14", "volume_sma20"]].isna().any():
            continue

        triggered_cooldown = False
        remaining_positions: list[_HybridPosition] = []
        for position in open_positions:
            closed_trade = _evaluate_hybrid_15m_exit(position, row=row, current_index=i, max_bars=max_bars)
            if closed_trade is None:
                remaining_positions.append(position)
                continue
            triggered_cooldown = risk.register_close(closed_trade["pnl_usd"]) or triggered_cooldown
            trades.append(closed_trade)

        open_positions = remaining_positions

        if triggered_cooldown:
            continue
        if risk.cooldown_bars_remaining > 0:
            risk.consume_cooldown_bar()
            continue
        if not risk.can_open(len(open_positions)):
            continue

        if _hybrid_15m_long_signal(df, i):
            open_positions.append(
                _HybridPosition(
                    side="long",
                    entry_price=float(row["close"]),
                    entry_time=timestamp,
                    entry_index=i,
                    position_size_usd=risk.position_size(),
                    equity_snapshot=risk.current_equity,
                    stop_loss=float(row["close"] - row["atr14"] * stop_loss_atr_mult),
                    take_profit=float(row["close"] + row["atr14"] * take_profit_atr_mult),
                )
            )
        elif _hybrid_15m_short_signal(df, i):
            open_positions.append(
                _HybridPosition(
                    side="short",
                    entry_price=float(row["close"]),
                    entry_time=timestamp,
                    entry_index=i,
                    position_size_usd=risk.position_size(),
                    equity_snapshot=risk.current_equity,
                    stop_loss=float(row["close"] + row["atr14"] * stop_loss_atr_mult),
                    take_profit=float(row["close"] - row["atr14"] * take_profit_atr_mult),
                )
            )

    if open_positions:
        last_row = df.iloc[-1]
        for position in open_positions:
            trades.append(_close_hybrid_position(position, exit_price=float(last_row["close"]), exit_reason="EOD_EXIT", current_index=len(df) - 1))

    return _calc_metrics(
        trades,
        SetupDefinition(
            key=result_key,
            label=result_label or definition.label,
            description=definition.description,
            entry_rule=definition.entry_rule,
            exit_rule=definition.exit_rule,
            profile=definition.profile,
            timeframe=definition.timeframe,
        ),
        notes=(
            f"Hybrid 15m scalp | profile={profile.key}({profile.label}) | "
            f"risk {profile.position_fraction * 100:.1f}% | "
            f"SL ATRx{stop_loss_atr_mult:.1f} | "
            f"TP ATRx{take_profit_atr_mult:.1f} | "
            f"timeout={max_bars} barras | fee 0.2%"
        ),
    )


def _hybrid_long_signal(row: pd.Series) -> bool:
    return (
        row["rsi14"] < 32
        and row["stoch_k"] < 25
        and row["volume"] > row["volume_sma20"] * 1.2
        and row["close"] > row["ema50"]
    )


def _hybrid_short_signal(row: pd.Series) -> bool:
    return (
        row["rsi14"] > 68
        and row["stoch_k"] > 75
        and row["volume"] > row["volume_sma20"] * 1.2
        and row["close"] < row["ema50"]
    )


def _evaluate_hybrid_exit(
    position: _HybridPosition,
    *,
    row: pd.Series,
    current_index: int,
) -> dict | None:
    if position.side == "long":
        if row["low"] <= position.stop_loss:
            return _close_hybrid_position(position, exit_price=position.stop_loss, exit_reason="SL_HIT", current_index=current_index)
        if row["high"] >= position.take_profit:
            return _close_hybrid_position(position, exit_price=position.take_profit, exit_reason="TP_HIT", current_index=current_index)
        if row["rsi14"] > 60 or row["stoch_k"] > 80:
            return _close_hybrid_position(position, exit_price=float(row["close"]), exit_reason="MANUAL_EXIT", current_index=current_index)
        return None

    if row["high"] >= position.stop_loss:
        return _close_hybrid_position(position, exit_price=position.stop_loss, exit_reason="SL_HIT", current_index=current_index)
    if row["low"] <= position.take_profit:
        return _close_hybrid_position(position, exit_price=position.take_profit, exit_reason="TP_HIT", current_index=current_index)
    if row["rsi14"] < 40 or row["stoch_k"] < 20:
        return _close_hybrid_position(position, exit_price=float(row["close"]), exit_reason="MANUAL_EXIT", current_index=current_index)
    return None


def _close_hybrid_position(
    position: _HybridPosition,
    *,
    exit_price: float,
    exit_reason: str,
    current_index: int,
) -> dict:
    gross_return = _hybrid_directional_return(position.side, position.entry_price, exit_price)
    gross_pnl_usd = position.position_size_usd * gross_return
    fees_usd = position.position_size_usd * 0.002
    net_pnl_usd = gross_pnl_usd - fees_usd
    pnl_pct = (net_pnl_usd / position.equity_snapshot) * 100 if position.equity_snapshot > 0 else 0.0
    return {
        "side": position.side,
        "entry_price": position.entry_price,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "bars": current_index - position.entry_index,
        "pnl_pct": pnl_pct,
        "pnl_usd": net_pnl_usd,
    }


def _hybrid_directional_return(side: str, entry_price: float, exit_price: float) -> float:
    normalized = side.strip().lower()
    if normalized == "long":
        return (exit_price - entry_price) / entry_price
    if normalized == "short":
        return (entry_price - exit_price) / entry_price
    raise ValueError(f"lado invalido: {side}")


def _resolve_ccxt_swap_symbol(exchange, symbol: str) -> str:
    stripped = symbol.strip().upper()
    if stripped in getattr(exchange, "markets", {}):
        return stripped
    if hasattr(exchange, "load_markets") and not getattr(exchange, "markets", None):
        exchange.load_markets()
    if stripped in getattr(exchange, "markets", {}):
        return stripped

    if "/" in stripped:
        base = stripped.split("/", 1)[0]
    else:
        base = stripped

    for market_symbol, market in getattr(exchange, "markets", {}).items():
        market_base = str(market.get("base", "")).upper()
        if market_base == "XBT":
            market_base = "BTC"
        if market_base == base and market.get("swap"):
            return market_symbol

    return stripped


def _build_ccxt_exchange(exchange_id: str):
    try:
        import ccxt
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("ccxt nao esta instalado") from exc

    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise ValueError(f"exchange invalida: {exchange_id}")
    exchange = exchange_cls({"enableRateLimit": True})
    if hasattr(exchange, "load_markets"):
        exchange.load_markets()
    return exchange


def _build_hybrid_risk_state(profile_key: str) -> _HybridRiskState:
    profile = HYBRID_PROFILE_MAP[normalize_hybrid_profile(profile_key)]
    return _HybridRiskState(
        initial_equity=10_000.0,
        current_equity=10_000.0,
        position_fraction=profile.position_fraction,
        stop_loss_atr_mult=profile.stop_loss_atr_mult,
        take_profit_atr_mult=profile.take_profit_atr_mult,
        fee_rate=0.002,
        daily_loss_limit_pct=profile.daily_loss_limit_pct,
        monthly_loss_limit_pct=profile.monthly_loss_limit_pct,
        max_open_positions=profile.max_open_positions,
    )


def _calc_metrics(trades: list[dict], definition: SetupDefinition, *, notes: str = "") -> BacktestResult:
    if not trades:
        return BacktestResult(
            key=definition.key,
            setup=definition.label,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_pnl=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            best_trade=0.0,
            worst_trade=0.0,
            max_drawdown=0.0,
            notes=notes or "No trades generated",
        )

    pnls = [float(trade["pnl_pct"]) for trade in trades]
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)
    total_pnl = float(sum(pnls))
    avg_return = total_pnl / len(pnls)

    total_wins = sum(pnl for pnl in pnls if pnl > 0)
    total_losses = abs(sum(pnl for pnl in pnls if pnl < 0))
    profit_factor = total_wins / total_losses if total_losses > 0 else 0.0

    if len(pnls) > 1:
        std_return = pd.Series(pnls).std()
        sharpe = (avg_return / std_return) * (252 ** 0.5) if std_return and std_return > 0 else 0.0
    else:
        sharpe = 0.0

    equity = 10000.0
    peak = equity
    max_dd = 0.0
    for pnl in pnls:
        equity = equity * (1 + pnl / 100)
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown

    return BacktestResult(
        key=definition.key,
        setup=definition.label,
        total_trades=len(trades),
        winning_trades=wins,
        losing_trades=losses,
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        total_pnl=total_pnl,
        avg_pnl=avg_return,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        best_trade=max(pnls),
        worst_trade=min(pnls),
        max_drawdown=max_dd * 100,
        notes=notes,
    )
