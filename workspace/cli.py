"""
CLI da skill `trade-automatizado-openclaw`.

Uso:
    .\\.venv\\Scripts\\python.exe workspace\\cli.py <comando> [opcoes]

Comandos:
    symbols            Lista simbolos disponiveis em ambas as exchanges
    setups             Lista setups operacionais disponiveis
    backtest-operational Roda validacao operacional dos setups
    backtest-hybrid-real Valida o setup HYBRID com candles reais via CCXT
    backtest-low-stoch-real Valida o setup Low Stoch Storm com candles reais via CCXT
    backtest-funding-real Valida o setup Funding Arb com historico real de funding
    calibrate-triangle-real Calibra thresholds reais do Triangle Breakout
    calibrate-funding-real Calibra thresholds reais do Funding Arb
    setup-live-status Mostra os setups live atualmente gerenciados
    setup-live        Roda os setups em loop, abrindo/fechando pares enquanto monitora
    open SYMBOL        Abre ordem hedged DEX+CEX, DEX-only/Nado ou CEX-only/Kraken
    open-venue-pair  Abre par delta-neutro manual entre duas CEXs ou duas DEXs
    status             Mostra delta, PnL e drift do par aberto
    live-status        Mostra posicoes live nas duas exchanges, mesmo sem state.json
    live-hedge         Hedgeia a exposicao live detectada na outra exchange
    live-sync          Monitora e replica abertura manual de um lado no outro
    rebalance          Rebalanceia se drift > threshold
    unwind             Fecha as duas pernas
    farm               Loop: rebalance periodico + stop global
    opportunistic      Usa motor de decisao e ainda hedgeia
    funding            Mostra funding rates atuais em simbolos comuns
    asset-scan         Compara ativos/perps Nado/Kraken e detecta atualizacoes
    kraken-accounts    Mostra os wallets/contas da Kraken e a conta ativa
    simulate           Resume cenarios simulados para 1x/2x/3x
    scenario-matrix    Mostra a matriz completa de cenarios por setup

Configuracao via .env (veja .env.example).
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

EARLY_LIVE_TRADE_COMMANDS = {
    "open",
    "abrir",
    "open-venue-pair",
    "abrir-par-delta-neutro",
    "close-venue-pair",
    "fechar-par-delta-neutro",
    "rebalance",
    "unwind",
    "farm",
    "opportunistic",
    "setup-live",
    "rodar-setups-live",
    "live-hedge",
    "live-sync",
}
LIVE_CONFIRM_ENV = "TRADE_AUTOMATIZADO_CONFIRM_LIVE"
FRIENDLY_LIVE_CONFIRM_ENV = "AUTORIZAR_TRADE_REAL"
FRIENDLY_CONFIRM_ENV = "CONFIRMAR_TRADE_REAL"
LEGACY_LIVE_CONFIRM_ENV = "DELTA_NEUTRAL_CONFIRM_LIVE"
_LIVE_CONFIRM_TRUE_VALUES = {"1", "true", "yes", "sim"}


def _live_trade_confirmed() -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in _LIVE_CONFIRM_TRUE_VALUES
        for name in (FRIENDLY_LIVE_CONFIRM_ENV, FRIENDLY_CONFIRM_ENV, LIVE_CONFIRM_ENV, LEGACY_LIVE_CONFIRM_ENV)
    )


def _early_live_confirmation_guard(argv: list[str]) -> None:
    if not argv:
        return
    cmd = argv[0]
    if cmd not in EARLY_LIVE_TRADE_COMMANDS:
        return
    if any(arg in {"-h", "--help"} for arg in argv):
        return
    if "--dry-run" in argv or "--simular" in argv:
        return
    if _live_trade_confirmed():
        return
    raise SystemExit(
        f"comando de trade bloqueado: defina {FRIENDLY_LIVE_CONFIRM_ENV}=sim apenas na execucao real aprovada "
        f"(tambem aceito: {LIVE_CONFIRM_ENV}=true; alias legado: {LEGACY_LIVE_CONFIRM_ENV}=true)"
    )


_early_live_confirmation_guard(sys.argv[1:])

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from workspace.file_lock import FileLock, LockHeld  # noqa: E402
from workspace.core import (  # noqa: E402
    DEFAULT_CORE_LIQUID_SYMBOLS,
    DEFAULT_FUNDING_ARB_EXIT_RATE,
    DEFAULT_FUNDING_ARB_MAX_HOLD_INTERVALS,
    DEFAULT_FUNDING_ARB_MAX_SPREAD_BPS,
    DEFAULT_FUNDING_ARB_MIN_RATE,
    DEFAULT_FUNDING_ARB_REAL_DAYS,
    DEFAULT_FUNDING_ARB_REAL_SYMBOLS,
    DEFAULT_DIVERGENCE_AND_VOLUME_REAL_DAYS,
    DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS,
    DEFAULT_HYBRID_REAL_SYMBOLS,
    DEFAULT_HYBRID_PROFILE,
    DEFAULT_RISK_PROFILE_LEVERAGE,
    DEFAULT_TRIANGLE_REAL_DAYS,
    DEFAULT_TRIANGLE_REAL_SYMBOLS,
    DEFAULT_LOW_STOCH_REAL_DAYS,
    DEFAULT_LOW_STOCH_REAL_SYMBOLS,
    EXECUTION_MODE_HEDGED,
    EXECUTION_MODE_KRAKEN_ONLY,
    EXECUTION_MODE_NADO_ONLY,
    HYBRID_PROFILE_MAP,
    MARGIN_MODE_CROSS,
    MARGIN_MODE_ISOLATED,
    ManagedSetupState,
    SETUP_CATALOG,
    ACTIVE_SETUP_KEYS,
    CalibrationCandidateResult,
    DeltaNeutralEngine,
    PairState,
    build_scenario_matrix,
    calibrate_funding_real,
    calibrate_triangle_real,
    evaluate_setup_entry,
    evaluate_setup_exit,
    get_funding_arb_config,
    validate_setup_settings,
    get_setup_execution_config,
    is_directional_setup,
    is_hedged_only_setup,
    normalize_execution_mode,
    normalize_hybrid_profile,
    normalize_margin_mode,
    normalize_setup_key,
    parse_setup_selection,
    parse_profiles,
    prepare_market_dataset,
    rank_backtest_results,
    run_divergence_volume_real_backtests,
    run_funding_real_backtests,
    run_hybrid_real_backtests,
    run_operational_backtests,
    run_low_stoch_real_backtests,
    serialize_backtest_results,
    summarize_simulation,
)
from workspace.kraken.kraken_integration import KrakenTrader, _first_float  # noqa: E402
from workspace.nado.units import from_x18  # noqa: E402
from workspace.venues import (  # noqa: E402
    cex_credentials,
    dex_adapter_spec,
    dex_config,
    selected_venues,
    venue_summary,
)
from workspace.venues.ccxt_cex import GenericCcxtTrader  # noqa: E402
from workspace.venues.custom_dex import load_custom_dex_adapter  # noqa: E402
from workspace.venues.hyperliquid_dex import HyperliquidDexTrader  # noqa: E402
from workspace.config import ConfigError, coerce_bool  # noqa: E402
from workspace.venues.sandbox import resolve_sandbox, sandbox_env_names  # noqa: E402

SKILL_ID = "trade-automatizado-openclaw"
LEGACY_SKILL_ID = "delta-neutral-airdrop-farmer"
DEFAULT_STATE_DIR = Path.home() / ".openclaw" / "state" / SKILL_ID
DEFAULT_ENV_FILE = Path.home() / ".config" / "openclaw" / f"{SKILL_ID}.env"
LEGACY_OPENCLAW_STATE_DIR = Path.home() / ".openclaw" / "state" / LEGACY_SKILL_ID
STATE_DIR = Path(os.environ.get("DELTA_NEUTRAL_STATE_DIR", DEFAULT_STATE_DIR)).expanduser()
STATE_FILE = STATE_DIR / "state.json"
VENUE_PAIR_STATE_FILE = STATE_DIR / "venue_pair_state.json"
SETUP_LIVE_STATE_FILE = STATE_DIR / "setup_live_state.json"
SETUP_LIVE_STATE_LOCK_FILE = STATE_DIR / "setup_live_state.lock"
# Espera maxima pelo lock do state file antes de desistir (segundos).
SETUP_STATE_LOCK_TIMEOUT = 30.0

CORE_MAJOR_ALLOWLIST_SYMBOLS = ("BTC/USDT", "BTC/USDC", "ETH/USDT", "ETH/USDC")


def _quote_pairs(*bases: str) -> tuple[str, ...]:
    return tuple(f"{base}/{quote}" for base in bases for quote in ("USDT", "USDC"))


DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS = list(_quote_pairs("ETH", "XMR"))
SETUP_LIVE_DEFAULT_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    # Allowlists iniciais vindas de validacao real 4h top-50/ref. CoinGecko (2026-05-15).
    # BTC/ETH em USDT e USDC entram como majors liquidos estruturais.
    # Estas listas sao guardrails: nao geram entrada; apenas limitam onde cada setup pode avaliar sinal.
    "institutional-strict": (
        *CORE_MAJOR_ALLOWLIST_SYMBOLS,
        *_quote_pairs("TAO", "SOL", "BCH", "XMR", "LINK", "ZEC", "DOT", "HBAR", "TRX", "LTC", "ADA"),
    ),
    "bollinger-mean-reversion": (
        *CORE_MAJOR_ALLOWLIST_SYMBOLS,
        *_quote_pairs("SOL", "BCH", "TAO", "ZEC", "HBAR", "XMR", "AVAX", "XRP", "TRX", "DOT", "UNI", "NEAR", "LTC"),
    ),
    "grid-strict": (*CORE_MAJOR_ALLOWLIST_SYMBOLS, *_quote_pairs("HBAR", "SUI", "XMR")),
    "low-stoch-storm": (*CORE_MAJOR_ALLOWLIST_SYMBOLS, *_quote_pairs("SOL", "XRP")),
    "divergence-and-volume-15m": tuple(DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS),
    "divergence-and-volume-1h": tuple(DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS),
    "divergence-and-volume-4h": tuple(DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS),
    "divergence-and-volume": tuple(DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS),
}

TARGET_STOP_MODE_OFF = "off"
TARGET_STOP_MODE_BREAKEVEN_ON_TP1 = "breakeven_on_tp1"
TARGET_STOP_MODE_LADDER = "ladder"
TARGET_STOP_MODE_ALIASES = {
    "": TARGET_STOP_MODE_OFF,
    "off": TARGET_STOP_MODE_OFF,
    "desligado": TARGET_STOP_MODE_OFF,
    "desativado": TARGET_STOP_MODE_OFF,
    "fixo": TARGET_STOP_MODE_OFF,
    "none": TARGET_STOP_MODE_OFF,
    "no": TARGET_STOP_MODE_OFF,
    "nao": TARGET_STOP_MODE_OFF,
    "não": TARGET_STOP_MODE_OFF,
    "breakeven_on_tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "breakeven-on-tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "break_even_on_tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "break-even-on-tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "entrada-no-tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "entrada_no_tp1": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "entrada": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "breakeven": TARGET_STOP_MODE_BREAKEVEN_ON_TP1,
    "ladder": TARGET_STOP_MODE_LADDER,
    "escada": TARGET_STOP_MODE_LADDER,
    "degrau": TARGET_STOP_MODE_LADDER,
    "degraus": TARGET_STOP_MODE_LADDER,
}
TARGET_STOP_MODE_INPUT_CHOICES = tuple(sorted(key for key in TARGET_STOP_MODE_ALIASES if key))

ASSET_SCAN_STATE_FILE = STATE_DIR / "asset_scan_state.json"
LEGACY_OPENCLAW_STATE_FILE = LEGACY_OPENCLAW_STATE_DIR / "state.json"
LEGACY_OPENCLAW_SETUP_LIVE_STATE_FILE = LEGACY_OPENCLAW_STATE_DIR / "setup_live_state.json"
LEGACY_REPO_STATE_FILE = ROOT / "state.json"
LEGACY_REPO_SETUP_LIVE_STATE_FILE = ROOT / "setup_live_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("delta-neutral")
OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or str(Path.home() / ".npm-global" / "bin" / "openclaw")
TRADE_NOTICE_TZ = ZoneInfo(os.environ.get("SETUP_NOTIFY_TIMEZONE", "America/Sao_Paulo") or "America/Sao_Paulo")

EXECUTION_MODE_INPUT_CHOICES = [
    EXECUTION_MODE_HEDGED,
    "hedge",
    "delta_neutral",
    "delta-neutral",
    "delta_neutro",
    "delta-neutro",
    "delta",
    "espelhado",
    "protegido",
    EXECUTION_MODE_NADO_ONLY,
    "nado-only",
    "nado",
    "dex_only",
    "dex-only",
    "dex",
    "somente_dex",
    "somente-dex",
    "so_dex",
    "so-dex",
    "apenas_dex",
    "apenas-dex",
    "nado_dex",
    "nado-dex",
    EXECUTION_MODE_KRAKEN_ONLY,
    "kraken-only",
    "kraken",
    "cex_only",
    "cex-only",
    "cex",
    "somente_cex",
    "somente-cex",
    "so_cex",
    "so-cex",
    "apenas_cex",
    "apenas-cex",
    "kraken_cex",
    "kraken-cex",
]


def _state_file_candidates() -> tuple[Path, ...]:
    if os.environ.get("DELTA_NEUTRAL_STATE_DIR"):
        return (STATE_FILE, LEGACY_REPO_STATE_FILE)
    return (STATE_FILE, LEGACY_OPENCLAW_STATE_FILE, LEGACY_REPO_STATE_FILE)


def _setup_live_state_file_candidates() -> tuple[Path, ...]:
    if os.environ.get("DELTA_NEUTRAL_STATE_DIR"):
        return (SETUP_LIVE_STATE_FILE, LEGACY_REPO_SETUP_LIVE_STATE_FILE)
    return (
        SETUP_LIVE_STATE_FILE,
        LEGACY_OPENCLAW_SETUP_LIVE_STATE_FILE,
        LEGACY_REPO_SETUP_LIVE_STATE_FILE,
    )


@dataclass
class LiveHedgeAction:
    symbol: str
    base: str
    source_exchange: str
    target_exchange: str
    nado_qty: float
    kraken_qty: float
    net_qty: float
    order_qty: float
    order_notional_usd: float
    net_notional_usd: float = 0.0
    is_buy: bool = True
    drift_bps: float = 0.0
    target_mark_price: float = 0.0
    target_min_qty: float = 0.0
    target_min_notional_usd: float = 0.0
    nado_product_id: int | None = None
    kraken_symbol: str = ""
    blocked_reason: str = ""


@dataclass
class SetupOrderPlan:
    setup_key: str
    symbol: str
    execution_mode: str
    venue: str
    margin_mode: str
    leverage: float
    requested_notional_usd: float
    effective_notional_usd: float
    requested_margin_usd: float
    sizing_source: str
    quantity: float
    entry_price: float
    stop_price: float
    take_profit: float
    liquidation_price: float
    liquidation_buffer_pct: float
    can_execute: bool
    blocked_reason: str = ""
    nado_product_id: int = 0
    kraken_symbol: str = ""


def _bool_pt(flag: bool) -> str:
    return "sim" if flag else "nao"


def _clean_literal_env(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.split("#", 1)[0].strip()
    return cleaned or None


def _fmt_percent(rate: float | None) -> str:
    if rate is None:
        return "n/d"
    return _bold_notice_value(f"{rate * 100:.4f}%/8h")


def _load_bool_env(name: str, default: bool) -> bool:
    """Portao booleano lido do ambiente, com vocabulario dos dois lados.

    A versao anterior era `raw.lower() in {"1","true","yes","sim"}`: todo o
    resto caia no `else` implicito e virava `False`. Onde o default e `True`
    -- `NADO_REQUIRE_LINKED_SIGNER` -- isso **desligava a protecao** por um
    typo. E `on`, `s` e `y`, validos no vocabulario que o `sandbox` usa,
    faziam o mesmo: quem aprendeu a escrever `CEX_SANDBOX=on` desligava a
    verificacao de linked signer sem nada dizer.

    Nao declarar continua sendo diferente de declarar errado: ausente ou vazio
    devolve o default, valor irreconhecivel levanta `ConfigError` -- que e um
    `RuntimeError`, entao o `main` o transforma em mensagem, nao em traceback.
    """
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    return coerce_bool(raw, name)


def _load_float_env(name: str, default: float) -> float:
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    return float(raw)


def _load_int_env(name: str, default: int) -> int:
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    return int(raw)


def _load_certainty_env(name: str = "CERTAINTY", default: int = 70) -> int:
    raw = _clean_literal_env(os.environ.get(name))
    if raw is None:
        return default
    cleaned = raw.rstrip("%")
    value = float(cleaned)
    if value <= 1:
        value *= 100
    return int(round(value))


def _load_unique_trend_env(name: str = "UNIQUE_TREND") -> str:
    raw = (_clean_literal_env(os.environ.get(name)) or "").upper()
    if raw in {"LONG", "SHORT"}:
        return raw
    return ""


def _first_env(*names: str) -> str | None:
    for name in names:
        value = _clean_literal_env(os.environ.get(name))
        if value:
            return value
    return None


def _normalize_execution_mode_arg(raw: str | None) -> str:
    if raw is None or not raw.strip():
        return ""
    try:
        return normalize_execution_mode(raw)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _normalize_order_side_arg(raw: str | None) -> str:
    key = (raw or "long").strip().lower().replace("-", "_")
    aliases = {
        "long": "long",
        "comprado": "long",
        "compra": "long",
        "short": "short",
        "vendido": "short",
        "venda": "short",
    }
    normalized = aliases.get(key)
    if normalized is None:
        raise SystemExit(f"lado invalido: {raw}; use comprado/long ou vendido/short")
    return normalized


def _normalize_margin_mode_arg(raw: str | None) -> str:
    if raw is None or not raw.strip():
        return ""
    try:
        return normalize_margin_mode(raw)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _load_optional_float_arg(raw: float | str | None, *env_names: str) -> float:
    if raw is not None:
        return float(raw)
    env_value = _first_env(*env_names)
    if env_value is None:
        return 0.0
    return float(env_value)


def _parse_pct_value(raw: float | str | None) -> float:
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    value = float(text.rstrip("%"))
    if value > 1:
        value /= 100
    if value < 0:
        raise ValueError("percentual nao pode ser negativo")
    return value


def _resolve_stop_loss_pct(raw_pct: float | str | None, preset: str | None = None) -> float:
    if raw_pct is not None:
        return _parse_pct_value(raw_pct)
    key = str(preset or "").strip().lower().replace("-", "_")
    presets = {
        "10": 0.10,
        "10%": 0.10,
        "conservador": 0.10,
        "conservative": 0.10,
        "20": 0.20,
        "20%": 0.20,
        "moderado": 0.20,
        "moderate": 0.20,
        "30": 0.30,
        "30%": 0.30,
        "degen": 0.30,
    }
    return float(presets.get(key, 0.0))


def _stop_price_from_pct(entry_price: float, side: str, pct: float) -> float:
    if entry_price <= 0 or pct <= 0:
        return 0.0
    if side == "long":
        return float(entry_price * (1 - pct))
    return float(entry_price * (1 + pct))


def _take_profit_price_from_pct(entry_price: float, side: str, pct: float) -> float:
    if entry_price <= 0 or pct <= 0:
        return 0.0
    if side == "long":
        return float(entry_price * (1 + pct))
    return float(entry_price * (1 - pct))


def _default_execution_mode_from_env() -> str:
    return _normalize_execution_mode_arg(
        _first_env("EXECUTION_MODE", "DEFAULT_EXECUTION_MODE", "TRADE_EXECUTION_MODE")
    )


def _default_margin_mode_from_env() -> str:
    return _normalize_margin_mode_arg(_first_env("MARGIN_MODE", "DEFAULT_MARGIN_MODE"))


def _default_nado_margin_mode_from_env() -> str:
    return _normalize_margin_mode_arg(_first_env("NADO_MARGIN_MODE", "DEFAULT_NADO_MARGIN_MODE", "DEX_MARGIN_MODE"))


def _default_kraken_margin_mode_from_env() -> str:
    return _normalize_margin_mode_arg(_first_env("KRAKEN_MARGIN_MODE", "DEFAULT_KRAKEN_MARGIN_MODE", "CEX_MARGIN_MODE"))


def _load_nado_owner_private_key() -> str | None:
    return (
        _clean_literal_env(os.environ.get("NADO_OWNER_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("NADO_PRIVATE_KEY"))
        or _clean_literal_env(os.environ.get("PRIVATE_KEY"))
    )


def _parse_symbol_list(raw: str | None, *, default: list[str] | None = None) -> list[str]:
    if not raw or raw.strip().lower() == "all":
        return list(default or [])
    return [chunk.strip().upper() for chunk in raw.split(",") if chunk.strip()]


def _log_active_trade_context(eng: DeltaNeutralEngine) -> None:
    nado_context = getattr(eng.nado, "get_isolation_context", lambda: {})()
    kraken_context = getattr(eng.kraken, "get_isolation_context", lambda: {})()
    kraken_safety = getattr(eng.kraken, "get_trading_safety", lambda **_: {})()
    logger.info(
        "contexto ativo: Nado subaccount=%s mode=%s trade_ready=%s | Kraken account=%s api=%s mode=%s trading=%s",
        nado_context.get("subaccount_name") or "-",
        nado_context.get("signer_mode") or "-",
        _bool_pt(bool(nado_context.get("trade_ready"))),
        kraken_context.get("account") or "-",
        kraken_context.get("api_fingerprint") or "-",
        kraken_context.get("subaccount_mode") or "-",
        (kraken_safety or {}).get("label", "-"),
    )
    if nado_context.get("trade_auth_error"):
        logger.warning("Nado trade guard: %s", nado_context["trade_auth_error"])
    if kraken_safety and kraken_safety.get("reason"):
        logger.info("Kraken trading safety: %s", kraken_safety["reason"])


def _normalize_live_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _live_base_symbol(symbol: str) -> str:
    normalized = _normalize_live_symbol(symbol)
    if "/" in normalized:
        return normalized.split("/", 1)[0]
    return normalized


def _setup_entry_priority_map(setup_priority: list[str] | tuple[str, ...] | None = None) -> dict[str, int]:
    ordered: list[str] = []
    for raw_key in list(setup_priority or ACTIVE_SETUP_KEYS):
        key = normalize_setup_key(str(raw_key or ""))
        if key and key not in ordered:
            ordered.append(key)
    for key in ACTIVE_SETUP_KEYS:
        if key not in ordered:
            ordered.append(key)
    return {key: index for index, key in enumerate(ordered)}


def _prioritized_setup_keys(setup_keys: list[str]) -> list[str]:
    priority = _setup_entry_priority_map(setup_keys)
    indexed: dict[str, int] = {}
    for index, raw_key in enumerate(setup_keys):
        key = normalize_setup_key(str(raw_key or ""))
        if key and key not in indexed:
            indexed[key] = index
    return sorted(indexed, key=lambda key: (priority.get(key, len(priority)), indexed[key]))


def _select_cycle_setup_entries(
    entries: list[tuple[str, str, pd.DataFrame, object]],
    *,
    setup_priority: list[str] | tuple[str, ...] | None = None,
) -> list[tuple[str, str, pd.DataFrame, object]]:
    priority = _setup_entry_priority_map(setup_priority)
    base_order: list[str] = []
    selected_by_base: dict[str, tuple[tuple[int, int], tuple[str, str, pd.DataFrame, object]]] = {}
    for index, entry in enumerate(entries):
        setup_key, symbol, _df, _signal = entry
        base = _live_base_symbol(symbol)
        if not base:
            base = _normalize_live_symbol(symbol)
        if base not in selected_by_base:
            base_order.append(base)
        normalized_setup = normalize_setup_key(setup_key)
        rank = (priority.get(normalized_setup, len(priority)), index)
        current = selected_by_base.get(base)
        if current is None or rank < current[0]:
            selected_by_base[base] = (rank, entry)
    return [selected_by_base[base][1] for base in base_order]


def _live_symbol_matches_allowed(symbol: str, allowed_symbol: str) -> bool:
    allowed = _normalize_live_symbol(allowed_symbol)
    candidate = _normalize_live_symbol(symbol)
    if not allowed:
        return False
    if "/" in allowed:
        return candidate == allowed
    return _live_base_symbol(candidate) == allowed


def _divergence_volume_whitelist_mode() -> str:
    if os.environ.get("SETUP_LIVE_ALLOWLIST_MODE", "").strip().lower() in {"open", "off", "disabled", "false", "0"}:
        return "open"
    raw = os.environ.get("DIVERGENCE_AND_VOLUME_WHITELIST_MODE", "strict").strip().lower()
    if raw in {"open", "off", "disabled", "false", "0"}:
        return "open"
    return "strict"


def _divergence_volume_allowed_bases() -> set[str]:
    symbols = _parse_symbol_list(
        os.environ.get("DIVERGENCE_AND_VOLUME_ALLOWED_SYMBOLS"),
        default=DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS,
    )
    return {_live_base_symbol(symbol) for symbol in symbols}


def _divergence_volume_symbol_allowed(symbol: str) -> bool:
    if _divergence_volume_whitelist_mode() == "open":
        return True
    return _live_base_symbol(symbol) in _divergence_volume_allowed_bases()


def _setup_allowlist_mode() -> str:
    raw = os.environ.get("SETUP_LIVE_ALLOWLIST_MODE", "strict").strip().lower()
    if raw in {"open", "off", "disabled", "false", "0"}:
        return "open"
    return "strict"


def _setup_allowlist_env_key(setup_key: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in setup_key.upper()).strip("_")
    return f"SETUP_LIVE_ALLOWLIST_{safe}"


def _setup_allowed_symbols(setup_key: str) -> list[str]:
    env_key = _setup_allowlist_env_key(setup_key)
    raw = os.environ.get(env_key)
    default = list(SETUP_LIVE_DEFAULT_ALLOWLISTS.get(setup_key, ()))
    symbols = _parse_symbol_list(raw, default=default)
    return [symbol.upper() for symbol in symbols]


def _setup_symbol_allowed(setup_key: str, symbol: str) -> bool:
    if not is_directional_setup(setup_key):
        return True
    if _setup_allowlist_mode() == "open":
        return True
    allowed = _setup_allowed_symbols(setup_key)
    return bool(allowed) and any(_live_symbol_matches_allowed(symbol, item) for item in allowed)


def _setup_allowlist_union(setup_keys: list[str], common_symbols: list[str]) -> list[str]:
    if _setup_allowlist_mode() == "open":
        return common_symbols
    common_by_symbol = {_normalize_live_symbol(symbol): symbol for symbol in common_symbols}
    common_by_base: dict[str, list[str]] = {}
    for symbol in common_symbols:
        common_by_base.setdefault(_live_base_symbol(symbol), []).append(symbol)
    selected: list[str] = []
    for setup_key in setup_keys:
        if not is_directional_setup(setup_key):
            continue
        for allowed in _setup_allowed_symbols(setup_key):
            normalized_allowed = _normalize_live_symbol(allowed)
            if "/" in normalized_allowed:
                matches = [common_by_symbol[normalized_allowed]] if normalized_allowed in common_by_symbol else []
            else:
                matches = common_by_base.get(normalized_allowed, [])
            for common_symbol in matches:
                if common_symbol not in selected:
                    selected.append(common_symbol)
    return selected


def _log_setup_allowlists(setup_keys: list[str]) -> None:
    if _setup_allowlist_mode() == "open":
        logger.warning("setup-live allowlist aberta por SETUP_LIVE_ALLOWLIST_MODE=open; guardrail por setup desativado")
        return
    for setup_key in setup_keys:
        if not is_directional_setup(setup_key):
            continue
        allowed = _setup_allowed_symbols(setup_key)
        logger.info(
            "setup-live allowlist | %s | permitidos=%s",
            setup_key,
            ",".join(allowed) if allowed else "(nenhum; setup fechado)",
        )


def _resolve_setup_live_symbols(
    eng: DeltaNeutralEngine,
    raw_symbol: str,
    setup_keys: list[str],
    *,
    execution_mode: str | None = None,
) -> list[str]:
    raw = (raw_symbol or "").strip().lower()
    common = _resolve_symbols(eng, "all", execution_mode=execution_mode)
    is_hedged_delta_neutral = execution_mode in {None, EXECUTION_MODE_HEDGED}
    if (
        raw == "all"
        and any(is_directional_setup(setup_key) for setup_key in setup_keys)
        and _setup_allowlist_mode() != "open"
        and not is_hedged_delta_neutral
    ):
        raise SystemExit(
            "setup-live bloqueado: --symbol all so e permitido para delta neutro/hedged; "
            "em dex_only/cex_only use --symbol allowlist ou informe simbolo aprovado"
        )
    if raw in {"allowlist", "allowed", "setup-allowlist", "setup_allowlist"}:
        selected = _setup_allowlist_union(setup_keys, common)
        if not selected:
            raise SystemExit("setup-live bloqueado: nenhuma allowlist configurada para os setups selecionados")
        return selected
    return _resolve_symbols(eng, raw_symbol, execution_mode=execution_mode)


def _collect_live_status(eng: DeltaNeutralEngine) -> tuple[list, list, dict[str, dict[str, float]]]:
    nado_positions = getattr(eng.nado, "get_all_positions", lambda: [])()
    kraken_positions = eng.kraken.get_all_positions()
    summary: dict[str, dict[str, float]] = {}

    def ensure(base: str) -> dict[str, float]:
        return summary.setdefault(
            base,
            {
                "nado_notional": 0.0,
                "kraken_notional": 0.0,
                "gross_notional": 0.0,
                "net_notional": 0.0,
                "nado_qty": 0.0,
                "kraken_qty": 0.0,
                "nado_mark": 0.0,
                "kraken_mark": 0.0,
            },
        )

    for position in nado_positions:
        base = _live_base_symbol(position.symbol)
        row = ensure(base)
        signed_notional = position.size * position.mark_price
        row["nado_notional"] += signed_notional
        row["gross_notional"] += abs(signed_notional)
        row["net_notional"] += signed_notional
        row["nado_qty"] += position.size
        row["nado_mark"] = position.mark_price or row["nado_mark"]

    for position in kraken_positions:
        base = _live_base_symbol(position.symbol)
        row = ensure(base)
        signed_notional = position.size * position.mark_price
        row["kraken_notional"] += signed_notional
        row["gross_notional"] += abs(signed_notional)
        row["net_notional"] += signed_notional
        row["kraken_qty"] += position.size
        row["kraken_mark"] = position.mark_price or row["kraken_mark"]

    return nado_positions, kraken_positions, summary


def _dex_label(dex_id: str) -> str:
    normalized = (dex_id or "dex").replace("_", "-").lower()
    if normalized in {"nado", "nado-dex"}:
        return "Nado"
    if normalized in {"hyperliquid", "hyperliquid-dex"}:
        return "Hyperliquid"
    return normalized or "DEX"


def _extract_balance_from_ccxt_payload(balance: dict, candidates: tuple[str, ...]) -> float:
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


def _get_generic_dex_entry_snapshot(eng: DeltaNeutralEngine, dex_id: str) -> dict:
    label = _dex_label(dex_id)
    context = getattr(eng.nado, "get_isolation_context", lambda: {})() or {}
    balance = 0.0
    balance_error = ""
    try:
        get_balance = getattr(eng.nado, "get_balance", None)
        if callable(get_balance):
            try:
                balance = float(get_balance("USDC") or 0.0)
            except TypeError:
                balance = float(get_balance() or 0.0)
        else:
            client = getattr(eng.nado, "client", None)
            fetch_balance = getattr(client, "fetch_balance", None)
            if not callable(fetch_balance):
                raise RuntimeError("adapter nao implementa get_balance/fetch_balance")
            balance = _extract_balance_from_ccxt_payload(fetch_balance(), ("USDC", "USD", "USDT"))
    except Exception as exc:  # noqa: BLE001
        balance_error = f"saldo {label} indisponivel: {exc}"
    trade_ready = context.get("trade_ready")
    return {
        "venue_label": label,
        "health_required": False,
        "trade_ready": bool(trade_ready) if trade_ready is not None else True,
        "trade_auth_error": str(context.get("trade_auth_error") or ""),
        "balance": balance,
        "initial_health": balance,
        "maintenance_health": balance,
        "initial_assets": balance,
        "initial_liabilities": 0.0,
        "maintenance_assets": balance,
        "maintenance_liabilities": 0.0,
        "initial_usage_pct": 0.0,
        "maintenance_usage_pct": 0.0,
        "error": balance_error,
    }


def _get_nado_entry_snapshot(eng: DeltaNeutralEngine) -> dict:
    dex_id = str(getattr(eng, "dex_id", "nado") or "nado").lower()
    if not _is_builtin_nado_dex(dex_id):
        return _get_generic_dex_entry_snapshot(eng, dex_id)
    context = getattr(eng.nado, "get_isolation_context", lambda: {})()
    balance = 0.0
    initial_health = 0.0
    maintenance_health = 0.0
    initial_assets = 0.0
    initial_liabilities = 0.0
    maintenance_assets = 0.0
    maintenance_liabilities = 0.0
    health_error = ""
    try:
        balance = float(getattr(eng.nado, "get_usdt0_balance", lambda: 0.0)() or 0.0)
    except Exception as exc:  # noqa: BLE001
        health_error = f"saldo Nado indisponivel: {exc}"
    try:
        info = eng.nado.client.context.engine_client.get_subaccount_info(eng.nado.subaccount_hex)
        healths = getattr(info, "healths", []) or []
        if len(healths) > 0 and hasattr(healths[0], "health"):
            initial = healths[0]
            initial_health = float(getattr(initial, "health", 0) or 0) / 1e18
            initial_assets = float(getattr(initial, "assets", 0) or 0) / 1e18
            initial_liabilities = float(getattr(initial, "liabilities", 0) or 0) / 1e18
        if len(healths) > 1 and hasattr(healths[1], "health"):
            maintenance = healths[1]
            maintenance_health = float(getattr(maintenance, "health", 0) or 0) / 1e18
            maintenance_assets = float(getattr(maintenance, "assets", 0) or 0) / 1e18
            maintenance_liabilities = float(getattr(maintenance, "liabilities", 0) or 0) / 1e18
    except Exception as exc:  # noqa: BLE001
        health_error = health_error or f"health Nado indisponivel: {exc}"
    initial_usage_pct = (initial_liabilities / initial_assets * 100) if initial_assets > 0 else 0.0
    maintenance_usage_pct = (maintenance_liabilities / maintenance_assets * 100) if maintenance_assets > 0 else 0.0
    return {
        "venue_label": "Nado",
        "health_required": True,
        "trade_ready": bool(context.get("trade_ready")),
        "trade_auth_error": str(context.get("trade_auth_error") or ""),
        "balance": balance,
        "initial_health": initial_health,
        "maintenance_health": maintenance_health,
        "initial_assets": initial_assets,
        "initial_liabilities": initial_liabilities,
        "maintenance_assets": maintenance_assets,
        "maintenance_liabilities": maintenance_liabilities,
        "initial_usage_pct": initial_usage_pct,
        "maintenance_usage_pct": maintenance_usage_pct,
        "error": health_error,
    }


def _resolve_account_margin_budget(
    *,
    equity_usd: float,
    reserve_usd: float,
    reserve_pct: float,
    slots: int,
) -> tuple[float, float, float]:
    if slots <= 0 or equity_usd <= 0:
        return 0.0, 0.0, 0.0
    pct_reserve = equity_usd * max(float(reserve_pct or 0.0), 0.0) / 100
    resolved_reserve = max(float(reserve_usd or 0.0), pct_reserve)
    operational_budget = max(equity_usd - resolved_reserve, 0.0)
    return resolved_reserve, operational_budget, operational_budget / slots if slots > 0 else 0.0


def _normalize_message_target(channel: str, target: str) -> str:
    if channel == "discord" and target and not target.startswith(("channel:", "user:")):
        return f"channel:{target}"
    return target


def _discord_message_prefix() -> str:
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_MENTION", "").strip()
    if raw.lower() in {"0", "false", "no", "nao", "off", "none"}:
        return ""
    if raw.lower() in {"1", "true", "yes", "sim", "everyone"}:
        return "@everyone"
    return raw


def _discord_box_enabled() -> bool:
    # Box/código no Discord fica reservado para eventos de estado já formatados
    # por _format_state_event_notice: operação monitorada, atualização de alvo,
    # stop, fechamento etc. Sinal novo/entrada/cancelamento não deve cair em
    # caixa por padrão, para não divergir do formato editorial do Zeus/Aspira.
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_BOX", "false").strip().lower()
    return raw not in {"0", "false", "no", "nao", "off"}


def _discord_box_style() -> str:
    style = os.environ.get("SETUP_NOTIFY_DISCORD_BOX_STYLE", "code").strip().lower()
    if style in {"quote", "blockquote"}:
        return "quote"
    return "code"


def _box_discord_message(message: str) -> str:
    if not _discord_box_enabled():
        return message
    clean = message.replace("```", "'''")
    if _discord_box_style() == "quote":
        return "\n".join(f"> {line}" if line else ">" for line in clean.splitlines())
    return f"```text\n{clean}\n```"


def _discord_box_allowed_for_message(message: str) -> bool:
    head = "\n".join(line.strip() for line in str(message or "").splitlines() if line.strip())[:240]
    return not any(
        marker in head
        for marker in (
            "🔄 ATUALIZAÇÃO 🔄",
            "⛔ STOP LOSS ATINGIDO ⛔",
            "⛔️ STOP LOSS ATINGIDO ⛔️",
            "🔒 FECHAMENTO MANUAL 🔒",
        )
    )


def _discord_replay_notice_message(message: str) -> bool:
    return not _discord_box_allowed_for_message(message)


def _with_discord_message_prefix(message: str) -> str:
    prefix = _discord_message_prefix()
    clean_message = message
    if prefix and clean_message.startswith(prefix):
        clean_message = clean_message[len(prefix):].lstrip("\n")
    use_box = _discord_box_enabled() and _discord_box_allowed_for_message(clean_message)
    if prefix and use_box and _discord_box_style() == "code":
        return f"{prefix}\n{_box_discord_message(clean_message)}"
    if prefix:
        clean_message = f"{prefix}\n{clean_message}"
    return _box_discord_message(clean_message) if use_box else clean_message


def _discord_native_embed_enabled() -> bool:
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_NATIVE_EMBED", "true").strip().lower()
    return raw not in {"0", "false", "no", "nao", "off"}


def _discord_embed_author() -> str:
    return os.environ.get("SETUP_NOTIFY_DISCORD_EMBED_AUTHOR", "").strip()


def _discord_allowed_mentions(text: str) -> dict:
    clean = str(text or "")
    roles = list(dict.fromkeys(re.findall(r"<@&(\d+)>", clean)))[:25]
    parse = ["everyone"] if clean.strip().startswith("@everyone") else []
    payload: dict[str, Any] = {"parse": parse}
    if roles:
        payload["roles"] = roles
    return payload


def _discord_normalized_symbol_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _discord_entry_search_terms(symbol: str) -> set[str]:
    normalized = _discord_normalized_symbol_text(symbol)
    terms = {normalized} if normalized else set()
    for quote in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            base = normalized[: -len(quote)]
            terms.add(base)
            terms.add(f"{base}{quote}")
    return {term for term in terms if len(term) >= 3}


def _find_recent_discord_entry_message_id(state: "ManagedSetupState") -> str:
    """Backfill do id raiz para updates de trades antigos que nasceram antes do formato canônico.

    O caminho novo persiste `discord_entry_message_id` no estado. Para monitorados já vivos,
    ainda pode faltar esse campo; sem ele, update sai sem reply. Aqui buscamos a última entrada
    recente do mesmo par no canal Discord e reutilizamos como raiz.
    """
    token = _discord_bot_token()
    channel_id = _discord_channel_id(os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "").strip())
    if not token or not channel_id:
        return ""
    terms = _discord_entry_search_terms(getattr(state, "symbol", ""))
    if not terms:
        return ""
    try:
        max_messages = max(25, min(int(os.environ.get("SETUP_NOTIFY_DISCORD_BACKFILL_SCAN_LIMIT", "250")), 500))
    except (TypeError, ValueError):
        max_messages = 250
    before = ""
    scanned = 0
    while scanned < max_messages:
        limit = min(100, max_messages - scanned)
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
        if before:
            url += f"&before={before}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": "trader-low_stoch-notifier",
            },
            method="GET",
        )
        try:
            timeout = int(os.environ.get("SETUP_NOTIFY_TIMEOUT_SECONDS", "75"))
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace") or "[]")
        except Exception as exc:  # noqa: BLE001
            logger.debug("discord backfill de reply falhou: %s", exc)
            return ""
        if not isinstance(payload, list) or not payload:
            return ""
        scanned += len(payload)
        before = str((payload[-1] or {}).get("id") or "").strip()
        for item in payload:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            normalized_content = _discord_normalized_symbol_text(content)
            if not any(marker in normalized_content for marker in ("ANLISETCNICA", "ANALISETCNICA", "ANALISETECNICA")):
                continue
            if not any(term in normalized_content for term in terms):
                continue
            attachments = item.get("attachments") or []
            if not attachments:
                continue
            message_id = str(item.get("id") or "").strip()
            if message_id:
                return message_id
        if not before:
            return ""
    return ""


def _discord_chart_image_path() -> Path | None:
    raw = (
        os.environ.get("SETUP_NOTIFY_CHART_IMAGE_PATH", "").strip()
        or os.environ.get("SETUP_NOTIFY_DISCORD_IMAGE_PATH", "").strip()
    )
    if not raw or raw.lower() in {"0", "false", "no", "nao", "off", "none"}:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _setup_chart_enabled() -> bool:
    raw = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_IMAGE", os.environ.get("SETUP_NOTIFY_CHART_ENABLED", "true")).strip().lower()
    return raw not in {"0", "false", "no", "nao", "off", "none"}


def _render_setup_chart_image(payload: dict[str, Any] | None) -> Path | None:
    explicit = _discord_chart_image_path()
    if explicit is not None:
        return explicit
    if not payload or not _setup_chart_enabled():
        return None
    try:
        from workspace.tradingview_chart import render_tradingview_chart

        return render_tradingview_chart(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("grafico TradingView/static falhou: %s", exc)
    return None


def _discord_multipart_body(payload: dict, image_path: Path) -> tuple[bytes, str]:
    boundary = f"aspira-trade-{int(time.time() * 1000)}"
    filename = image_path.name or "trade-chart.png"
    content_type = mimetypes.guess_type(filename)[0] or "image/png"
    file_bytes = image_path.read_bytes()
    chunks: list[bytes] = []
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
    chunks.append(b"Content-Type: application/json\r\n\r\n")
    chunks.append(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode())
    chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _discord_channel_id(target: str) -> str:
    normalized = _normalize_message_target("discord", target)
    if normalized.startswith("channel:"):
        return normalized.split(":", 1)[1].strip()
    if normalized.isdigit():
        return normalized
    return ""


def _discord_bot_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    if (
        not os.environ.get("SETUP_NOTIFY_ENV_FILE")
        and (os.environ.get("QC_SECRETS_PROXY") or os.environ.get("QC_SERVICE_KEY_NAMES"))
    ):
        return ""
    env_path = Path(os.environ.get("SETUP_NOTIFY_ENV_FILE", DEFAULT_ENV_FILE)).expanduser()
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_BOT_TOKEN":
                return value.strip().strip('"').strip("'")
    except Exception:
        pass
    token = _discord_bot_token_from_openclaw_config()
    if token:
        return token
    return ""


def _discord_bot_token_from_openclaw_config() -> str:
    """Resolve o SecretRef do Discord configurado no OpenClaw, sem gravar segredo em disco.

    A entrega canônica do trade no Discord precisa usar multipart direto para manter
    texto completo + imagem no mesmo post. O adaptador `message` do OpenClaw pode
    chunkar texto longo; por isso reaproveitamos o provider de segredo já existente
    na config do gateway quando `DISCORD_BOT_TOKEN` não está no ambiente local.
    """
    config_path = Path(os.environ.get("OPENCLAW_CONFIG_FILE", "~/.openclaw/openclaw.json")).expanduser()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        token_ref = ((config.get("channels") or {}).get("discord") or {}).get("token") or {}
        if not isinstance(token_ref, dict) or token_ref.get("source") != "exec":
            return ""
        provider_name = str(token_ref.get("provider") or "").strip()
        provider = ((config.get("secrets") or {}).get("providers") or {}).get(provider_name) or {}
        if not isinstance(provider, dict) or provider.get("source") != "exec":
            return ""
        command = str(provider.get("command") or "").strip()
        args = [str(arg) for arg in provider.get("args") or []]
        if not command:
            return ""
        env = {key: value for key, value in os.environ.items() if key in set(provider.get("passEnv") or [])}
        result = subprocess.run(
            [command, *args],
            check=False,
            timeout=int(os.environ.get("SETUP_NOTIFY_SECRET_TIMEOUT_SECONDS", "15")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env or None,
        )
        if result.returncode != 0:
            return ""
        value = result.stdout.strip()
        if provider.get("jsonOnly"):
            payload = json.loads(value)
            secret_id = str(token_ref.get("id") or "value")
            value = str(payload.get(secret_id) or payload.get("value") or "").strip() if isinstance(payload, dict) else ""
        return value
    except Exception:
        return ""


def _discord_embed_color(message: str) -> int:
    text = message.upper()
    if "SHORT" in text or "STOP" in text or "CANCELADA" in text:
        return 0xE74C3C
    if "LONG" in text or "ATINGIDO" in text:
        return 0x2ECC71
    return 0xF1C40F


def _build_discord_embed(message: str) -> dict:
    lines = [line.rstrip() for line in str(message or "").splitlines()]
    title = next((line for line in lines if line.strip()), "🚨 NOVA OPERAÇÃO 🚨")
    body_lines = lines[lines.index(title) + 1 :] if title in lines else lines[1:]
    description = "\n".join(line for line in body_lines if line.strip())[:4096]
    embed = {
        "title": title[:256],
        "description": description or "\u200b",
        "color": _discord_embed_color(message),
    }
    author = _discord_embed_author()
    if author:
        embed["author"] = {"name": author}
    return embed


def _discord_spaced_content(content: str) -> str:
    clean = str(content or "").rstrip()
    if not clean or clean.endswith("\u200b"):
        return clean
    if len(clean) <= 1996:
        return f"{clean}\n\n\u200b"
    return clean


def _discord_plain_content(message: str, prefix: str = "") -> str:
    clean_message = str(message or "").strip()
    clean_prefix = str(prefix or "").strip()
    if clean_prefix and not clean_message.startswith(clean_prefix):
        clean_message = f"{clean_prefix}\n{clean_message}" if clean_message else clean_prefix
    clean_message = _discord_spaced_content(clean_message)
    if len(clean_message) <= 2000:
        return clean_message
    for marker in ("\nDisclaimer:", "\nGerenciamento de risco:"):
        head = clean_message.split(marker, 1)[0].rstrip()
        if head and len(head) <= 1980:
            return f"{head}\n\nTexto encurtado para caber em uma única mensagem do Discord."
    return clean_message[:1970].rstrip() + "\n…"


def _compact_discord_fallback_update(message: str, *, limit: int = 340) -> str:
    """Mantem updates em um unico reply quando o fallback OpenClaw chunkar em 350 chars."""
    clean = str(message or "").strip()
    if len(clean) <= limit or "```" not in clean or "### **" not in clean:
        return clean
    body = clean.replace("```text", "").replace("```", "").strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    title = next((line for line in lines if line.startswith("###")), lines[0] if lines else "🔄 ATUALIZAÇÃO")
    targets = [line for line in lines if line.upper().startswith("ALVO ")][:4]
    pnl = next((line for line in lines if line.startswith("P&L:")), "")
    pnl_amount = next((line for line in lines if line.startswith("P&L Amount:")), "")
    risk = next((line for line in lines if line.startswith("Risco até Stop:")), "")
    reason = ""
    for idx, line in enumerate(lines):
        if "Motivo" in line:
            reason = lines[idx + 1] if idx + 1 < len(lines) else ""
            break
    compact_lines = [title, *targets]
    compact_lines.extend(line for line in (pnl, pnl_amount, risk) if line)
    if reason:
        compact_lines.append(f"Motivo: {reason}")
    compact = "```text\n" + "\n".join(compact_lines) + "\n```"
    if len(compact) <= limit:
        return compact
    keep = []
    for line in compact_lines:
        candidate = "```text\n" + "\n".join([*keep, line]) + "\n```"
        if len(candidate) > limit:
            break
        keep.append(line)
    return "```text\n" + "\n".join(keep) + "\n```"


def _send_discord_native_embed(
    *,
    target: str,
    message: str,
    image_path: Path | None = None,
    reply_to_message_id: str = "",
) -> str | None:
    # Nome mantido por compatibilidade: a entrega correta para o Aspira é texto + imagem,
    # sem card/embed nativo. O anexo aparece abaixo do texto na mesma mensagem.
    token = _discord_bot_token()
    channel_id = _discord_channel_id(target)
    if not token or not channel_id:
        return None
    prefix = _discord_message_prefix()
    content = _discord_plain_content(message, prefix)
    image_path = image_path or _discord_chart_image_path()
    payload = {
        "content": content,
        "allowed_mentions": _discord_allowed_mentions(content),
    }
    clean_reply_to = str(reply_to_message_id or "").strip()
    if clean_reply_to:
        payload["message_reference"] = {
            "message_id": clean_reply_to,
            "channel_id": channel_id,
            "fail_if_not_exists": False,
        }
    if image_path is not None:
        payload["attachments"] = [{"id": 0, "filename": image_path.name}]
        data, boundary = _discord_multipart_body(payload, image_path)
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        content_type = "application/json"
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": content_type,
            "User-Agent": "trader-low_stoch-notifier",
        },
        method="POST",
    )
    try:
        timeout = int(os.environ.get("SETUP_NOTIFY_TIMEOUT_SECONDS", "75"))
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if not 200 <= int(response.status) < 300:
                return None
            try:
                body = response.read().decode("utf-8", errors="replace")
                payload_out = json.loads(body) if body else {}
                message_id = str(payload_out.get("id") or "").strip()
                return message_id or None
            except Exception:  # noqa: BLE001
                return None
    except urllib.error.HTTPError as exc:
        detail = exc.read(200).decode("utf-8", errors="replace")
        logger.warning("discord embed falhou | status=%s | detail=%s", exc.code, detail)
    except Exception as exc:  # noqa: BLE001
        logger.warning("discord embed falhou: %s", exc)
    return None


def _notice_brand_label() -> str:
    return os.environ.get("SETUP_NOTIFY_BRAND", "").strip()


def _bold_notice_value(value: str) -> str:
    clean = str(value or "").strip()
    if not clean or clean == "N/A" or clean.startswith("**"):
        return clean or "N/A"
    return f"**{clean}**"


def _notice_title_line(title: str) -> str:
    clean = str(title or "").strip()
    while clean.startswith("#"):
        clean = clean[1:].lstrip()
    return f"# {clean or 'Atualização'}"


def _notice_subtitle(text: str) -> str:
    return _bold_notice_value(text)


def _notice_header_lines(title: str) -> list[str]:
    brand = _notice_brand_label()
    lines: list[str] = []
    if brand:
        lines.extend([brand, ""])
    lines.extend([_notice_title_line(title), "", ""])
    return lines


def _send_entry_notification(
    *,
    channel: str,
    target: str,
    account: str,
    message: str,
    image_path: Path | None = None,
    reply_to_discord_message_id: str = "",
    reply_to_whatsapp_message_id: str = "",
) -> str | None:
    target = _normalize_message_target(channel, target)
    if not target:
        return None
    if channel == "discord":
        account = account or os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT", "default").strip()
        discord_message_id = _send_discord_native_embed(
            target=target,
            message=message,
            image_path=image_path,
            reply_to_message_id=reply_to_discord_message_id,
        )
        if discord_message_id:
            return discord_message_id
        fallback_openclaw = os.environ.get("SETUP_NOTIFY_FALLBACK_OPENCLAW", "0").strip().lower() in {"1", "true", "yes", "sim"}
        if not fallback_openclaw:
            logger.warning("discord embed falhou; fallback openclaw desativado | target=%s", target)
            return None
        message = _with_discord_message_prefix(message)
        if reply_to_discord_message_id:
            message = _compact_discord_fallback_update(message)
    cmd = [OPENCLAW_BIN, "message", "send", "--json", "--channel", channel, "--target", target, "--message", message]
    if image_path is not None and image_path.is_file():
        cmd.extend(["--media", str(image_path)])
    if channel == "telegram":
        thread_id = os.environ.get("SETUP_NOTIFY_ENTRY_THREAD_ID", "").strip()
        if thread_id:
            cmd.extend(["--thread-id", thread_id])
    if channel == "discord" and reply_to_discord_message_id:
        cmd.extend(["--reply-to", str(reply_to_discord_message_id)])
    if channel == "whatsapp" and reply_to_whatsapp_message_id:
        cmd.extend(["--reply-to", str(reply_to_whatsapp_message_id)])
    if account:
        cmd.extend(["--account", account])
    try:
        timeout = int(os.environ.get("SETUP_NOTIFY_TIMEOUT_SECONDS", "75"))
        result = subprocess.run(cmd, check=False, timeout=timeout, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("notificacao de entrada falhou | channel=%s | target=%s | rc=%s", channel, target, result.returncode)
            if result.stderr:
                logger.debug("notificacao stderr: %s", result.stderr.strip()[:500])
            return None
        try:
            payload_out = json.loads(result.stdout or "{}")
            message_id = str(
                payload_out.get("messageId")
                or payload_out.get("message_id")
                or (payload_out.get("result") or {}).get("messageId")
                or (payload_out.get("result") or {}).get("id")
                or ((payload_out.get("payload") or {}).get("result") or {}).get("messageId")
                or ((payload_out.get("payload") or {}).get("result") or {}).get("id")
                or ""
            ).strip()
            if message_id:
                return message_id
        except Exception:  # noqa: BLE001
            logger.debug("notificacao stdout nao-json: %s", (result.stdout or "").strip()[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning("falha ao enviar notificacao de entrada: %s", exc)
    return None


def _setup_notifications_enabled() -> bool:
    enabled = os.environ.get("SETUP_NOTIFY_ENTRY_ENABLED", "true").strip().lower()
    return enabled not in {"0", "false", "no", "nao", "off"}


def _message_for_entry_channel(channel: str, message: str) -> str:
    if channel == "whatsapp":
        return _format_whatsapp_from_notice(message)
    if channel != "telegram":
        return message
    mention = os.environ.get("SETUP_NOTIFY_ENTRY_TELEGRAM_MENTION", "").strip()
    if not mention:
        return message
    lines = str(message or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.fullmatch(r"<@&\d+>", lines[0].strip()):
        lines[0] = mention
    elif not lines or mention not in lines[0]:
        lines.insert(0, mention)
    return "\n".join(lines)


def _whatsapp_clean_inline(value: str) -> str:
    clean = str(value or "").replace("\u200b", "").strip()
    clean = re.sub(r"^#{1,6}\s+", "", clean).strip()
    clean = clean.replace("**", "").replace("__", "").replace("`", "").strip()
    return clean


def _whatsapp_notice_lines(message: str) -> list[str]:
    return [_whatsapp_clean_inline(line) for line in str(message or "").splitlines()]


def _whatsapp_value_after(lines: list[str], labels: tuple[str, ...]) -> str:
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        comparable = re.sub(r"^[📌🛑💎📊📈⚠️⚡️📝➜✅⏳❌⛔️🚨💰🔒\s]+", "", line).strip()
        for label in labels:
            if comparable.lower().startswith(label.lower()) and ":" in comparable:
                return _whatsapp_clean_inline(comparable.split(":", 1)[1])
    return ""


def _whatsapp_symbol_pair(value: str) -> str:
    clean = _whatsapp_clean_inline(value).upper().split(":", 1)[0].replace("-", "/")
    clean = re.sub(r"\s+", "", clean)
    if "/" in clean:
        base, quote = clean.split("/", 1)
        return f"{base}/{quote or 'USDT'}" if base else clean
    for quote in ("USDT", "USDC", "USD"):
        if clean.endswith(quote) and len(clean) > len(quote):
            return f"{clean[:-len(quote)]}/{quote}"
    return f"{clean}/USDT" if clean and clean != "N/A" else "N/A"


def _whatsapp_pair_from_notice(lines: list[str]) -> str:
    par = _whatsapp_value_after(lines, ("Par",))
    if par:
        return _whatsapp_symbol_pair(par)
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        match = re.search(r"\b([A-Z0-9]{2,20})(?:/)?(USDT|USDC|USD)\b", line.upper())
        if match:
            return _whatsapp_symbol_pair("".join(match.groups()))
        match = re.match(r"^([A-Z0-9]{2,12})\s+aciona\b", line, re.IGNORECASE)
        if match:
            return _whatsapp_symbol_pair(match.group(1))
    return "N/A"


def _whatsapp_setup_timeframe(lines: list[str]) -> tuple[str, str]:
    setup = _whatsapp_value_after(lines, ("Estratégia", "Estrategia", "Setup"))
    timeframe = _whatsapp_value_after(lines, ("Timeframe", "Tempo Gráfico", "Tempo Grafico"))
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        match = re.search(r"Análise Técnica\s*-\s*(.*?)\s*-\s*Time Frame\s*(.+)$", line, re.IGNORECASE)
        if match:
            setup = setup or _whatsapp_clean_inline(match.group(1))
            timeframe = timeframe or _whatsapp_clean_inline(match.group(2))
    return setup or "N/A", _whatsapp_timeframe_label(timeframe or "N/A")


def _whatsapp_timeframe_label(value: str) -> str:
    clean = _whatsapp_clean_inline(value) or "N/A"
    match = re.fullmatch(r"(\d+)\s*([mMhHdDwW])", clean)
    if not match:
        return clean
    unit = match.group(2)
    normalized_unit = "m" if unit.lower() == "m" else unit.upper()
    return f"{match.group(1)}{normalized_unit}"


def _whatsapp_parse_price(value: str) -> float:
    clean = _whatsapp_clean_inline(value)
    if ":" in clean:
        clean = clean.split(":", 1)[1].strip()
    match = re.search(r"[-+]?\$?\s*([0-9]+(?:[.,][0-9]+)?)", clean)
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 0.0


def _whatsapp_result_pct_label(side: str, entry_price: float, price: float, leverage: float) -> str:
    pct = _directional_notice_pnl_pct(str(side or "").lower(), entry_price, price, leverage)
    return f"({pct:+.2f}%)" if pct is not None else ""


def _whatsapp_targets(
    lines: list[str],
    *,
    entry: bool = False,
    side: str = "",
    entry_price: float = 0.0,
    leverage: float = 1.0,
) -> list[str]:
    targets: list[str] = []
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        if not re.search(r"\bAlvo\s+\d+\s*:", line, re.IGNORECASE):
            continue
        line = re.sub(r"^[➜→\s]+", "", line).strip()
        if side and entry_price > 0:
            marker = ""
            marker_match = re.search(r"\s([✅⏳❌])$", line)
            if marker_match:
                marker = marker_match.group(1)
                line = line[: marker_match.start()].rstrip()
            target_price = _whatsapp_parse_price(line)
            result_label = _whatsapp_result_pct_label(side, entry_price, target_price, leverage)
            if result_label and result_label not in line:
                line = f"{line} {result_label}"
            if marker:
                line = f"{line} {marker}"
        if entry:
            line = re.sub(r"^[✅⏳❌\s]+", "", line).strip()
            if not line.startswith("➜"):
                line = f"➜ {line}"
        targets.append(line)
    return targets[:4]


def _whatsapp_rr(lines: list[str]) -> str:
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        match = re.search(r"Relação risco/retorno estimada:\s*([0-9.,]+)", line, re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".")
    return "N/A"


def _whatsapp_notice_kind(lines: list[str]) -> str:
    text = "\n".join(lines).upper()
    if "NOVA OPERAÇÃO" in text or "NOVA OPERACAO" in text or "NOVO TRADE" in text:
        return "entry"
    if "FECHAMENTO MANUAL" in text:
        return "manual"
    if "STOP LOSS ATINGIDO" in text or "STOPLOSS ATINGIDO" in text:
        return "stop"
    return "target"


def _whatsapp_manual_reason(lines: list[str]) -> str:
    reason = ""
    for raw in lines:
        line = _whatsapp_clean_inline(raw)
        if line.startswith("📝"):
            reason = line.lstrip("📝").strip()
            break
    if not reason:
        reason = "Desconfiguração de setup."
    if re.search(r"entre\s+alvo|perda\s+de\s+for[cç]a|mudan[cç]a.*setup", reason, re.IGNORECASE):
        reason = "Desconfiguração de setup."
    parts = re.split(r"(?<=[.!?])\s+", reason)
    return " ".join(part for part in parts[:1] if part).strip()


def _format_whatsapp_entry_notice(lines: list[str], audience: str) -> str:
    pair = _whatsapp_pair_from_notice(lines)
    setup, timeframe = _whatsapp_setup_timeframe(lines)
    leverage = _leverage_notice_label(_setup_leverage_for_timeframe(timeframe))
    leverage_value = _setup_leverage_for_timeframe(timeframe)
    side = _whatsapp_value_after(lines, ("Operação", "Operacao", "Tipo")) or "N/A"
    side = side.split()[0].upper() if side else "N/A"
    entry = _whatsapp_value_after(lines, ("Entrada", "Preço de Entrada", "Preco de Entrada")) or "N/A"
    stop = _whatsapp_value_after(lines, ("Stop", "Stop Loss")) or "N/A"
    entry_price = _whatsapp_parse_price(entry)
    targets = _whatsapp_targets(lines, entry=True, side=side, entry_price=entry_price, leverage=1.0)
    output = [
        f"🚨 NOVO TRADE {audience}".rstrip(),
        "",
        f"📈 Setup: {setup}",
        f"Tempo Gráfico: {timeframe}",
        f"Alavancagem sugerida: {leverage}",
        "",
        pair,
        "",
        "📊 Trade:",
        "",
        f"💎 Operação: {side}",
        f"📌 Entrada: {entry}",
        f"🛑 Stop: {stop}",
        "",
        "🎯 Alvos:",
        *(targets or ["➜ Alvo 1: N/A", "➜ Alvo 2: N/A", "➜ Alvo 3: N/A", "➜ Alvo 4: N/A"]),
        "",
        "⚡️ Se bater Alvo 1, subir Stop Loss para ponto de entrada, realizando parcial de lucro.",
        "",
        "⚠️ Disclaimer:",
        "Conteúdo educacional para estudo do setup, contexto e gestão de risco.",
    ]
    return "\n".join(output).strip()


def _format_whatsapp_update_notice(lines: list[str], audience: str) -> str:
    kind = _whatsapp_notice_kind(lines)
    title = {
        "manual": "❌ FECHAMENTO MANUAL",
        "stop": "⛔️ STOP LOSS ATINGIDO",
        "target": "💰 GRANA NO BOLSO",
    }.get(kind, "💰 GRANA NO BOLSO")
    pair = _whatsapp_pair_from_notice(lines)
    setup, timeframe = _whatsapp_setup_timeframe(lines)
    leverage = _leverage_notice_label(_setup_leverage_for_timeframe(timeframe))
    leverage_value = _setup_leverage_for_timeframe(timeframe)
    side = _whatsapp_value_after(lines, ("Tipo", "Operação", "Operacao"))
    side = side.split()[0].upper() if side else ""
    entry = _whatsapp_value_after(lines, ("Entrada", "Preço de Entrada", "Preco de Entrada")) or "N/A"
    stop = _whatsapp_value_after(lines, ("Stop", "Stop Loss")) or "N/A"
    pnl = _whatsapp_value_after(lines, ("P&L", "PNL")) or "N/A"
    entry_price = _whatsapp_parse_price(entry)
    targets = _whatsapp_targets(lines, side=side, entry_price=entry_price, leverage=leverage_value)
    if kind == "stop":
        return "\n".join(
            [
                f"{title} {audience}".rstrip(),
                "",
                pair,
                "",
                f"📌 Entrada: {entry}",
                f"🛑 Stop: {stop}",
                "",
                "📊 Performance:",
                f"PNL: {pnl}",
            ]
        ).strip()
    output = [
        f"{title} {audience}".rstrip(),
        "",
        pair,
        "",
        f"📌 Entrada: {entry}",
        f"🛑 Stop: {stop}",
        "",
        "📊 Status dos Alvos:",
        *(targets or ["⏳ Alvo 1: N/A", "⏳ Alvo 2: N/A", "⏳ Alvo 3: N/A", "⏳ Alvo 4: N/A"]),
        "",
        "📈 Detalhes da Operação:",
        f"Estratégia: {setup}",
        f"Timeframe: {timeframe}",
        f"Alavancagem sugerida: {leverage}",
        "",
        "📊 Performance:",
        f"PNL: {pnl}",
    ]
    if kind == "manual":
        output.extend(["", "", f"📝 {_whatsapp_manual_reason(lines)}"])
    output.extend(
        [
            "",
            "⚠️ Disclaimer:",
            "Não é recomendaçao de investimento. Siga seu gerenciamento e faça sua própia análise.",
        ]
    )
    return "\n".join(output).strip()


def _format_whatsapp_from_notice(message: str) -> str:
    """Formata o espelho WhatsApp com templates próprios sem alterar Discord."""
    text = str(message or "").strip()
    # WhatsApp não deve exibir @all textual: ele não marca todos de verdade neste fluxo.
    audience = ""
    text = re.sub(r"<@&\d+>", audience, text)
    text = text.replace("@Intus Club Member", audience)
    lines = _whatsapp_notice_lines(text)
    kind = _whatsapp_notice_kind(lines)
    formatted = _format_whatsapp_entry_notice(lines, audience) if kind == "entry" else _format_whatsapp_update_notice(lines, audience)
    prefix = os.environ.get("SETUP_NOTIFY_WHATSAPP_PREFIX", "").strip()
    if prefix:
        formatted = f"{prefix}\n\n{formatted}" if formatted else prefix
    return formatted.strip()


def _send_setup_trade_notice(
    message: str,
    chart_payload: dict[str, Any] | None = None,
    *,
    reply_to_discord_message_id: str = "",
    reply_to_whatsapp_message_id: str = "",
    include_chart: bool = True,
) -> dict[str, str]:
    if not _setup_notifications_enabled():
        return {}

    channel = os.environ.get("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram").strip() or "telegram"
    target = os.environ.get("SETUP_NOTIFY_ENTRY_TARGET", "").strip()
    account = os.environ.get("SETUP_NOTIFY_ENTRY_ACCOUNT", "").strip()
    discord_channel_id = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "").strip()
    discord_account = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT", "default").strip()
    whatsapp_target = os.environ.get("SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET", "").strip()
    whatsapp_account = os.environ.get("SETUP_NOTIFY_ENTRY_WHATSAPP_ACCOUNT", "default").strip()
    whatsapp_enabled = os.environ.get("SETUP_NOTIFY_WHATSAPP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "sim"}
    if not target and not discord_channel_id and not (whatsapp_enabled and whatsapp_target):
        return {}

    needs_chart = include_chart and (
        bool(discord_channel_id)
        or (bool(target) and channel in {"discord", "whatsapp"})
        or (whatsapp_enabled and bool(whatsapp_target))
    )
    image_path = _render_setup_chart_image(chart_payload) if needs_chart else None
    sent: dict[str, str] = {}
    require_chart = os.environ.get("SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY", "true").strip().lower() not in {"0", "false", "no", "nao", "off"}
    if needs_chart and require_chart and image_path is None:
        symbol = str((chart_payload or {}).get("symbol") or "").strip() or "N/A"
        logger.warning("notificacao de entrada bloqueada: grafico obrigatorio ausente | symbol=%s", symbol)
        return sent

    if target:
        message_id = _send_entry_notification(
            channel=channel,
            target=target,
            account=account,
            message=_message_for_entry_channel(channel, message),
            image_path=image_path if channel in {"discord", "whatsapp"} else None,
            reply_to_discord_message_id=reply_to_discord_message_id if channel == "discord" else "",
            reply_to_whatsapp_message_id=reply_to_whatsapp_message_id if channel == "whatsapp" else "",
        )
        if message_id:
            sent["discord_message_id" if channel == "discord" else "whatsapp_message_id" if channel == "whatsapp" else "message_id"] = message_id
    if discord_channel_id:
        primary_discord_target = _normalize_message_target(channel, target)
        extra_discord_target = _normalize_message_target("discord", discord_channel_id)
        if channel != "discord" or primary_discord_target != extra_discord_target:
            discord_message_id = _send_entry_notification(
                channel="discord",
                target=discord_channel_id,
                account=discord_account,
                message=message,
                image_path=image_path,
                reply_to_discord_message_id=reply_to_discord_message_id,
            )
            if discord_message_id:
                sent["discord_message_id"] = discord_message_id
    if whatsapp_enabled and whatsapp_target:
        primary_whatsapp_target = _normalize_message_target(channel, target)
        extra_whatsapp_target = _normalize_message_target("whatsapp", whatsapp_target)
        if channel != "whatsapp" or primary_whatsapp_target != extra_whatsapp_target:
            whatsapp_message_id = _send_entry_notification(
                channel="whatsapp",
                target=whatsapp_target,
                account=whatsapp_account,
                message=_message_for_entry_channel("whatsapp", message),
                image_path=image_path,
                reply_to_discord_message_id="",
                reply_to_whatsapp_message_id=reply_to_whatsapp_message_id,
            )
            if whatsapp_message_id:
                sent["whatsapp_message_id"] = whatsapp_message_id
    return sent


def _format_trade_datetime(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=TRADE_NOTICE_TZ)
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year}, {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} BRT"


def _format_trade_symbol(symbol: str) -> str:
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("/", "")
    if cleaned and not cleaned.endswith(("USDT", "USDC", "USD")):
        cleaned = f"{cleaned}USDT"
    return cleaned or "N/A"


def _format_trade_price(value: float | None) -> str:
    try:
        price = float(value or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    if price <= 0:
        return "N/A"
    abs_price = abs(price)
    if abs_price >= 1000:
        decimals = 2
    elif abs_price >= 1:
        decimals = 4
    elif abs_price >= 0.01:
        decimals = 5
    elif abs_price >= 0.0001:
        decimals = 6
    else:
        decimals = 8
    formatted = f"{price:.{decimals}f}".rstrip("0").rstrip(".")
    return _bold_notice_value(f"${formatted}")


def _format_trade_amount(value: float | None) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    return _bold_notice_value(f"${amount:.4f}")


def _format_trade_pct(value: float | None) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return _bold_notice_value(f"{pct:.2f}%")


def _side_notice_label(side: str) -> str:
    normalized = str(side or "").lower()
    if normalized == "long":
        return "LONG 🟢"
    if normalized == "short":
        return "SHORT 🔴"
    return normalized.upper() or "N/A"


def _setup_notice_strategy(setup_key: str) -> str:
    definition = SETUP_CATALOG.get(setup_key)
    return definition.label if definition is not None else setup_key


def _risk_notice_label(profile: str) -> str:
    normalized = str(profile or "").lower()
    return {
        "conservative": "Conservador",
        "moderate": "Moderado",
        "aggressive": "Agressivo",
    }.get(normalized, normalized.capitalize() if normalized else "Moderado")


def _leverage_notice_label(leverage: float | None) -> str:
    try:
        value = float(leverage or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    if value <= 0:
        return "N/A"
    return f"{value:g}x"


TIMEFRAME_SETUP_LEVERAGE: dict[str, float] = {
    "15m": 10.0,
    "30m": 7.0,
    "1h": 5.0,
    "4h": 3.0,
    "1d": 1.0,
}


def _normalize_setup_timeframe_key(timeframe: str) -> str:
    value = str(timeframe or "").strip().lower().replace(" ", "")
    aliases = {
        "15min": "15m",
        "15": "15m",
        "30min": "30m",
        "30": "30m",
        "60m": "1h",
        "1hr": "1h",
        "1hour": "1h",
        "240m": "4h",
        "4hr": "4h",
        "4hour": "4h",
        "d": "1d",
        "day": "1d",
        "1day": "1d",
        "daily": "1d",
    }
    return aliases.get(value, value)


def _setup_leverage_for_timeframe(timeframe: str, *, fallback: float | None = None) -> float:
    key = _normalize_setup_timeframe_key(timeframe)
    if key in TIMEFRAME_SETUP_LEVERAGE:
        return TIMEFRAME_SETUP_LEVERAGE[key]
    try:
        return max(float(fallback or 1.0), 1.0)
    except (TypeError, ValueError):
        return 1.0


def _setup_leverage_for_signal(setup_key: str, signal: object, *, fallback: float | None = None) -> float:
    timeframe = str(getattr(signal, "timeframe", "") or "").strip()
    if not timeframe:
        setup_definition = SETUP_CATALOG.get(setup_key)
        timeframe = setup_definition.timeframe if setup_definition is not None else ""
    return _setup_leverage_for_timeframe(timeframe, fallback=fallback)


def _setup_leverage_for_state(state: ManagedSetupState) -> float:
    return _setup_leverage_for_timeframe(state.timeframe, fallback=state.leverage or None)


def _risk_reward(entry_price: float, stop_price: float, target_price: float) -> float | None:
    if entry_price <= 0 or stop_price <= 0 or target_price <= 0:
        return None
    risk = abs(entry_price - stop_price)
    reward = abs(target_price - entry_price)
    if risk <= 0:
        return None
    return reward / risk


def _directional_notice_pnl_pct(side: str, entry_price: float, live_price: float, leverage: float) -> float | None:
    if entry_price <= 0 or live_price <= 0:
        return None
    if side == "long":
        base = (live_price - entry_price) / entry_price
    elif side == "short":
        base = (entry_price - live_price) / entry_price
    else:
        return None
    return base * max(float(leverage or 1.0), 1.0) * 100


def _target_realization_weights(targets_count: int) -> list[float]:
    if targets_count <= 0:
        return []
    if targets_count == 1:
        return [1.0]
    remaining_weight = 0.50 / max(targets_count - 1, 1)
    return [0.50] + [remaining_weight for _ in range(targets_count - 1)]


def _directional_notice_weighted_result_pct(
    *,
    side: str,
    entry_price: float,
    live_price: float,
    leverage: float,
    targets: list[float],
    targets_hit: int,
) -> float | None:
    live_pct = _directional_notice_pnl_pct(side, entry_price, live_price, leverage)
    if live_pct is None:
        return None
    valid_targets = [float(target) for target in targets if float(target or 0.0) > 0]
    if not valid_targets:
        return live_pct
    weights = _target_realization_weights(len(valid_targets))
    completed = max(0, min(int(targets_hit or 0), len(valid_targets)))
    total = 0.0
    for idx, weight in enumerate(weights):
        if idx < completed:
            target_pct = _directional_notice_pnl_pct(side, entry_price, valid_targets[idx], leverage)
            total += weight * float(target_pct if target_pct is not None else live_pct)
        else:
            total += weight * live_pct
    return total


def _notice_targets_lines(targets: list[float], *, targets_hit: int = 0) -> list[str]:
    if not targets:
        return ["ALVO 1: N/A ⏳"]
    lines: list[str] = []
    for idx, target in enumerate(targets, start=1):
        marker = "✅" if idx <= targets_hit else "⏳"
        lines.append(f"ALVO {idx}: {_format_trade_price(target)} {marker}")
    return lines


def _notice_targets_inline(targets: list[float], *, targets_hit: int = 0) -> str:
    return " | ".join(_notice_targets_lines(targets, targets_hit=targets_hit))


def _format_symbol_pair(symbol: str) -> str:
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("-", "/")
    if "/" in cleaned:
        base, quote = cleaned.split("/", 1)
        return f"{base}/{quote or 'USDT'}"
    for quote in ("USDT", "USDC", "USD"):
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            return f"{cleaned[:-len(quote)]}/{quote}"
    return f"{cleaned or 'N/A'}/USDT"


def _symbol_base(symbol: str) -> str:
    return _format_symbol_pair(symbol).split("/", 1)[0]


def _ensure_four_notice_targets(targets: list[float]) -> list[float]:
    return [float(target) for target in targets if float(target or 0.0) > 0][:4]


def _notice_targets_block(targets: list[float]) -> list[str]:
    valid = _ensure_four_notice_targets(targets)
    if not valid:
        return ["→ Alvo 1: N/A"]
    return [f"→ Alvo {idx}: {_format_trade_price(target)}" for idx, target in enumerate(valid, start=1)]


def _notice_rr_label(entry_price: float, stop_price: float, targets: list[float]) -> str:
    # Na mensagem pública de entrada, a relação risco/retorno é ancorada no Alvo 1.
    # Os demais alvos são extensão da operação e só entram depois do acionamento inicial.
    target = targets[0] if targets else 0.0
    rr = _risk_reward(float(entry_price or 0.0), float(stop_price or 0.0), float(target or 0.0))
    return f"{rr:.2f}" if rr is not None else "N/A"


def _notice_timeframe_label(timeframe: str) -> str:
    raw = str(timeframe or "").strip()
    if not raw:
        return "N/A"
    return raw.upper()


def _notice_activation_bullets(*, side: str, entry_price: float, stop_price: float, targets: list[float], reason: str) -> list[str]:
    side_label = str(side or "").upper() or "N/A"
    clean_reason = str(reason or "Setup detectado pelo robô.").strip().rstrip(".")
    final_target = _format_trade_price(targets[-1]) if targets else "N/A"
    rr = _notice_rr_label(entry_price, stop_price, targets)
    return [
        f"→ {clean_reason}.",
        f"→ Entrada técnica em {_format_trade_price(entry_price)} com invalidação em {_format_trade_price(stop_price)}.",
        f"→ Alvos definidos até {final_target}; relação risco/retorno estimada: {rr}.",
        f"→ Operação {side_label} segue válida enquanto não perder a invalidação em {_format_trade_price(stop_price)}.",
    ]


def _notice_risk_text() -> str:
    return os.environ.get(
        "SETUP_NOTIFY_RISK_TEXT",
        "5% da banca destinada a trading futuros com alavancagem máxima de 5x.",
    ).strip()


def _notice_disclaimer_text() -> str:
    return os.environ.get(
        "SETUP_NOTIFY_DISCLAIMER",
        "O mercado de criptomoedas é altamente volátil e imprevisível. As análises e operações compartilhadas aqui são baseadas em indicadores técnicos, price action e outros dados de mercado, mas NÃO constituem recomendação de investimento. Cada participante deve realizar sua própria análise e entrar em qualquer operação por conta e risco próprios.",
    ).strip()


def _normalize_target_stop_mode(raw: str | None) -> str:
    value = str(raw or "").strip().lower().replace(" ", "-")
    normalized = TARGET_STOP_MODE_ALIASES.get(value)
    if normalized:
        return normalized
    allowed = "off/desligado, breakeven_on_tp1/entrada-no-tp1, ladder/escada"
    raise ValueError(f"modo-stop-alvo invalido: {raw!r}; use {allowed}")


def _target_stop_mode_from_state(state: ManagedSetupState) -> str:
    try:
        return _normalize_target_stop_mode(str(state.metadata.get("target_stop_mode") or TARGET_STOP_MODE_OFF))
    except ValueError:
        return TARGET_STOP_MODE_OFF


def _is_stop_improvement(side: str, current_stop: float, candidate_stop: float) -> bool:
    if candidate_stop <= 0:
        return False
    if current_stop <= 0:
        return True
    if side == "long":
        return candidate_stop > current_stop + 1e-9
    if side == "short":
        return candidate_stop < current_stop - 1e-9
    return False


def _target_stop_candidate(state: ManagedSetupState, targets_hit: int) -> float:
    mode = _target_stop_mode_from_state(state)
    if mode == TARGET_STOP_MODE_OFF or targets_hit <= 0:
        return 0.0
    entry_price = _state_entry_price(state)
    if entry_price <= 0:
        return 0.0
    if mode == TARGET_STOP_MODE_BREAKEVEN_ON_TP1:
        return entry_price
    if mode == TARGET_STOP_MODE_LADDER:
        if targets_hit <= 1:
            return entry_price
        targets = _state_notice_targets(state)
        target_index = min(targets_hit - 2, len(targets) - 1)
        if target_index >= 0 and targets:
            return float(targets[target_index])
        return entry_price
    return 0.0


def _sync_pair_stop_price(state: ManagedSetupState, stop_price: float) -> None:
    if state.effective_venue in {"hedged", "nado"}:
        state.pair_state.nado_stop_price = stop_price
    if state.effective_venue in {"hedged", "kraken"}:
        state.pair_state.kraken_stop_price = stop_price


def _native_order_venue_id(eng: DeltaNeutralEngine | None, role: str) -> str:
    if role == "nado":
        return str(getattr(eng, "dex_id", "nado") or "nado")
    if role == "kraken":
        return str(getattr(eng, "cex_id", "kraken") or "kraken")
    return role


def _extract_order_ref(order: object) -> dict[str, str]:
    payloads: list[object] = []

    def collect(obj: object) -> None:
        if obj is None or len(payloads) > 24:
            return
        if isinstance(obj, (list, tuple)):
            for item in obj:
                collect(item)
            return
        payloads.append(obj)
        if isinstance(obj, dict):
            for key in ("data", "result", "order", "response", "info"):
                if key in obj:
                    collect(obj.get(key))
            return
        for attr in ("data", "result", "order", "response", "info"):
            if hasattr(obj, attr):
                collect(getattr(obj, attr))

    collect(order)
    ref: dict[str, str] = {}
    id_keys = ("id", "order_id", "orderId", "clientOrderId", "client_order_id")
    digest_keys = ("digest", "tx_hash", "txHash", "hash")
    for payload in payloads:
        getter = payload.get if isinstance(payload, dict) else lambda key, default=None, payload=payload: getattr(payload, key, default)
        if "id" not in ref:
            for key in id_keys:
                value = getter(key, None)
                if value:
                    ref["id"] = str(value)
                    break
        if "digest" not in ref:
            for key in digest_keys:
                value = getter(key, None)
                if value:
                    ref["digest"] = str(value)
                    break
        if ref.get("id") and ref.get("digest"):
            break
    return ref


def _native_order_ref_id(order_ref: object) -> str:
    if isinstance(order_ref, str):
        return order_ref
    if not isinstance(order_ref, dict):
        return ""
    return str(order_ref.get("digest") or order_ref.get("id") or "")


def _record_native_order_ref(
    state: ManagedSetupState,
    eng: DeltaNeutralEngine | None,
    role: str,
    kind: str,
    order: object,
    *,
    price: float,
    quantity: float,
    label: str = "",
) -> dict[str, Any]:
    ref: dict[str, Any] = _extract_order_ref(order)
    ref.update(
        {
            "role": role,
            "venue_id": _native_order_venue_id(eng, role),
            "kind": kind,
            "price": float(price),
            "quantity": float(quantity),
            "label": label,
            "created_at": time.time(),
            "tracked": bool(_native_order_ref_id(ref)),
        }
    )
    native_orders = state.metadata.setdefault("native_orders", {})
    if not isinstance(native_orders, dict):
        native_orders = {}
        state.metadata["native_orders"] = native_orders
    role_orders = native_orders.setdefault(role, {})
    if not isinstance(role_orders, dict):
        role_orders = {}
        native_orders[role] = role_orders
    role_orders["venue_id"] = _native_order_venue_id(eng, role)
    if kind == "sl":
        role_orders["sl"] = ref
    else:
        role_orders.setdefault("tp", [])
        if isinstance(role_orders["tp"], list):
            role_orders["tp"].append(ref)
    return ref


def _invalidate_native_stop_ref(state: ManagedSetupState, role: str, *, reason: str) -> None:
    """Marca a referencia de stop nativo como morta.

    `replace_stop_loss` cancela o stop antigo antes de criar o novo. Quando a
    criacao falha, a referencia guardada aponta para uma ordem que nao existe
    mais -- e o ciclo seguinte tentaria cancelar esse id de novo, empilhando um
    `OrderNotFound` por cima do erro real e escondendo que a posicao esta nua.
    """
    native_orders = state.metadata.get("native_orders")
    if not isinstance(native_orders, dict):
        return
    role_orders = native_orders.get(role)
    if not isinstance(role_orders, dict):
        return
    ref = role_orders.get("sl")
    if not isinstance(ref, dict):
        return
    ref.pop("id", None)
    ref.pop("digest", None)
    ref["tracked"] = False
    ref["invalidated_reason"] = reason
    ref["invalidated_at"] = time.time()


def _role_stop_order_ref(state: ManagedSetupState, role: str) -> dict[str, Any]:
    native_orders = state.metadata.get("native_orders")
    if not isinstance(native_orders, dict):
        return {}
    role_orders = native_orders.get(role)
    if not isinstance(role_orders, dict):
        return {}
    ref = role_orders.get("sl")
    return ref if isinstance(ref, dict) else {}


def _state_role_qty(state: ManagedSetupState, role: str) -> float:
    if role == "nado":
        return abs(float(state.pair_state.nado_qty or 0.0))
    if role == "kraken":
        return abs(float(state.pair_state.kraken_qty or 0.0))
    return 0.0


def _set_state_role_qty(state: ManagedSetupState, role: str, quantity: float) -> None:
    qty = max(float(quantity), 0.0)
    if role == "nado":
        state.pair_state.nado_qty = qty
    elif role == "kraken":
        state.pair_state.kraken_qty = qty


def _refresh_state_effective_notional(state: ManagedSetupState) -> None:
    notionals: list[float] = []
    if state.effective_venue in {"hedged", "nado"} and state.pair_state.nado_entry > 0:
        notionals.append(abs(float(state.pair_state.nado_qty or 0.0)) * float(state.pair_state.nado_entry))
    if state.effective_venue in {"hedged", "kraken"} and state.pair_state.kraken_entry > 0:
        notionals.append(abs(float(state.pair_state.kraken_qty or 0.0)) * float(state.pair_state.kraken_entry))
    if notionals:
        state.pair_state.effective_notional_usd = min(notionals) if state.effective_venue == "hedged" else notionals[0]


def _replace_native_stop_loss(eng: DeltaNeutralEngine, state: ManagedSetupState, new_stop: float) -> dict[str, Any]:
    roles: list[str] = []
    if state.effective_venue in {"hedged", "nado"}:
        roles.append("nado")
    if state.effective_venue in {"hedged", "kraken"}:
        roles.append("kraken")
    results: list[dict[str, Any]] = []
    for role in roles:
        trader = getattr(eng, role, None)
        replace = getattr(trader, "replace_stop_loss", None)
        previous_ref = _role_stop_order_ref(state, role)
        ref_id = _native_order_ref_id(previous_ref)
        if not callable(replace):
            results.append({"role": role, "replaced": False, "reason": "adapter_missing_replace_stop_loss"})
            continue
        if not ref_id:
            results.append({"role": role, "replaced": False, "reason": "missing_native_stop_ref"})
            continue
        quantity = _state_role_qty(state, role)
        if quantity <= 0 or new_stop <= 0:
            results.append({"role": role, "replaced": False, "reason": "invalid_qty_or_stop"})
            continue
        try:
            if role == "nado":
                quantity = float(trader.round_quantity_to_increment(state.pair_state.nado_product_id, quantity))
                result = replace(
                    product_id=state.pair_state.nado_product_id,
                    quantity=quantity,
                    trigger_price=float(new_stop),
                    is_long=(state.pair_state.nado_side or state.side) == "long",
                    previous_order_ref=previous_ref,
                    slippage_pct=float(getattr(eng, "protective_stop_trigger_slippage_pct", 0.01) or 0.01),
                )
            else:
                quantity = float(trader.round_quantity_to_increment(state.pair_state.kraken_symbol, quantity))
                result = replace(
                    symbol=state.pair_state.kraken_symbol,
                    quantity=quantity,
                    trigger_price=float(new_stop),
                    is_long=(state.pair_state.kraken_side or state.side) == "long",
                    previous_order_ref=previous_ref,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("setup-live stop-alvo | falha ao trocar SL nativo %s em %s: %s", role, state.symbol, exc)
            # A troca cancela antes de criar: a referencia guardada agora
            # aponta para ordem morta. Deixa-la faria o proximo ciclo cancelar
            # um id inexistente em vez de perceber a posicao desprotegida.
            _invalidate_native_stop_ref(state, role, reason=str(exc))
            results.append({"role": role, "replaced": False, "reason": str(exc), "stop_ref_invalidated": True})
            continue
        order = result.get("order") if isinstance(result, dict) else result
        skipped_reason = result.get("skipped_reason") if isinstance(result, dict) else ""
        if order is None:
            results.append({"role": role, "replaced": False, "reason": skipped_reason or "replace_returned_no_order"})
            continue
        new_ref = _record_native_order_ref(
            state,
            eng,
            role,
            "sl",
            order,
            price=float(new_stop),
            quantity=quantity,
            label=f"SL-after-TP{state.targets_hit}",
        )
        results.append({"role": role, "replaced": True, "order_ref": new_ref})
    return {"replaced": any(item.get("replaced") for item in results), "results": results}


def _apply_target_stop_mode(
    state: ManagedSetupState,
    *,
    previous_targets_hit: int,
    targets_hit: int,
    eng: DeltaNeutralEngine | None = None,
) -> dict[str, float | str] | None:
    mode = _target_stop_mode_from_state(state)
    if mode == TARGET_STOP_MODE_OFF or targets_hit <= previous_targets_hit:
        return None
    new_stop = _target_stop_candidate(state, targets_hit)
    old_stop = float(state.stop_price or 0.0)
    if not _is_stop_improvement(state.side, old_stop, new_stop):
        return None
    state.stop_price = float(new_stop)
    _sync_pair_stop_price(state, float(new_stop))
    state.metadata["target_stop_mode"] = mode
    native_replace = _replace_native_stop_loss(eng, state, float(new_stop)) if eng is not None else {"replaced": False, "results": []}
    state.metadata["target_stop_last_move"] = {
        "from": old_stop,
        "to": float(new_stop),
        "after_targets_hit": int(targets_hit),
        "mode": mode,
        "native_stop_replaced": bool(native_replace.get("replaced")),
        "native_stop_replace_results": native_replace.get("results", []),
    }
    if native_replace.get("replaced"):
        state.metadata["target_stop_native_replacement"] = "replace_stop_loss"
    description = f"Stop movido de {old_stop:.8g} para {float(new_stop):.8g} apos TP{targets_hit} ({mode})"
    _append_setup_event(state, "Stop Move", description)
    logger.info("setup-live stop-alvo | %s %s | %s", state.setup_key, state.symbol, description)
    return {"old_stop": old_stop, "new_stop": float(new_stop), "mode": mode}


def _notice_pct_from_env(*env_names: str, default: float = 0.0) -> float:
    raw = _first_env(*env_names)
    if raw is None:
        return default
    try:
        return _parse_pct_value(raw)
    except (TypeError, ValueError):
        return default


def _notice_stop_loss_pct(stop_loss_pct: float = 0.0) -> float:
    if stop_loss_pct > 0:
        return stop_loss_pct
    return _notice_pct_from_env(
        "SETUP_NOTIFY_STOP_LOSS_PCT",
        "PROTECTIVE_STOP_LOSS_PCT",
        "MAX_PAIR_LOSS_PCT",
        default=0.03,
    )


def _notice_take_profit_pct(take_profit_pct: float = 0.0) -> float:
    if take_profit_pct > 0:
        return take_profit_pct
    return _notice_pct_from_env(
        "SETUP_NOTIFY_TAKE_PROFIT_PCT",
        "PROTECTIVE_TAKE_PROFIT_PCT",
        default=0.03,
    )


def _fallback_notice_stop_price(
    *,
    entry_price: float,
    side: str,
    explicit_stop_price: float,
    stop_loss_pct: float = 0.0,
) -> float:
    if explicit_stop_price > 0:
        return explicit_stop_price
    return _stop_price_from_pct(entry_price, side, _notice_stop_loss_pct(stop_loss_pct))


def _fallback_notice_targets(
    *,
    entry_price: float,
    side: str,
    explicit_targets: list[float],
    take_profit_pct: float = 0.0,
) -> list[float]:
    targets = [float(target) for target in explicit_targets if float(target or 0.0) > 0]
    if targets:
        return targets
    target = _take_profit_price_from_pct(entry_price, side, _notice_take_profit_pct(take_profit_pct))
    return [target] if target > 0 else []


def _active_cex_notice_label() -> str:
    cex_id = selected_venues().cex_id
    if _is_builtin_kraken_cex(cex_id):
        return "Kraken"
    return cex_id or "CEX"


def _notice_venue_label(venue: str) -> str:
    normalized = str(venue or "").strip().lower()
    if normalized == EXECUTION_MODE_HEDGED:
        return f"Nado + {_active_cex_notice_label()}"
    if normalized in {EXECUTION_MODE_NADO_ONLY, "nado"}:
        return "Nado"
    if normalized in {EXECUTION_MODE_KRAKEN_ONLY, "kraken"}:
        return _active_cex_notice_label()
    return venue or "N/A"


def _notice_mode_label(venue: str) -> str:
    normalized = str(venue or "").strip().lower()
    if normalized == EXECUTION_MODE_HEDGED:
        return normalized
    if normalized == EXECUTION_MODE_NADO_ONLY:
        return normalized
    if normalized == EXECUTION_MODE_KRAKEN_ONLY:
        return EXECUTION_MODE_KRAKEN_ONLY if _is_builtin_kraken_cex(selected_venues().cex_id) else "cex_only"
    if normalized == "kraken":
        return EXECUTION_MODE_KRAKEN_ONLY if _is_builtin_kraken_cex(selected_venues().cex_id) else "cex_only"
    if normalized == "nado":
        return EXECUTION_MODE_NADO_ONLY
    return ""


def _plan_notice_targets(plan: SetupOrderPlan, signal: object | None = None) -> list[float]:
    targets = list(getattr(signal, "take_profit_targets", []) or []) if signal is not None else []
    reference_entry = float(getattr(signal, "reference_entry_price", 0.0) or 0.0) if signal is not None else 0.0
    if targets and reference_entry > 0 and plan.entry_price > 0:
        rebased = [
            _rebase_reference_price(float(target), from_entry=reference_entry, to_entry=plan.entry_price)
            for target in targets
        ]
        return [target for target in rebased if target > 0]
    if plan.take_profit > 0:
        return [float(plan.take_profit)]
    return []


def _plan_notice_stop_price(
    *,
    plan: SetupOrderPlan | None,
    signal: object | None,
    entry_price: float,
    side: str,
    stop_loss_pct: float = 0.0,
) -> float:
    # Para a entrega visual/textual, o stop canônico é o do setup. O preset global
    # de stop_loss_pct existe para proteção operacional/fallback, mas não deve
    # sobrescrever uma invalidação explícita do setup no print do TradingView.
    signal_stop = float(getattr(signal, "stop_price", 0.0) or 0.0) if signal is not None else 0.0
    reference_entry = float(getattr(signal, "reference_entry_price", 0.0) or 0.0) if signal is not None else 0.0
    if signal_stop > 0:
        if reference_entry > 0 and entry_price > 0:
            rebased_stop = _rebase_reference_price(signal_stop, from_entry=reference_entry, to_entry=entry_price)
            if rebased_stop > 0:
                return rebased_stop
        return signal_stop
    plan_stop = float(plan.stop_price or 0.0) if plan is not None else 0.0
    return _fallback_notice_stop_price(
        entry_price=entry_price,
        side=side,
        explicit_stop_price=plan_stop,
        stop_loss_pct=stop_loss_pct,
    )


def _signal_notice_targets(signal: object | None) -> list[float]:
    if signal is None:
        return []
    targets = [float(target) for target in list(getattr(signal, "take_profit_targets", []) or []) if float(target or 0.0) > 0]
    if targets:
        return targets
    take_profit = float(getattr(signal, "take_profit", 0.0) or 0.0)
    return [take_profit] if take_profit > 0 else []


def _state_entry_price(state: ManagedSetupState) -> float:
    if state.effective_venue == "nado":
        return float(state.pair_state.nado_entry or 0.0)
    if state.effective_venue == "kraken":
        return float(state.pair_state.kraken_entry or 0.0)
    return float(state.reference_entry_price or state.pair_state.kraken_entry or state.pair_state.nado_entry or 0.0)


def _state_notice_targets(state: ManagedSetupState) -> list[float]:
    levels = state.metadata.get("target_levels")
    if isinstance(levels, list):
        targets = [float(level.get("price") or 0.0) for level in levels if isinstance(level, dict)]
        return [target for target in targets if target > 0]
    if state.take_profit > 0:
        return [float(state.take_profit)]
    return []


def _state_notice_margin(state: ManagedSetupState) -> float:
    margin = float(state.metadata.get("requested_margin_usd") or 0.0)
    if margin <= 0:
        margin = float(state.pair_state.requested_margin_usd or 0.0)
    return margin


def _state_total_directional_qty(state: ManagedSetupState) -> float:
    initial_qty = float(state.metadata.get("initial_position_qty") or 0.0)
    if initial_qty > 0:
        return initial_qty
    levels = state.metadata.get("target_levels")
    if isinstance(levels, list):
        key = "nado_qty" if state.effective_venue == "nado" else "kraken_qty"
        total = 0.0
        for level in levels:
            if isinstance(level, dict):
                total += abs(float(level.get(key) or 0.0))
        if total > 0:
            state.metadata["initial_position_qty"] = total
            return total
    if state.effective_venue == "nado":
        qty = abs(float(state.pair_state.nado_qty or 0.0))
    elif state.effective_venue == "kraken":
        qty = abs(float(state.pair_state.kraken_qty or 0.0))
    else:
        qty = min(abs(float(state.pair_state.nado_qty or 0.0)), abs(float(state.pair_state.kraken_qty or 0.0)))
    if qty > 0:
        state.metadata["initial_position_qty"] = qty
    return qty


def _update_state_potential_pnl(state: ManagedSetupState, live_price: float) -> None:
    entry_price = _state_entry_price(state)
    if entry_price <= 0 or live_price <= 0 or state.side not in {"long", "short"}:
        return
    current_best = float(state.metadata.get("max_favorable_price") or entry_price)
    if state.side == "long":
        favorable_price = max(current_best, live_price)
        pnl_per_unit = favorable_price - entry_price
    else:
        favorable_price = min(current_best, live_price) if current_best > 0 else live_price
        pnl_per_unit = entry_price - favorable_price
    if pnl_per_unit < 0:
        pnl_per_unit = 0.0
    qty = _state_total_directional_qty(state)
    potential_usd = pnl_per_unit * qty if qty > 0 else 0.0
    potential_pct = (pnl_per_unit / entry_price * 100.0) if entry_price > 0 else 0.0
    prev_usd = float(state.metadata.get("max_favorable_pnl_usd") or 0.0)
    if potential_usd + 1e-12 >= prev_usd:
        state.metadata["max_favorable_price"] = favorable_price
        state.metadata["max_favorable_pnl_usd"] = potential_usd
        state.metadata["max_favorable_pnl_pct"] = potential_pct



def _state_risk_to_stop_line(state: ManagedSetupState) -> str:
    entry_price = _state_entry_price(state)
    stop_price = float(state.stop_price or 0.0)
    if entry_price <= 0 or stop_price <= 0:
        return "Risco: N/A até o stop"
    leverage = _setup_leverage_for_state(state)
    risk_pct = abs(entry_price - stop_price) / entry_price * leverage * 100
    return f"Risco: {_bold_notice_value(f'{risk_pct:.2f}%')} até o stop"

def _state_potential_pnl_line(state: ManagedSetupState) -> str:
    price = float(state.metadata.get("max_favorable_price") or 0.0)
    pnl_usd = float(state.metadata.get("max_favorable_pnl_usd") or 0.0)
    pnl_pct = float(state.metadata.get("max_favorable_pnl_pct") or 0.0)
    if price <= 0 and pnl_usd <= 0:
        return "PNL potencial: N/A"
    return f"PNL potencial max: {_bold_notice_value(f'${pnl_usd:.2f}')} ({_bold_notice_value(f'{pnl_pct:+.2f}%')}) @ {price:.8g}"


def _append_setup_event(
    state: ManagedSetupState,
    event_type: str,
    description: str,
    *,
    ts: float | None = None,
) -> None:
    events = state.metadata.get("events")
    if not isinstance(events, list):
        events = []
    events.append({"ts": float(ts or time.time()), "type": event_type, "description": description})
    state.metadata["events"] = events[-20:]


def _format_setup_history(state: ManagedSetupState, *, title: str = "Histórico") -> str:
    events = state.metadata.get("events")
    if not isinstance(events, list) or not events:
        return ""
    lines = [f"⏰ {title}:"]
    for event in events[-8:]:
        if not isinstance(event, dict):
            continue
        lines.append(
            f"{_format_trade_datetime(float(event.get('ts') or time.time()))}: "
            f"{event.get('type', 'Event')} - {event.get('description', '')}"
        )
    return "\n".join(lines)


def _format_entry_notice(
    *,
    title: str,
    setup_key: str,
    symbol: str,
    side: str,
    entry_price: float,
    stop_price: float,
    targets: list[float],
    leverage: float,
    risk_profile: str,
    timeframe: str,
    reason: str,
    venue: str,
    margin_mode: str = "",
) -> str:
    symbol_pair = _format_symbol_pair(symbol)
    base = _symbol_base(symbol_pair)
    setup_label = _setup_notice_strategy(setup_key)
    valid_targets = _ensure_four_notice_targets(targets)
    rr = _notice_rr_label(entry_price, stop_price, valid_targets)
    side_plain = str(side or "").upper() or "N/A"
    audience = os.environ.get("SETUP_NOTIFY_DISCORD_AUDIENCE", "@Intus Club Member").strip()
    clean_reason = str(reason or "Setup detectado pelo robô.").strip().rstrip(".")
    lines = [symbol_pair]
    if audience:
        lines.append(audience)
    lines.extend(
        [
            "",
            _notice_title_line(title),
            "",
            "",
            _notice_subtitle(f"📈 Análise Técnica - {setup_label} - Time Frame {_notice_timeframe_label(timeframe)}"),
            "",
            f"{base} aciona sinal do setup {setup_label} após {clean_reason}.",
            "",
            _notice_subtitle("🧠 Por que ativou:"),
            *_notice_activation_bullets(
                side=side_plain,
                entry_price=entry_price,
                stop_price=stop_price,
                targets=valid_targets,
                reason=clean_reason,
            ),
            "",
            _notice_subtitle("📌 Leitura técnica:"),
            f"A estrutura favorece busca pelos alvos enquanto as condições do setup continuarem sustentando a direção do movimento. Relação risco/retorno estimada: {rr}.",
            "",
            _notice_subtitle("📊 Trading:"),
            "",
            f"💎 Operação: {side_plain}",
            f"⚙️ Alavancagem sugerida: {_leverage_notice_label(leverage)}",
            f"📌 Entrada: {_format_trade_price(entry_price)}",
            f"🛑 Stop: {_format_trade_price(stop_price)}",
            "",
            _notice_subtitle("🎯 Alvos:"),
            *_notice_targets_block(valid_targets),
            "",
            "⚠️ (AS OUTRAS ORDENS SÓ DEVEM SER COLOCADAS SE ACIONAR A ORDEM 1)",
            "",
            "⚡ Após chegar ao ALVO 1, é interessante mudar o stoploss para o ponto de entrada e realizar parcial de acordo com seu gerenciamento de risco.",
            "",
            _notice_subtitle("📕 Gerenciamento de risco:"),
            _notice_risk_text().replace("5%", "**5%**", 1),
        ]
    )
    disclaimer = _notice_disclaimer_text()
    if disclaimer:
        lines.extend(["", _notice_subtitle("⚠️ Disclaimer:"), disclaimer])
    return "\n".join(lines)


def _entry_chart_payload(
    *,
    setup_key: str,
    symbol: str,
    side: str,
    entry_price: float,
    stop_price: float,
    targets: list[float],
    timeframe: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "symbol": _format_symbol_pair(symbol),
        "setup": setup_key,
        "setup_key": setup_key,
        "setup_label": _setup_notice_strategy(setup_key),
        "timeframe": timeframe or "N/A",
        "side": str(side or "").upper() or "N/A",
        "entry_price": float(entry_price or 0.0),
        "stop_price": float(stop_price or 0.0),
        "targets": _ensure_four_notice_targets(targets),
        "reason": str(reason or "Setup detectado pelo robô.").strip(),
    }




def _state_chart_payload(state: ManagedSetupState, *, reason: str = "") -> dict[str, Any]:
    return _entry_chart_payload(
        setup_key=state.setup_key,
        symbol=state.symbol,
        side=state.side,
        entry_price=_state_entry_price(state),
        stop_price=float(state.stop_price or 0.0),
        targets=_state_notice_targets(state),
        timeframe=state.timeframe or "N/A",
        reason=reason or state.entry_reason or "Atualização da operação em monitoramento.",
    )

def _format_state_event_notice(
    *,
    title: str,
    state: ManagedSetupState,
    live_price: float,
    targets_hit: int,
    reason: str,
    history_title: str = "Histórico",
) -> str:
    entry_price = _state_entry_price(state)
    targets = _state_notice_targets(state)
    notice_leverage = _setup_leverage_for_state(state)
    pnl_pct = _directional_notice_weighted_result_pct(
        side=state.side,
        entry_price=entry_price,
        live_price=live_price,
        leverage=notice_leverage,
        targets=targets,
        targets_hit=targets_hit,
    )
    risk_line = _state_risk_to_stop_line(state)
    title_clean = str(title or "🔄 ATUALIZAÇÃO 🔄").strip()
    symbol_clean = _format_trade_symbol(state.symbol)
    sections = [
        *_notice_header_lines(f"{title_clean} | {symbol_clean}"),
        f"Par: {symbol_clean}",
        f"Tipo: {_side_notice_label(state.side)}",
        f"Preço de Entrada: {_format_trade_price(entry_price)}",
        f"Stop Loss: {_format_trade_price(state.stop_price)}",
        "",
        "",
        _notice_subtitle("📊 Status dos Alvos:"),
        *_notice_targets_lines(targets, targets_hit=targets_hit),
        "",
        "",
        _notice_subtitle("📈 Detalhes da Operação:"),
        f"Estratégia: {_setup_notice_strategy(state.setup_key)}",
        f"Timeframe: {state.timeframe or 'N/A'}",
        f"Alavancagem sugerida: {_leverage_notice_label(notice_leverage)}",
        f"Data/Hora: {_format_trade_datetime(state.opened_at_ts or state.pair_state.opened_at)}",
        "",
        "",
        _notice_subtitle("📊 Performance:"),
        f"P&L: {_format_trade_pct(pnl_pct)}",
        risk_line,
    ]
    if reason and "FECHAMENTO MANUAL" in title_clean.upper():
        sections.extend(["", f"📝 {str(reason).strip().upper()}"])
    return "\n".join(sections)

def _reason_is_stop(reason: str) -> bool:
    text = str(reason or "").lower()
    return "stop" in text or "sl_" in text or "stop loss" in text


def _notify_setup_state_event(
    state: ManagedSetupState,
    *,
    title: str,
    live_price: float,
    targets_hit: int | None = None,
    reason: str = "",
    history_title: str = "Histórico",
) -> None:
    message = _format_state_event_notice(
        title=title,
        state=state,
        live_price=live_price,
        targets_hit=state.targets_hit if targets_hit is None else targets_hit,
        reason=reason,
        history_title=history_title,
    )
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    reply_to = str(metadata.get("discord_entry_message_id") or metadata.get("discord_message_id") or "").strip()
    whatsapp_reply_to = str(metadata.get("whatsapp_entry_message_id") or metadata.get("whatsapp_message_id") or "").strip()
    if not reply_to:
        reply_to = _find_recent_discord_entry_message_id(state)
        if reply_to:
            metadata["discord_entry_message_id"] = reply_to
            state.metadata = metadata
    result = _send_setup_trade_notice(
        message,
        chart_payload=_state_chart_payload(state, reason=reason),
        reply_to_discord_message_id=reply_to,
        reply_to_whatsapp_message_id=whatsapp_reply_to,
        include_chart=False,
    )
    if result.get("discord_message_id"):
        metadata["discord_last_update_message_id"] = result["discord_message_id"]
        state.metadata = metadata
    if result.get("whatsapp_message_id"):
        metadata["whatsapp_last_update_message_id"] = result["whatsapp_message_id"]
        state.metadata = metadata


def _notify_setup_entry(
    *,
    plan: SetupOrderPlan,
    side: str,
    venue: str,
    liquidation_price: float,
    liquidation_buffer_pct: float,
    signal: object | None = None,
    risk_profile: str = "moderate",
) -> str:
    """Envia aviso best-effort quando uma entrada live for confirmada."""
    timeframe = str(getattr(signal, "timeframe", "") or SETUP_CATALOG.get(plan.setup_key, SETUP_CATALOG["hybrid"]).timeframe)
    reason = str(getattr(signal, "reason", "") or "Entrada confirmada pelo setup-live.")
    liq_note = f"Liq corretora: {_fmt_liq(liquidation_price)} | Buffer: {liquidation_buffer_pct:.1f}%"
    entry_price = float(plan.entry_price or getattr(signal, "reference_entry_price", 0.0) or 0.0)
    notice_side = side or str(getattr(signal, "side", "") or "")
    stop_price = _plan_notice_stop_price(
        plan=plan,
        signal=signal,
        entry_price=entry_price,
        side=notice_side,
    )
    targets = _fallback_notice_targets(
        entry_price=entry_price,
        side=notice_side,
        explicit_targets=_plan_notice_targets(plan, signal),
    )
    message = _format_entry_notice(
        title="🚨 ENTRAMOS NA OPERAÇÃO 🚨",
        setup_key=plan.setup_key,
        symbol=plan.symbol,
        side=notice_side,
        entry_price=entry_price,
        stop_price=stop_price,
        targets=targets,
        leverage=plan.leverage,
        risk_profile=risk_profile,
        timeframe=timeframe,
        reason=f"{reason} | {liq_note}",
        venue=venue,
        margin_mode=plan.margin_mode,
    )
    result = _send_setup_trade_notice(
        message,
        chart_payload=_entry_chart_payload(
            setup_key=plan.setup_key,
            symbol=plan.symbol,
            side=notice_side,
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            timeframe=timeframe,
            reason=reason,
        ),
    )
    return result


def _notify_setup_opportunity(
    *,
    setup_key: str,
    symbol: str,
    signal: object,
    execution_mode: str,
    leverage: float,
    risk_profile: str,
    plan: SetupOrderPlan | None = None,
    fallback_entry_price: float = 0.0,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
) -> dict[str, str]:
    side = str(getattr(signal, "side", "") or "")
    entry_price = float(
        (plan.entry_price if plan is not None else 0.0)
        or getattr(signal, "reference_entry_price", 0.0)
        or fallback_entry_price
        or 0.0
    )
    stop_price = _plan_notice_stop_price(
        plan=plan,
        signal=signal,
        entry_price=entry_price,
        side=side,
        stop_loss_pct=stop_loss_pct,
    )
    targets = _fallback_notice_targets(
        entry_price=entry_price,
        side=side,
        explicit_targets=_plan_notice_targets(plan, signal) if plan is not None else _signal_notice_targets(signal),
        take_profit_pct=take_profit_pct,
    )
    message = _format_entry_notice(
        title="🚨 NOVA OPERAÇÃO 🚨",
        setup_key=setup_key,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        targets=targets,
        leverage=leverage,
        risk_profile=risk_profile,
        timeframe=str(getattr(signal, "timeframe", "") or ""),
        reason=str(getattr(signal, "reason", "") or "Oportunidade detectada pelo setup-live."),
        venue=plan.venue if plan is not None else execution_mode,
        margin_mode=plan.margin_mode if plan is not None else "",
    )
    result = _send_setup_trade_notice(
        message,
        chart_payload=_entry_chart_payload(
            setup_key=setup_key,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            timeframe=str(getattr(signal, "timeframe", "") or ""),
            reason=str(getattr(signal, "reason", "") or "Oportunidade detectada pelo setup-live."),
        ),
    )
    return result


def _notify_setup_cancelled(
    *,
    setup_key: str,
    symbol: str,
    signal: object,
    execution_mode: str,
    leverage: float,
    risk_profile: str,
    reason: str,
    plan: SetupOrderPlan | None = None,
    fallback_entry_price: float = 0.0,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
) -> dict[str, str]:
    side = str(getattr(signal, "side", "") or "")
    entry_price = float(
        (plan.entry_price if plan is not None else 0.0)
        or getattr(signal, "reference_entry_price", 0.0)
        or fallback_entry_price
        or 0.0
    )
    stop_price = _plan_notice_stop_price(
        plan=plan,
        signal=signal,
        entry_price=entry_price,
        side=side,
        stop_loss_pct=stop_loss_pct,
    )
    targets = _fallback_notice_targets(
        entry_price=entry_price,
        side=side,
        explicit_targets=_plan_notice_targets(plan, signal) if plan is not None else _signal_notice_targets(signal),
        take_profit_pct=take_profit_pct,
    )
    message = _format_entry_notice(
        title="⚠️ OPERAÇÃO CANCELADA ⚠️",
        setup_key=setup_key,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        targets=targets,
        leverage=leverage,
        risk_profile=risk_profile,
        timeframe=str(getattr(signal, "timeframe", "") or ""),
        reason=str(getattr(signal, "reason", "") or "Oportunidade cancelada antes da entrada."),
        venue=plan.venue if plan is not None else execution_mode,
        margin_mode=plan.margin_mode if plan is not None else "",
    )
    result = _send_setup_trade_notice(
        f"{message}\n\n❌ Motivo: {reason}",
        chart_payload=_entry_chart_payload(
            setup_key=setup_key,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_price=stop_price,
            targets=targets,
            timeframe=str(getattr(signal, "timeframe", "") or ""),
            reason=str(getattr(signal, "reason", "") or reason or "Oportunidade cancelada antes da entrada."),
        ),
        include_chart=False,
    )
    return result


def _configure_entry_notifications_from_args(args: argparse.Namespace) -> None:
    """Permite definir o destino de notificação por CLI, mantendo env como fallback."""
    target = str(getattr(args, "notify_entry_target", None) or "").strip()
    channel = str(getattr(args, "notify_entry_channel", None) or "").strip()
    account = str(getattr(args, "notify_entry_account", None) or "").strip()
    discord_channel_id = str(getattr(args, "notify_entry_discord_channel_id", None) or "").strip()
    discord_account = str(getattr(args, "notify_entry_discord_account", None) or "").strip()
    if target:
        os.environ["SETUP_NOTIFY_ENTRY_TARGET"] = target
    if channel:
        os.environ["SETUP_NOTIFY_ENTRY_CHANNEL"] = channel
    if discord_channel_id:
        os.environ["SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID"] = discord_channel_id
    if account:
        os.environ["SETUP_NOTIFY_ENTRY_ACCOUNT"] = account
    if discord_account:
        os.environ["SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT"] = discord_account
    if bool(getattr(args, "no_notify_entry", False)):
        os.environ["SETUP_NOTIFY_ENTRY_ENABLED"] = "false"
    elif target or channel or account or discord_channel_id or discord_account:
        os.environ.setdefault("SETUP_NOTIFY_ENTRY_ENABLED", "true")
    resolved_target = os.environ.get("SETUP_NOTIFY_ENTRY_TARGET", "").strip()
    resolved_discord = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "").strip()
    notifications_enabled = os.environ.get("SETUP_NOTIFY_ENTRY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "nao", "off"}
    if resolved_target and notifications_enabled:
        logger.info(
            "setup-live notificacao de entrada ativa | channel=%s | target=%s",
            os.environ.get("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram").strip() or "telegram",
            resolved_target,
        )
    if resolved_discord and notifications_enabled:
        logger.info("setup-live notificacao extra Discord ativa | target=%s", _normalize_message_target("discord", resolved_discord))


def _get_kraken_entry_snapshot(eng: DeltaNeutralEngine) -> dict:
    safety = getattr(eng.kraken, "get_trading_safety", lambda **_: {})() or {}
    available_margin = 0.0
    overview_error = ""
    try:
        overview = eng.kraken.get_accounts_overview()
        selected = overview.get("selected") or {}
        selected_account = str(selected.get("account") or "").lower()
        for account in overview.get("accounts") or []:
            if str(account.get("name") or "").lower() != selected_account:
                continue
            available_margin = float(
                account.get("available_margin")
                or account.get("available_funds")
                or 0.0
            )
            break
    except Exception as exc:  # noqa: BLE001
        overview_error = f"margem Kraken indisponivel: {exc}"
    return {
        "available_margin": available_margin,
        "safe": bool(safety.get("safe")),
        "safety_label": str(safety.get("label") or ""),
        "safety_reason": str(safety.get("reason") or ""),
        "error": overview_error,
    }


def _assess_setup_entry_readiness(
    eng: DeltaNeutralEngine,
    *,
    managed_states: list[ManagedSetupState],
    requested_notional_usd: float | None,
    requested_margin_usd: float | None = None,
    nado_margin_usd: float | None = None,
    kraken_margin_usd: float | None = None,
    leverage: float = 0.0,
    execution_mode: str = EXECUTION_MODE_HEDGED,
    max_open_setups: int = 0,
    account_margin_reserve_usd: float = 0.0,
    account_margin_reserve_pct: float = 0.0,
    account_margin_slots: int = 0,
    account_max_maint_usage_pct: float = 0.0,
    account_stress_pct: float = 0.0,
) -> dict:
    nado = _get_nado_entry_snapshot(eng)
    dex_label = str(nado.get("venue_label") or "DEX")
    dex_health_required = bool(nado.get("health_required", True))
    kraken = _get_kraken_entry_snapshot(eng)
    account_equity = float(nado.get("maintenance_assets") or nado.get("balance") or 0.0)
    resolved_reserve_usd, account_budget_usd, account_margin_per_slot = _resolve_account_margin_budget(
        equity_usd=account_equity,
        reserve_usd=account_margin_reserve_usd,
        reserve_pct=account_margin_reserve_pct,
        slots=account_margin_slots,
    )
    if (
        account_margin_per_slot > 0
        and float(requested_margin_usd or 0.0) <= 0
        and float(nado_margin_usd or 0.0) <= 0
        and float(kraken_margin_usd or 0.0) <= 0
    ):
        requested_margin_usd = account_margin_per_slot
    operational_margin_usd = _resolve_margin_for_execution_mode(
        execution_mode,
        requested_margin_usd,
        nado_margin_usd,
        kraken_margin_usd,
    )
    requested_notional, generic_margin, sizing_source, _ = _resolve_operational_notional(
        notional_usd=requested_notional_usd,
        margin_usd=operational_margin_usd,
        leverage=leverage,
        default_notional_usd=eng.volume_per_leg,
    )
    nado_requested_margin = float(nado_margin_usd or generic_margin or 0.0)
    kraken_requested_margin = float(kraken_margin_usd or generic_margin or 0.0)

    min_nado_balance_ratio = _load_float_env("SETUP_ENTRY_MIN_NADO_BALANCE_RATIO", 0.05)
    min_kraken_margin_ratio = _load_float_env("SETUP_ENTRY_MIN_KRAKEN_MARGIN_RATIO", 0.20)
    min_nado_initial_health = _load_float_env("SETUP_ENTRY_MIN_NADO_INITIAL_HEALTH", 2.0)

    blockers: list[str] = []
    warnings: list[str] = []

    required_nado_balance = (
        nado_requested_margin
        if nado_requested_margin > 0
        else requested_notional * min_nado_balance_ratio
    )
    required_kraken_margin = (
        kraken_requested_margin
        if kraken_requested_margin > 0
        else requested_notional * min_kraken_margin_ratio
    )

    needs_nado = execution_mode in {EXECUTION_MODE_HEDGED, EXECUTION_MODE_NADO_ONLY}
    needs_kraken = execution_mode in {EXECUTION_MODE_HEDGED, EXECUTION_MODE_KRAKEN_ONLY}

    if needs_nado and nado["error"]:
        blockers.append(str(nado["error"]))
    if needs_kraken and kraken["error"]:
        blockers.append(str(kraken["error"]))
    if needs_nado and float(nado["balance"]) < required_nado_balance:
        blockers.append(
            f"saldo {dex_label} insuficiente (${float(nado['balance']):.2f} < ${required_nado_balance:.2f})"
        )
    if needs_nado and dex_health_required and float(nado["initial_health"]) < min_nado_initial_health:
        blockers.append(
            f"health inicial da {dex_label} insuficiente ({float(nado['initial_health']):.2f} < {min_nado_initial_health:.2f})"
        )
    maint_usage = float(nado.get("maintenance_usage_pct") or 0.0)
    if needs_nado and dex_health_required and account_max_maint_usage_pct > 0 and maint_usage >= account_max_maint_usage_pct:
        blockers.append(
            f"uso de margem de manutencao {dex_label} alto ({maint_usage:.2f}% >= {account_max_maint_usage_pct:.2f}%)"
        )
    if needs_nado and dex_health_required and account_budget_usd > 0:
        current_slots = len([state for state in managed_states if state.effective_venue in {"nado", "hedged"}])
        if account_margin_slots > 0 and current_slots >= account_margin_slots:
            blockers.append(f"slots de margem {dex_label} esgotados ({current_slots} >= {account_margin_slots})")
        projected_reserved = resolved_reserve_usd + nado_requested_margin
        if float(nado.get("maintenance_health") or 0.0) < projected_reserved:
            blockers.append(
                f"reserva cross {dex_label} insuficiente apos entrada (${float(nado.get('maintenance_health') or 0.0):.2f} < ${projected_reserved:.2f})"
            )
        if account_stress_pct > 0:
            managed_notional = sum(
                abs(float(getattr(state.pair_state, "effective_notional_usd", 0.0) or 0.0))
                for state in managed_states
                if state.effective_venue in {"nado", "hedged"}
            )
            stress_loss = (managed_notional + requested_notional) * account_stress_pct / 100
            stress_health = float(nado.get("maintenance_health") or 0.0) - stress_loss
            if stress_health < resolved_reserve_usd:
                blockers.append(
                    f"stress cross {dex_label} insuficiente | queda {account_stress_pct:.1f}% deixa health ${stress_health:.2f} < reserva ${resolved_reserve_usd:.2f}"
                )
    if needs_kraken and float(kraken["available_margin"]) < required_kraken_margin:
        blockers.append(
            f"margem Kraken insuficiente (${float(kraken['available_margin']):.2f} < ${required_kraken_margin:.2f})"
        )
    if max_open_setups > 0 and len(managed_states) >= max_open_setups:
        blockers.append(f"limite de setups abertos atingido ({len(managed_states)} >= {max_open_setups})")
    if needs_nado and not bool(nado["trade_ready"]):
        warnings.append(str(nado["trade_auth_error"] or f"{dex_label} trade_ready=nao"))
    if needs_kraken and not bool(kraken["safe"]):
        warnings.append(str(kraken["safety_reason"] or "Kraken trading unsafe"))

    return {
        "can_open": not blockers,
        "requested_notional_usd": requested_notional,
        "requested_margin_usd": generic_margin,
        "nado_requested_margin_usd": nado_requested_margin,
        "kraken_requested_margin_usd": kraken_requested_margin,
        "sizing_source": sizing_source,
        "managed_states": len(managed_states),
        "dex_venue_label": dex_label,
        "dex_health_required": dex_health_required,
        "dex_balance": float(nado["balance"]),
        "nado_balance": float(nado["balance"]),
        "nado_initial_health": float(nado["initial_health"]),
        "nado_maintenance_health": float(nado["maintenance_health"]),
        "nado_maintenance_usage_pct": maint_usage,
        "account_equity_usd": account_equity,
        "account_reserve_usd": resolved_reserve_usd,
        "account_budget_usd": account_budget_usd,
        "account_margin_per_slot_usd": account_margin_per_slot,
        "account_margin_slots": account_margin_slots,
        "account_max_maint_usage_pct": account_max_maint_usage_pct,
        "account_stress_pct": account_stress_pct,
        "kraken_available_margin": float(kraken["available_margin"]),
        "kraken_safety_label": str(kraken["safety_label"]),
        "blockers": blockers,
        "warnings": warnings,
    }


def _log_setup_entry_readiness(snapshot: dict) -> None:
    logger.info(
        "setup-live prontidao | entradas=%s | sizing=%s | notional=$%.2f | margin_dex=$%.2f | margin_cex=$%.2f | dex=%s balance=$%.2f | dex_health=%.2f | maint_usage=%.2f%% | acct_budget=$%.2f | slot_margin=$%.2f | cex_margin=$%.2f | setups_abertos=%d | cex=%s",
        _bool_pt(bool(snapshot.get("can_open"))),
        snapshot.get("sizing_source") or "notional",
        float(snapshot.get("requested_notional_usd") or 0.0),
        float(snapshot.get("nado_requested_margin_usd") or 0.0),
        float(snapshot.get("kraken_requested_margin_usd") or 0.0),
        snapshot.get("dex_venue_label") or "DEX",
        float(snapshot.get("nado_balance") or 0.0),
        float(snapshot.get("nado_initial_health") or 0.0),
        float(snapshot.get("nado_maintenance_usage_pct") or 0.0),
        float(snapshot.get("account_budget_usd") or 0.0),
        float(snapshot.get("account_margin_per_slot_usd") or 0.0),
        float(snapshot.get("kraken_available_margin") or 0.0),
        int(snapshot.get("managed_states") or 0),
        snapshot.get("kraken_safety_label") or "-",
    )
    for warning in snapshot.get("warnings") or []:
        logger.warning("setup-live aviso: %s", warning)
    for blocker in snapshot.get("blockers") or []:
        logger.warning("setup-live bloqueio: %s", blocker)


def _preflight_symbol_entry(
    eng: DeltaNeutralEngine,
    *,
    symbol: str,
    requested_notional_usd: float | None,
    requested_margin_usd: float | None = None,
    leverage: float = 0.0,
) -> tuple[bool, str]:
    requested_notional, _, _, sizing_error = _resolve_operational_notional(
        notional_usd=requested_notional_usd,
        margin_usd=requested_margin_usd,
        leverage=leverage,
        default_notional_usd=eng.volume_per_leg,
    )
    if sizing_error:
        return False, sizing_error
    build_pair_sizing_plan = getattr(eng, "build_pair_sizing_plan", None)
    if callable(build_pair_sizing_plan):
        plan = build_pair_sizing_plan(symbol, requested_notional)
        return bool(plan.can_execute), str(plan.blocked_reason or "")

    notional = requested_notional
    pid = eng._nado_symbol_map[symbol]
    kraken_symbol = eng._kraken_symbol_map[symbol]
    nado_mid = eng.nado.get_market_mid_price(pid)
    kraken_mid = eng.kraken.get_market_mid_price(kraken_symbol)
    if nado_mid <= 0 or kraken_mid <= 0:
        return False, f"precos invalidos (nado={nado_mid:.4f} kraken={kraken_mid:.4f})"

    nado_target_qty = float(eng.nado.round_quantity_to_increment(pid, notional / nado_mid))
    kraken_target_qty = float(eng.kraken.round_quantity_to_increment(kraken_symbol, notional / kraken_mid))
    if nado_target_qty <= 0 or kraken_target_qty <= 0:
        return False, f"qty minima inviavel (nado={nado_target_qty} kraken={kraken_target_qty})"

    common_qty = min(nado_target_qty, kraken_target_qty)
    nado_qty = float(eng.nado.round_quantity_to_increment(pid, common_qty))
    kraken_qty = float(eng.kraken.round_quantity_to_increment(kraken_symbol, common_qty))
    if nado_qty <= 0 or kraken_qty <= 0:
        return False, f"qty comum inviavel (nado={nado_qty} kraken={kraken_qty})"
    return True, ""


def _setup_uses_managed_targets(setup_key: str, signal: object) -> bool:
    return bool(getattr(signal, "take_profit_targets", None)) and is_directional_setup(setup_key)


def _risk_profile_leverage(profile: str | None) -> float:
    resolved = normalize_hybrid_profile(profile)
    return float(DEFAULT_RISK_PROFILE_LEVERAGE.get(resolved, DEFAULT_RISK_PROFILE_LEVERAGE[DEFAULT_HYBRID_PROFILE]))


def _estimate_liquidation_price(entry_price: float, side: str, leverage: float) -> float:
    if entry_price <= 0 or leverage <= 1:
        return 0.0
    if side == "long":
        return float(entry_price * (1 - 1 / leverage))
    return float(entry_price * (1 + 1 / leverage))


def _liquidation_buffer_pct(entry_price: float, stop_price: float, liquidation_price: float) -> float:
    if entry_price <= 0 or stop_price <= 0 or liquidation_price <= 0:
        return 999.0
    full_distance = abs(entry_price - liquidation_price)
    if full_distance <= 0:
        return 0.0
    remaining_distance = abs(stop_price - liquidation_price)
    return float((remaining_distance / full_distance) * 100)


def _fmt_liq(value: float) -> str:
    return f"{value:.4f}" if value and value > 0 else "corretora_pendente"


def _execution_mode_for_setup(setup_key: str, requested_mode: str) -> str:
    if is_hedged_only_setup(setup_key):
        return EXECUTION_MODE_HEDGED
    return requested_mode


def _margin_mode_for_venue(
    *,
    venue: str,
    margin_mode: str,
    nado_margin_mode: str,
    kraken_margin_mode: str,
    config,
) -> str:
    if venue == "nado":
        return nado_margin_mode or margin_mode or config.nado_margin_mode or MARGIN_MODE_CROSS
    if venue == "kraken":
        return kraken_margin_mode or margin_mode or config.kraken_margin_mode or MARGIN_MODE_CROSS
    return margin_mode or MARGIN_MODE_CROSS


def _resolve_operational_notional(
    *,
    notional_usd: float | None,
    margin_usd: float | None,
    leverage: float,
    default_notional_usd: float,
) -> tuple[float, float, str, str]:
    requested_margin = float(margin_usd or 0.0)
    if requested_margin > 0:
        if leverage <= 0:
            return 0.0, requested_margin, "margin_x_leverage", "--margin-usd exige leverage > 0"
        return float(requested_margin * leverage), requested_margin, "margin_x_leverage", ""
    return float(notional_usd or default_notional_usd), 0.0, "notional", ""


def _resolve_margin_for_execution_mode(
    execution_mode: str,
    margin_usd: float | None,
    nado_margin_usd: float | None,
    kraken_margin_usd: float | None,
) -> float:
    generic_margin = float(margin_usd or 0.0)
    nado_margin = float(nado_margin_usd or 0.0)
    kraken_margin = float(kraken_margin_usd or 0.0)
    if generic_margin > 0:
        return generic_margin
    if execution_mode == EXECUTION_MODE_NADO_ONLY:
        return nado_margin
    if execution_mode == EXECUTION_MODE_KRAKEN_ONLY:
        return kraken_margin
    if execution_mode == EXECUTION_MODE_HEDGED and nado_margin > 0 and kraken_margin > 0:
        return min(nado_margin, kraken_margin)
    return 0.0


def _effective_venue_for_execution_mode(execution_mode: str) -> str:
    if execution_mode == EXECUTION_MODE_NADO_ONLY:
        return "nado"
    if execution_mode == EXECUTION_MODE_KRAKEN_ONLY:
        return "kraken"
    return "hedged"


def _opposite_side(side: str) -> str:
    return "short" if side == "long" else "long"


def _build_dry_run_target_levels(
    *,
    targets: list[float],
    target_weights: list[float],
    total_qty: float,
    effective_venue: str,
) -> list[dict]:
    valid_targets = [float(target) for target in targets if float(target or 0.0) > 0]
    if not valid_targets:
        return []
    qty = max(float(total_qty or 0.0), 1.0)
    weights = list(target_weights) if target_weights else [1 / len(valid_targets)] * len(valid_targets)
    if len(weights) != len(valid_targets):
        weights = [1 / len(valid_targets)] * len(valid_targets)
    levels: list[dict] = []
    remaining_qty = qty
    for idx, target in enumerate(valid_targets, start=1):
        split_qty = remaining_qty if idx == len(valid_targets) else max(qty * float(weights[idx - 1]), 0.0)
        remaining_qty = max(remaining_qty - split_qty, 0.0)
        levels.append(
            {
                "label": f"TP{idx}",
                "price": target,
                "nado_qty": split_qty if effective_venue in {"hedged", "nado"} else 0.0,
                "kraken_qty": split_qty if effective_venue in {"hedged", "kraken"} else 0.0,
            }
        )
    return levels


def _build_dry_run_setup_state(
    eng: DeltaNeutralEngine,
    *,
    setup_key: str,
    symbol: str,
    df: pd.DataFrame,
    signal: object,
    execution_mode: str,
    leverage: float,
    hybrid_profile: str,
    plan: SetupOrderPlan | None,
    fallback_entry_price: float,
    notional_usd: float | None,
    margin_usd: float | None,
    nado_margin_usd: float | None,
    kraken_margin_usd: float | None,
    margin_mode: str,
    nado_margin_mode: str,
    kraken_margin_mode: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    target_stop_mode: str = TARGET_STOP_MODE_OFF,
) -> ManagedSetupState:
    side = str(getattr(signal, "side", "") or "")
    effective_venue = plan.venue if plan is not None else _effective_venue_for_execution_mode(execution_mode)
    execution_config = get_setup_execution_config(setup_key)
    setup_margin_mode = normalize_margin_mode(margin_mode) or MARGIN_MODE_CROSS
    nado_mode = normalize_margin_mode(nado_margin_mode) or execution_config.nado_margin_mode or setup_margin_mode
    kraken_mode = normalize_margin_mode(kraken_margin_mode) or execution_config.kraken_margin_mode or setup_margin_mode
    if plan is not None:
        requested_notional = float(plan.requested_notional_usd or 0.0)
        requested_margin = float(plan.requested_margin_usd or 0.0)
        sizing_source = plan.sizing_source
        entry_price = float(plan.entry_price or getattr(signal, "reference_entry_price", 0.0) or fallback_entry_price or 0.0)
        quantity = float(plan.quantity or 0.0)
        margin_label = plan.margin_mode
        effective_notional = float(plan.effective_notional_usd or 0.0)
    else:
        requested_margin_input = _resolve_margin_for_execution_mode(
            execution_mode,
            margin_usd,
            nado_margin_usd,
            kraken_margin_usd,
        )
        requested_notional, requested_margin, sizing_source, _ = _resolve_operational_notional(
            notional_usd=notional_usd,
            margin_usd=requested_margin_input,
            leverage=leverage,
            default_notional_usd=eng.volume_per_leg,
        )
        entry_price = float(getattr(signal, "reference_entry_price", 0.0) or fallback_entry_price or 0.0)
        quantity = float(requested_notional / entry_price) if entry_price > 0 and requested_notional > 0 else 1.0
        margin_label = setup_margin_mode
        effective_notional = float(quantity * entry_price) if entry_price > 0 else float(requested_notional or 0.0)
    if quantity <= 0:
        quantity = 1.0

    reference_entry_price = float(getattr(signal, "reference_entry_price", 0.0) or entry_price or 0.0)
    signal_stop = float(getattr(signal, "stop_price", 0.0) or 0.0)
    actual_stop_price = _rebase_reference_price(signal_stop, from_entry=reference_entry_price, to_entry=entry_price)
    if stop_loss_pct > 0:
        actual_stop_price = _stop_price_from_pct(entry_price, side, stop_loss_pct)
    stop_price = _fallback_notice_stop_price(
        entry_price=entry_price,
        side=side,
        explicit_stop_price=actual_stop_price or signal_stop,
        stop_loss_pct=stop_loss_pct,
    )

    explicit_targets = _plan_notice_targets(plan, signal) if plan is not None else _signal_notice_targets(signal)
    if plan is None and explicit_targets and reference_entry_price > 0 and entry_price > 0:
        explicit_targets = [
            _rebase_reference_price(float(target), from_entry=reference_entry_price, to_entry=entry_price)
            for target in explicit_targets
        ]
    targets = _fallback_notice_targets(
        entry_price=entry_price,
        side=side,
        explicit_targets=explicit_targets,
        take_profit_pct=take_profit_pct,
    )
    take_profit = targets[-1] if targets else _take_profit_price_from_pct(
        entry_price,
        side,
        _notice_take_profit_pct(take_profit_pct),
    )
    target_levels = _build_dry_run_target_levels(
        targets=targets,
        target_weights=list(getattr(signal, "target_weights", []) or []),
        total_qty=quantity,
        effective_venue=effective_venue,
    )
    opened_ts = time.time()
    try:
        opened_bar_at = str(df.iloc[-1]["timestamp"].isoformat())
    except Exception:  # noqa: BLE001
        opened_bar_at = ""
    product_id = int((plan.nado_product_id if plan is not None else 0) or eng._nado_symbol_map.get(symbol, 0) or 0)
    kraken_symbol = str((plan.kraken_symbol if plan is not None else "") or eng._kraken_symbol_map.get(symbol, symbol) or symbol)
    pair_state = PairState(
        symbol=symbol,
        nado_product_id=product_id,
        kraken_symbol=kraken_symbol,
        nado_side=side,
        kraken_side=_opposite_side(side),
        requested_notional_usd=requested_notional,
        effective_notional_usd=effective_notional,
        nado_qty=quantity if effective_venue in {"hedged", "nado"} else 0.0,
        kraken_qty=quantity if effective_venue in {"hedged", "kraken"} else 0.0,
        nado_entry=entry_price,
        kraken_entry=entry_price,
        requested_margin_usd=requested_margin,
        sizing_source=sizing_source,
        kraken_requested_leverage=leverage if effective_venue in {"hedged", "kraken"} else 0.0,
        kraken_margin_mode=kraken_mode if effective_venue in {"hedged", "kraken"} else "",
        execution_mode=execution_mode,
        effective_venue=effective_venue,
        nado_requested_leverage=leverage if effective_venue in {"hedged", "nado"} else 0.0,
        nado_margin_mode=nado_mode if effective_venue in {"hedged", "nado"} else "",
        pair_stop_loss_pct=_notice_stop_loss_pct(stop_loss_pct),
        pair_take_profit_pct=_notice_take_profit_pct(take_profit_pct),
        nado_stop_price=stop_price if effective_venue in {"hedged", "nado"} else 0.0,
        kraken_stop_price=stop_price if effective_venue in {"hedged", "kraken"} else 0.0,
        nado_take_profit_price=take_profit if effective_venue in {"hedged", "nado"} else 0.0,
        kraken_take_profit_price=take_profit if effective_venue in {"hedged", "kraken"} else 0.0,
        nado_close_side=_opposite_side(side),
        kraken_close_side=side,
        opened_at=opened_ts,
    )
    metadata = dict(getattr(signal, "metadata", {}) or {})
    metadata.update(
        {
            "dry_run": True,
            "tracking_only": True,
            "execution_mode": execution_mode,
            "effective_venue": effective_venue,
            "margin_mode": margin_label,
            "leverage": leverage,
            "requested_margin_usd": requested_margin,
            "sizing_source": sizing_source,
            "stop_loss_pct": stop_loss_pct,
            "target_stop_mode": target_stop_mode,
            "target_stop_native_replacement": "managed_loop",
            "events": [
                {"ts": opened_ts, "type": "New", "description": "dry-run tracking started"},
                {
                    "ts": opened_ts,
                    "type": "Entry",
                    "description": f"{side.upper()} simulated at {entry_price}",
                },
            ],
        }
    )
    if target_levels:
        metadata["target_levels"] = target_levels
    return ManagedSetupState(
        setup_key=setup_key,
        symbol=symbol,
        timeframe=str(getattr(signal, "timeframe", "") or SETUP_CATALOG.get(setup_key, SETUP_CATALOG["hybrid"]).timeframe),
        side=side,
        pair_state=pair_state,
        hybrid_profile=hybrid_profile,
        reference_entry_price=entry_price,
        stop_price=stop_price,
        take_profit=take_profit,
        close_after_bars=int(getattr(signal, "close_after_bars", 0) or 0),
        entry_reason=str(getattr(signal, "reason", "") or ""),
        execution_mode=execution_mode,
        effective_venue=effective_venue,
        margin_mode=margin_label,
        leverage=leverage,
        opened_bar_at=opened_bar_at,
        opened_at_ts=opened_ts,
        metadata=metadata,
    )


def _nado_min_order_notional_usd(eng: DeltaNeutralEngine, product_id: int, entry_price: float, min_qty: float) -> float:
    min_notional_getter = getattr(eng.nado, "get_min_order_notional_usd", None)
    native_min = float(min_notional_getter(product_id) if callable(min_notional_getter) else 0.0)
    qty_min = float(min_qty * entry_price) if min_qty > 0 and entry_price > 0 else 0.0
    override_min = _load_float_env("NADO_MIN_ORDER_NOTIONAL_USD", 0.0)
    if override_min > 0:
        return max(override_min, qty_min)
    return max(native_min, qty_min)


def _nado_native_protection_block_reason(
    eng: DeltaNeutralEngine,
    *,
    product_id: int,
    effective_notional_usd: float,
    signal: object,
) -> str:
    min_notional_getter = getattr(eng.nado, "get_min_order_notional_usd", None)
    min_notional = float(min_notional_getter(product_id) if callable(min_notional_getter) else 0.0)
    override_min = _load_float_env("NADO_MIN_ORDER_NOTIONAL_USD", 0.0)
    if override_min > 0:
        min_notional = override_min
    if min_notional <= 0:
        return ""
    if effective_notional_usd + 1e-9 < min_notional:
        return (
            "nocional Nado abaixo do minimo para SL/TP nativo "
            f"(${effective_notional_usd:.2f} < ${min_notional:.2f})"
        )
    targets = list(getattr(signal, "take_profit_targets", []) or [])
    if len(targets) <= 1:
        return ""
    weights = list(getattr(signal, "target_weights", []) or [])
    if len(weights) != len(targets):
        weights = [1 / len(targets)] * len(targets)
    positive_weights = [float(weight) for weight in weights if float(weight) > 0]
    if not positive_weights:
        return ""
    smallest_weight = min(positive_weights)
    smallest_target_notional = effective_notional_usd * smallest_weight
    if smallest_target_notional + 1e-9 < min_notional:
        return (
            "TP parcial Nado abaixo do minimo nativo "
            f"(${smallest_target_notional:.2f} < ${min_notional:.2f}); "
            f"use notional >= ${min_notional / smallest_weight:.2f} para {len(targets)} TPs"
        )
    return ""


def _build_single_venue_order_plan(
    eng: DeltaNeutralEngine,
    *,
    setup_key: str,
    symbol: str,
    venue: str,
    signal: object,
    notional_usd: float | None,
    margin_mode: str,
    leverage: float,
    min_liquidation_buffer_pct: float,
    margin_usd: float | None = None,
    stop_loss_pct: float = 0.0,
) -> SetupOrderPlan:
    take_profit = float(getattr(signal, "take_profit", 0.0) or 0.0)
    side = str(getattr(signal, "side", "") or "")
    requested_notional, requested_margin, sizing_source, sizing_error = _resolve_operational_notional(
        notional_usd=notional_usd,
        margin_usd=margin_usd,
        leverage=leverage,
        default_notional_usd=eng.volume_per_leg,
    )
    signal_stop_price = float(getattr(signal, "stop_price", 0.0) or 0.0)

    if venue == "nado":
        if symbol not in eng._nado_symbol_map:
            return SetupOrderPlan(setup_key, symbol, EXECUTION_MODE_NADO_ONLY, venue, margin_mode, leverage, requested_notional, 0.0, requested_margin, sizing_source, 0.0, 0.0, signal_stop_price, take_profit, 0.0, 0.0, False, f"{symbol} nao listado na Nado")
        product_id = eng._nado_symbol_map[symbol]
        entry_price = float(eng.nado.get_market_mid_price(product_id) or 0.0)
        valid_entry_price = eng._is_valid_market_price(entry_price)
        qty = float(eng.nado.round_quantity_to_increment(product_id, requested_notional / entry_price)) if valid_entry_price else 0.0
        min_qty = eng._infer_nado_min_quantity(product_id)
        min_notional = _nado_min_order_notional_usd(eng, product_id, entry_price, min_qty) if valid_entry_price else 0.0
        kraken_symbol = eng._kraken_symbol_map.get(symbol, "")
    else:
        if symbol not in eng._kraken_symbol_map:
            return SetupOrderPlan(setup_key, symbol, EXECUTION_MODE_KRAKEN_ONLY, venue, margin_mode, leverage, requested_notional, 0.0, requested_margin, sizing_source, 0.0, 0.0, signal_stop_price, take_profit, 0.0, 0.0, False, f"{symbol} nao listado na Kraken")
        kraken_symbol = eng._kraken_symbol_map[symbol]
        entry_price = float(eng.kraken.get_market_mid_price(kraken_symbol) or 0.0)
        valid_entry_price = eng._is_valid_market_price(entry_price)
        qty = float(eng.kraken.round_quantity_to_increment(kraken_symbol, requested_notional / entry_price)) if valid_entry_price else 0.0
        min_qty = eng._infer_kraken_min_quantity(kraken_symbol)
        min_notional = min_qty * entry_price if min_qty > 0 and valid_entry_price else 0.0
        product_id = eng._nado_symbol_map.get(symbol, 0)

    effective_notional = qty * entry_price if qty > 0 and entry_price > 0 else 0.0
    stop_price = _stop_price_from_pct(entry_price, side, stop_loss_pct) or signal_stop_price
    # Antes da ordem, a liquidação real ainda não existe: ela deve vir da corretora/venue
    # depois da entrada confirmada. Não usar a estimativa teórica de 1/leverage para
    # bloquear uma entrada cujo stop gerenciado é 20%; isso confundia stop com liquidação.
    liquidation_price = 0.0
    buffer_pct = 999.0
    blocked_reason = ""
    if sizing_error:
        blocked_reason = sizing_error
    elif not eng._is_valid_market_price(entry_price):
        blocked_reason = f"preco invalido em {venue}: {entry_price:.8g}"
    elif qty <= 0:
        blocked_reason = f"nocional abaixo do minimo executavel | {venue} ~${min_notional:.2f}"
    elif min_notional > 0 and effective_notional + 1e-9 < min_notional:
        blocked_reason = (
            f"notional abaixo do minimo do ativo | {venue} "
            f"${effective_notional:.2f} < ${min_notional:.2f}"
        )
    return SetupOrderPlan(
        setup_key=setup_key,
        symbol=symbol,
        execution_mode=EXECUTION_MODE_NADO_ONLY if venue == "nado" else EXECUTION_MODE_KRAKEN_ONLY,
        venue=venue,
        margin_mode=margin_mode,
        leverage=leverage,
        requested_notional_usd=requested_notional,
        effective_notional_usd=effective_notional,
        requested_margin_usd=requested_margin,
        sizing_source=sizing_source,
        quantity=qty,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit=take_profit,
        liquidation_price=liquidation_price,
        liquidation_buffer_pct=buffer_pct,
        can_execute=not blocked_reason,
        blocked_reason=blocked_reason,
        nado_product_id=product_id,
        kraken_symbol=kraken_symbol,
    )


def _safe_from_x18(raw: object) -> float:
    try:
        return float(from_x18(raw))
    except Exception:
        return 0.0


def _nado_trigger_order_detail(item: object) -> dict:
    wrapper = getattr(item, "order", None)
    order = getattr(wrapper, "order", None)
    trigger = getattr(wrapper, "trigger", None)
    trigger_dict = trigger.dict() if hasattr(trigger, "dict") else trigger or {}
    requirement = {}
    if isinstance(trigger_dict, dict):
        requirement = ((trigger_dict.get("price_trigger") or {}).get("price_requirement") or {})
    trigger_key = ""
    trigger_raw = 0
    if isinstance(requirement, dict) and requirement:
        trigger_key, trigger_raw = next(iter(requirement.items()))
    amount = _safe_from_x18(getattr(order, "amount", 0))
    return {
        "product_id": int(getattr(wrapper, "product_id", 0) or 0),
        "digest": str(getattr(wrapper, "digest", "") or ""),
        "amount": amount,
        "qty": abs(amount),
        "side": "buy" if amount > 0 else "sell",
        "exec_price": _safe_from_x18(getattr(order, "priceX18", 0)),
        "trigger_key": trigger_key,
        "trigger_price": _safe_from_x18(trigger_raw),
        "status": str(getattr(item, "status", "") or ""),
        "placed_at": int(getattr(item, "placed_at", 0) or 0),
    }


def _format_nado_trigger_levels(levels: list[dict]) -> str:
    if not levels:
        return "-"
    return ", ".join(
        f"{float(level['qty']):.8g}@{float(level['trigger_price']):.8g}"
        f"{'(!min)' if level.get('below_min') else ''}"
        for level in sorted(levels, key=lambda item: float(item.get("trigger_price") or 0.0))
    )


def _collect_nado_trigger_summary(eng: DeltaNeutralEngine, nado_positions: list[object]) -> dict[int, dict[str, list[dict]]]:
    product_ids = [int(getattr(position, "product_id", 0) or 0) for position in nado_positions]
    product_ids = [product_id for product_id in product_ids if product_id > 0]
    if not product_ids or not hasattr(eng.nado, "get_trigger_orders"):
        return {}
    try:
        trigger_orders = eng.nado.get_trigger_orders(product_ids=product_ids, reduce_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nao foi possivel consultar trigger orders da Nado: %s", exc)
        return {}
    positions_by_product = {int(position.product_id): position for position in nado_positions}
    summary: dict[int, dict[str, list[dict]]] = {}
    for item in trigger_orders:
        detail = _nado_trigger_order_detail(item)
        product_id = int(detail["product_id"])
        position = positions_by_product.get(product_id)
        if position is None or detail["qty"] <= 0:
            continue
        min_notional_getter = getattr(eng.nado, "get_min_order_notional_usd", None)
        min_notional = float(min_notional_getter(product_id) if callable(min_notional_getter) else 0.0)
        detail["notional"] = abs(float(detail["qty"]) * float(detail["trigger_price"]))
        detail["min_notional"] = min_notional
        detail["below_min"] = bool(min_notional > 0 and float(detail["notional"]) + 1e-9 < min_notional)
        trigger_key = str(detail["trigger_key"])
        is_long = str(getattr(position, "side", "")).lower() == "long"
        is_take_profit = ("above" in trigger_key and is_long) or ("below" in trigger_key and not is_long)
        bucket = "tp" if is_take_profit else "sl"
        summary.setdefault(product_id, {"tp": [], "sl": []})[bucket].append(detail)
    return summary


def _log_live_status(eng: DeltaNeutralEngine, *, header: str | None = None) -> bool:
    nado_positions, kraken_positions, summary = _collect_live_status(eng)
    if not nado_positions and not kraken_positions:
        logger.info("(sem posicoes live)")
        return False

    if header:
        logger.info(header)

    nado_trigger_summary = _collect_nado_trigger_summary(eng, nado_positions)
    managed_states = load_setup_live_states()
    managed_nado_products = {
        int(state.pair_state.nado_product_id)
        for state in managed_states
        if state.effective_venue in {"nado", "hedged"} and int(state.pair_state.nado_product_id or 0) > 0
    }
    managed_kraken_symbols = {
        str(state.pair_state.kraken_symbol or "").upper()
        for state in managed_states
        if state.effective_venue in {"kraken", "hedged"} and str(state.pair_state.kraken_symbol or "")
    }
    for position in nado_positions:
        product_id = int(getattr(position, "product_id", 0) or 0)
        managed_label = "managed" if product_id in managed_nado_products else "ORPHAN"
        logger.info(
            "  NADO   %s | %s | qty=%.8f | notional=$%.2f | mark=%.2f | mode=%s | state=%s",
            position.symbol,
            position.side,
            position.size,
            position.notional_usd,
            position.mark_price,
            position.margin_mode,
            managed_label,
        )
        if managed_label == "ORPHAN":
            logger.warning(
                "         alerta: exposicao real sem setup_live_state correspondente; setup-live nao gerencia TP/SL desta posicao",
            )
        protection = nado_trigger_summary.get(product_id)
        if protection:
            sl_qty = sum(float(level.get("qty") or 0.0) for level in protection["sl"])
            tp_qty = sum(float(level.get("qty") or 0.0) for level in protection["tp"])
            logger.info(
                "         protecao Nado | SL=%d qty=%.8g [%s] | TP=%d qty=%.8g [%s]",
                len(protection["sl"]),
                sl_qty,
                _format_nado_trigger_levels(protection["sl"]),
                len(protection["tp"]),
                tp_qty,
                _format_nado_trigger_levels(protection["tp"]),
            )
            below_min = [level for level in protection["sl"] + protection["tp"] if level.get("below_min")]
            if below_min:
                logger.warning(
                    "         alerta Nado: %d trigger(s) abaixo do minimo nativo; podem falhar ao disparar",
                    len(below_min),
                )
    for position in kraken_positions:
        kraken_symbol = str(getattr(position, "symbol", "") or "").upper()
        managed_label = "managed" if kraken_symbol in managed_kraken_symbols else "ORPHAN"
        logger.info(
            "  KRAKEN %s | %s | qty=%.8f | notional=$%.2f | mark=%.2f | lev=%.2fx | state=%s",
            position.symbol,
            position.side,
            position.size,
            abs(position.size * position.mark_price),
            position.mark_price,
            position.leverage,
            managed_label,
        )
        if managed_label == "ORPHAN":
            logger.warning(
                "         alerta: exposicao real sem setup_live_state correspondente; setup-live nao gerencia TP/SL desta posicao",
            )

    logger.info("resumo live por ativo:")
    for base in sorted(summary):
        row = summary[base]
        gross = row["gross_notional"]
        net = row["net_notional"]
        drift_bps = abs(net) / gross * 10000 if gross else 0.0
        if gross <= 0:
            status = "flat"
        elif drift_bps <= eng.drift_bps:
            status = "hedged"
        else:
            status = "unmatched"
        logger.info(
            "  %s | nado=$%.2f | kraken=$%.2f | net=$%.2f | drift=%.2f bps | status=%s",
            base,
            row["nado_notional"],
            row["kraken_notional"],
            net,
            drift_bps,
            status,
        )
    return True


def _pick_live_hedge_target(row: dict[str, float], target_exchange: str) -> str | None:
    if target_exchange in {"nado", "kraken"}:
        return target_exchange

    nado_notional = row["nado_notional"]
    kraken_notional = row["kraken_notional"]
    if abs(nado_notional) < 1e-12 and abs(kraken_notional) < 1e-12:
        return None
    if abs(nado_notional) < 1e-12:
        return "nado"
    if abs(kraken_notional) < 1e-12:
        return "kraken"
    if abs(nado_notional) < abs(kraken_notional):
        return "nado"
    return "kraken"


def _infer_kraken_min_quantity(eng: DeltaNeutralEngine, symbol: str) -> float:
    market_getter = getattr(getattr(eng.kraken, "client", None), "market", None)
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


def _infer_nado_min_quantity(eng: DeltaNeutralEngine, product_id: int) -> float:
    get_increment = getattr(eng.nado, "_get_size_increment_x18", None)
    if callable(get_increment):
        try:
            increment = int(get_increment(product_id))
        except Exception:  # noqa: BLE001
            return 0.0
        if increment > 0:
            return increment / 1e18
    return 0.0


def _plan_live_hedges(
    eng: DeltaNeutralEngine,
    *,
    symbol: str = "all",
    target_exchange: str = "auto",
) -> list[LiveHedgeAction]:
    _, _, summary = _collect_live_status(eng)
    common_by_base = {
        _live_base_symbol(common_symbol): common_symbol
        for common_symbol in eng.common_symbols()
    }
    requested_symbols = _resolve_symbols(eng, symbol)
    allowed_bases = {_live_base_symbol(common_symbol) for common_symbol in requested_symbols}
    actions: list[LiveHedgeAction] = []

    for base in sorted(summary):
        if base not in allowed_bases:
            continue
        common_symbol = common_by_base.get(base)
        if not common_symbol:
            continue

        row = summary[base]
        net_qty = row["nado_qty"] + row["kraken_qty"]
        net_notional_usd = row["net_notional"]
        gross_notional = row["gross_notional"]
        drift_bps = abs(net_notional_usd) / gross_notional * 10000 if gross_notional else 0.0
        if abs(net_notional_usd) < 1e-9 or drift_bps <= eng.drift_bps:
            continue

        selected_target = _pick_live_hedge_target(row, target_exchange)
        if selected_target is None:
            continue

        is_buy = net_notional_usd < 0
        blocked_reason = ""
        nado_product_id = eng._nado_symbol_map.get(common_symbol)
        kraken_symbol = eng._kraken_symbol_map.get(common_symbol, "")
        target_min_qty = 0.0
        target_min_notional_usd = 0.0

        if selected_target == "kraken":
            if not kraken_symbol:
                continue
            mark_price = row["kraken_mark"] or eng.kraken.get_market_mid_price(kraken_symbol)
            raw_order_qty = abs(net_notional_usd) / mark_price if mark_price > 0 else 0.0
            order_qty = eng.kraken.round_quantity_to_increment(kraken_symbol, raw_order_qty)
            target_min_qty = _infer_kraken_min_quantity(eng, kraken_symbol)
            target_min_notional_usd = target_min_qty * mark_price
            conflicts = eng.kraken.get_market_order_conflicts(kraken_symbol, is_buy=is_buy)
            if conflicts:
                ids = ", ".join(conflict.order_id for conflict in conflicts)
                blocked_reason = f"Kraken bloqueado por ordens abertas ({ids})"
            if order_qty <= 0:
                blocked_reason = blocked_reason or (
                    f"nocional abaixo do minimo executavel na Kraken (~${target_min_notional_usd:.2f})"
                )
            source_exchange = "nado" if abs(row["nado_notional"]) >= abs(row["kraken_notional"]) else "kraken"
        else:
            if nado_product_id is None:
                continue
            mark_price = row["nado_mark"] or eng.nado.get_market_mid_price(nado_product_id)
            raw_order_qty = abs(net_notional_usd) / mark_price if mark_price > 0 else 0.0
            order_qty = eng.nado.round_quantity_to_increment(nado_product_id, raw_order_qty)
            target_min_qty = _infer_nado_min_quantity(eng, nado_product_id)
            target_min_notional_usd = target_min_qty * mark_price
            if order_qty <= 0:
                blocked_reason = (
                    f"nocional abaixo do minimo executavel na Nado (~${target_min_notional_usd:.2f})"
                )
            source_exchange = "kraken" if abs(row["kraken_notional"]) >= abs(row["nado_notional"]) else "nado"

        actions.append(
            LiveHedgeAction(
                symbol=common_symbol,
                base=base,
                source_exchange=source_exchange,
                target_exchange=selected_target,
                nado_qty=row["nado_qty"],
                kraken_qty=row["kraken_qty"],
                net_qty=net_qty,
                order_qty=order_qty,
                order_notional_usd=order_qty * mark_price,
                net_notional_usd=net_notional_usd,
                is_buy=is_buy,
                drift_bps=drift_bps,
                target_mark_price=mark_price,
                target_min_qty=target_min_qty,
                target_min_notional_usd=target_min_notional_usd,
                nado_product_id=nado_product_id,
                kraken_symbol=kraken_symbol,
                blocked_reason=blocked_reason,
            )
        )

    return actions


def _log_live_hedge_plan(actions: list[LiveHedgeAction], *, dry_run: bool) -> None:
    if not actions:
        logger.info("sem exposicoes live desenquadradas para hedgear")
        return

    logger.info("plano de live-hedge%s:", " (dry-run)" if dry_run else "")
    for action in actions:
        side = "BUY" if action.is_buy else "SELL"
        logger.info(
            "  %s | source=%s -> target=%s | net=$%.2f | %s qty=%.8f | hedge=$%.2f | min_exec=$%.2f | drift=%.2f bps%s",
            action.symbol,
            action.source_exchange,
            action.target_exchange,
            action.net_notional_usd,
            side,
            action.order_qty,
            action.order_notional_usd,
            action.target_min_notional_usd,
            action.drift_bps,
            f" | bloqueado={action.blocked_reason}" if action.blocked_reason else "",
        )


def _execute_live_hedges(
    eng: DeltaNeutralEngine,
    actions: list[LiveHedgeAction],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    executed = 0
    blocked = 0
    for action in actions:
        if action.blocked_reason:
            logger.warning("live-hedge bloqueado em %s: %s", action.symbol, action.blocked_reason)
            blocked += 1
            continue

        side = "BUY" if action.is_buy else "SELL"
        logger.info(
            "executando live-hedge %s | %s -> %s | %s qty=%.8f (~$%.2f)",
            action.symbol,
            action.source_exchange,
            action.target_exchange,
            side,
            action.order_qty,
            action.order_notional_usd,
        )
        if dry_run:
            continue

        try:
            if action.target_exchange == "kraken":
                eng.kraken.validate_entry_subaccount_rule(
                    require_subaccount=getattr(eng, "kraken_require_subaccount", False),
                    declared_is_subaccount=getattr(eng, "kraken_api_is_subaccount", False),
                )
                eng.kraken.place_market_order(
                    symbol=action.kraken_symbol,
                    quantity=action.order_qty,
                    is_buy=action.is_buy,
                )
                stop_price = eng.protective_stop_price(
                    action.target_mark_price,
                    "long" if action.is_buy else "short",
                )
                if stop_price > 0:
                    eng.kraken.place_stop_loss(
                        symbol=action.kraken_symbol,
                        quantity=action.order_qty,
                        trigger_price=stop_price,
                        is_long=action.is_buy,
                    )
            else:
                eng.nado.assert_trade_ready()
                eng.nado.place_market_order(
                    product_id=int(action.nado_product_id),
                    quantity=action.order_qty,
                    is_buy=action.is_buy,
                    slippage_bps=eng.slippage_bps,
                )
                stop_price = eng.protective_stop_price(
                    action.target_mark_price,
                    "long" if action.is_buy else "short",
                )
                if stop_price > 0:
                    trigger_slippage_pct = float(
                        getattr(eng, "protective_stop_trigger_slippage_pct", 0.01) or 0.01
                    )
                    eng.nado.place_stop_loss(
                        product_id=int(action.nado_product_id),
                        quantity=action.order_qty,
                        trigger_price=stop_price,
                        is_long=action.is_buy,
                        slippage_pct=trigger_slippage_pct,
                    )
            executed += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("falha no live-hedge %s: %s", action.symbol, exc)
            blocked += 1
    return executed, blocked


def load_state() -> PairState | None:
    source = next(
        (
            candidate
            for candidate in _state_file_candidates()
            if candidate.exists()
        ),
        None,
    )
    if source is None:
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    return PairState.from_dict(payload)


def save_state(state: PairState | None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if state is None:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        return
    STATE_FILE.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def _setup_state_lock_path() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return SETUP_LIVE_STATE_LOCK_FILE


def _setup_state_key(state: ManagedSetupState) -> tuple[str, str, str, str, str]:
    venue = str(state.effective_venue or state.pair_state.effective_venue or "").lower()
    entry = state.opened_bar_at or str(round(float(state.opened_at_ts or state.pair_state.opened_at or 0.0), 3))
    return (
        str(state.setup_key or "").lower(),
        str(state.symbol or "").upper(),
        venue,
        str(state.side or "").lower(),
        entry,
    )


def _read_setup_live_states_unlocked() -> list[ManagedSetupState]:
    source = next(
        (
            candidate
            for candidate in _setup_live_state_file_candidates()
            if candidate.exists()
        ),
        None,
    )
    if source is None:
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    return [ManagedSetupState.from_dict(item) for item in payload]


def load_setup_live_states() -> list[ManagedSetupState]:
    """Le o state file sem tomar lock.

    A escrita e atomica (`os.replace`), entao um leitor nunca ve arquivo pela
    metade: ou o conteudo antigo, ou o novo. O `flock` compartilhado que existia
    aqui nao comprava nada -- e o lock atual e exclusivo, entao usa-lo faria a
    leitura serializar contra escritores e contra outros leitores, travando o
    loop do `setup-live` a cada iteracao.
    """
    return _read_setup_live_states_unlocked()


def _atomic_write_setup_live_states_unlocked(states: list[ManagedSetupState]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not states:
        if SETUP_LIVE_STATE_FILE.exists():
            SETUP_LIVE_STATE_FILE.unlink()
        return
    payload = [state.to_dict() for state in states]
    tmp = SETUP_LIVE_STATE_FILE.with_name(f".{SETUP_LIVE_STATE_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETUP_LIVE_STATE_FILE)


def _dump_setup_live_states_for_recovery(states: list[ManagedSetupState]) -> Path | None:
    """Grava o state num arquivo lateral quando o lock nao pode ser adquirido.

    Nao substitui o state file (nao ha lock para isso com seguranca); serve
    para que um estado produzido logo apos preenchimento de ordem nao se perca.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = STATE_DIR / f"setup_live_state.recovery.{os.getpid()}.{int(time.time())}.json"
        target.write_text(
            json.dumps([state.to_dict() for state in states], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.error(
            "lock do setup-live state indisponivel; estado salvo para recuperacao manual em %s",
            target,
        )
        return target
    except Exception:
        logger.exception("falha ao gravar arquivo de recuperacao do setup-live state")
        return None


def save_setup_live_states(
    states: list[ManagedSetupState],
    *,
    base_states: list[ManagedSetupState] | None = None,
    merge_existing: bool = True,
) -> None:
    """Salva setup-live state com lock, escrita atomica e merge anti-race.

    `base_states` deve ser o snapshot carregado pelo mesmo loop antes de processar.
    Chaves removidas entre base->states sao tombstones locais e nao sao ressuscitadas
    pelo merge. Estados novos de outro processo/venue sao preservados.
    """
    lock_path = _setup_state_lock_path()
    try:
        lock = FileLock(lock_path, timeout=SETUP_STATE_LOCK_TIMEOUT)
        lock.__enter__()
    except LockHeld:
        # O `flock` anterior bloqueava ate adquirir, entao a escrita nunca
        # falhava. Agora pode -- e essa escrita acontece logo depois de ordens
        # preenchidas. Perder o registro em silencio deixaria posicao aberta
        # sem rastreio, entao o estado vai para um arquivo de recuperacao antes
        # de propagar o erro.
        _dump_setup_live_states_for_recovery(states)
        raise
    try:
        final_states = list(states)
        if merge_existing and base_states is not None:
            existing = _read_setup_live_states_unlocked()
            incoming_by_key = {_setup_state_key(state): state for state in final_states}
            base_keys = {_setup_state_key(state) for state in base_states}
            incoming_keys = set(incoming_by_key)
            removed_keys = base_keys - incoming_keys
            merged: list[ManagedSetupState] = []
            seen: set[tuple[str, str, str, str, str]] = set()
            for state in existing:
                key = _setup_state_key(state)
                if key in removed_keys:
                    continue
                if key in incoming_by_key:
                    merged.append(incoming_by_key[key])
                else:
                    merged.append(state)
                seen.add(key)
            for key, state in incoming_by_key.items():
                if key not in seen:
                    merged.append(state)
            final_states = merged
        _atomic_write_setup_live_states_unlocked(final_states)
    finally:
        lock.__exit__(None, None, None)


def _setup_timeframe_limit(timeframe: str) -> int:
    mapping = {
        "15m": 220,
        "1h": 260,
        "4h": 280,
    }
    return mapping.get(timeframe, 260)


def _fetch_setup_market_dataset(eng: DeltaNeutralEngine, symbol: str, timeframe: str) -> pd.DataFrame:
    kraken_symbol = eng._kraken_symbol_map[symbol]
    raw = eng.kraken.client.fetch_ohlcv(kraken_symbol, timeframe=timeframe, limit=_setup_timeframe_limit(timeframe))
    if not raw:
        raise RuntimeError(f"sem candles para {symbol} em {timeframe}")
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise RuntimeError(f"dataset vazio para {symbol} em {timeframe}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = prepare_market_dataset(df)
    df.attrs["symbol"] = symbol
    df.attrs["kraken_symbol"] = kraken_symbol
    df.attrs["timeframe"] = timeframe
    return df


def _setup_reference_price(eng: DeltaNeutralEngine, state: ManagedSetupState) -> float:
    if state.effective_venue == "nado":
        return eng.nado.get_market_mid_price(state.pair_state.nado_product_id)
    try:
        return eng.kraken.get_market_mid_price(state.pair_state.kraken_symbol)
    except Exception:  # noqa: BLE001
        return eng.nado.get_market_mid_price(state.pair_state.nado_product_id)


def _build_setup_runtime_context(
    eng: DeltaNeutralEngine,
    *,
    symbol: str,
    setup_key: str,
) -> dict:
    normalized = setup_key.strip().lower()
    kraken_symbol = eng._kraken_symbol_map[symbol]
    nado_product_id = eng._nado_symbol_map.get(symbol, 0)
    kraken_mid = eng.kraken.get_market_mid_price(kraken_symbol)
    nado_mid = 0.0
    if nado_product_id:
        try:
            nado_mid = eng.nado.get_market_mid_price(nado_product_id)
        except Exception:  # noqa: BLE001
            nado_mid = 0.0
    spread_bps = ((kraken_mid - nado_mid) / nado_mid * 10000) if nado_mid else 0.0
    context = {
        "symbol": symbol,
        "kraken_symbol": kraken_symbol,
        "nado_product_id": nado_product_id,
        "kraken_mid": kraken_mid,
        "nado_mid": nado_mid,
        "spread_bps": spread_bps,
        "now_ts": time.time(),
    }
    if normalized == "funding-arb":
        funding_config = get_funding_arb_config()
        funding_rate = eng.kraken.get_funding_rate(kraken_symbol)
        context.update(
            {
                "funding_rate": float(funding_rate or 0.0),
                "funding_threshold": funding_config.min_rate,
                "neutral_exit_rate": funding_config.exit_rate,
                "max_hold_hours": funding_config.max_hold_hours,
                "max_spread_bps": funding_config.max_spread_bps,
            }
        )
    return context


def _rebase_reference_price(level_price: float, *, from_entry: float, to_entry: float) -> float:
    if from_entry <= 0 or to_entry <= 0 or level_price <= 0:
        return 0.0
    move_pct = (level_price - from_entry) / from_entry
    return float(to_entry * (1 + move_pct))


def _round_target_split_qty(
    eng: DeltaNeutralEngine,
    state: PairState,
    desired_qty: float,
    *,
    effective_venue: str,
) -> float:
    if desired_qty <= 0:
        return 0.0
    if effective_venue == "nado":
        return float(eng.nado.round_quantity_to_increment(state.nado_product_id, desired_qty))
    if effective_venue == "kraken":
        return float(eng.kraken.round_quantity_to_increment(state.kraken_symbol, desired_qty))
    nado_qty = eng.nado.round_quantity_to_increment(state.nado_product_id, desired_qty)
    kraken_qty = eng.kraken.round_quantity_to_increment(state.kraken_symbol, desired_qty)
    common_qty = min(float(nado_qty), float(kraken_qty))
    if common_qty <= 0:
        return 0.0
    nado_qty = eng.nado.round_quantity_to_increment(state.nado_product_id, common_qty)
    kraken_qty = eng.kraken.round_quantity_to_increment(state.kraken_symbol, common_qty)
    return min(float(nado_qty), float(kraken_qty))


def _build_target_levels(
    eng: DeltaNeutralEngine,
    pair_state: PairState,
    *,
    reference_entry_price: float,
    signal_targets: list[float],
    target_weights: list[float],
    effective_venue: str = "hedged",
) -> list[dict]:
    if not signal_targets or reference_entry_price <= 0:
        return []

    if effective_venue == "nado":
        total_qty = float(pair_state.nado_qty)
    elif effective_venue == "kraken":
        total_qty = float(pair_state.kraken_qty)
    else:
        total_qty = min(float(pair_state.nado_qty), float(pair_state.kraken_qty))
    if total_qty <= 0:
        return []

    if effective_venue == "nado":
        target_entry_price = float(pair_state.nado_entry)
    elif effective_venue == "kraken":
        target_entry_price = float(pair_state.kraken_entry)
    else:
        target_entry_price = float(pair_state.nado_entry or pair_state.kraken_entry)
    if target_entry_price <= 0:
        target_entry_price = reference_entry_price

    weights = list(target_weights) if target_weights else [1 / len(signal_targets)] * len(signal_targets)
    if len(weights) != len(signal_targets):
        weights = [1 / len(signal_targets)] * len(signal_targets)

    planned_qtys: list[float] = []
    remaining_qty = total_qty
    for idx, weight in enumerate(weights):
        if idx == len(weights) - 1:
            # O último alvo recebe o resíduo da posição. O pequeno epsilon evita
            # perder um incremento por ruído binário, ex.: 0.25 - 0.08 - 0.08.
            qty = _round_target_split_qty(eng, pair_state, remaining_qty + 1e-12, effective_venue=effective_venue)
        else:
            desired_qty = total_qty * float(weight)
            qty = _round_target_split_qty(
                eng,
                pair_state,
                min(desired_qty, remaining_qty),
                effective_venue=effective_venue,
            )
        if qty > 0:
            planned_qtys.append(qty)
            remaining_qty = max(remaining_qty - qty, 0.0)

    if not planned_qtys:
        final_qty = _round_target_split_qty(eng, pair_state, total_qty, effective_venue=effective_venue)
        if final_qty <= 0:
            return []
        planned_qtys = [final_qty]

    chosen_targets = signal_targets[-len(planned_qtys):]
    levels: list[dict] = []
    for idx, (target_price, qty) in enumerate(zip(chosen_targets, planned_qtys), start=1):
        levels.append(
            {
                "label": f"TP{idx}",
                "price": _rebase_reference_price(
                    float(target_price),
                    from_entry=reference_entry_price,
                    to_entry=target_entry_price,
                ),
                "nado_qty": qty if effective_venue in {"hedged", "nado"} else 0.0,
                "kraken_qty": qty if effective_venue in {"hedged", "kraken"} else 0.0,
            }
        )
    return levels


def _target_levels_cover_total_qty(eng: DeltaNeutralEngine, state: ManagedSetupState, levels: list[dict]) -> bool:
    if not levels:
        return False
    effective_venue = state.effective_venue
    pair_state = state.pair_state
    if effective_venue == "nado":
        expected_qty = _round_target_split_qty(
            eng,
            pair_state,
            float(pair_state.nado_qty) + 1e-12,
            effective_venue=effective_venue,
        )
        covered_qty = sum(float(level.get("nado_qty") or 0.0) for level in levels)
    elif effective_venue == "kraken":
        expected_qty = _round_target_split_qty(
            eng,
            pair_state,
            float(pair_state.kraken_qty) + 1e-12,
            effective_venue=effective_venue,
        )
        covered_qty = sum(float(level.get("kraken_qty") or 0.0) for level in levels)
    else:
        expected_qty = _round_target_split_qty(
            eng,
            pair_state,
            min(float(pair_state.nado_qty), float(pair_state.kraken_qty)) + 1e-12,
            effective_venue=effective_venue,
        )
        covered_qty = min(
            sum(float(level.get("nado_qty") or 0.0) for level in levels),
            sum(float(level.get("kraken_qty") or 0.0) for level in levels),
        )
    if expected_qty <= 0:
        return False
    return covered_qty + 1e-9 >= expected_qty


def _fallback_three_target_ladder(entry_price: float, final_target: float) -> tuple[list[float], list[float]]:
    if entry_price <= 0 or final_target <= 0 or abs(final_target - entry_price) < 1e-9:
        return [], []
    step = (final_target - entry_price) / 3.0
    return [float(entry_price + step), float(entry_price + 2 * step), float(final_target)], [1 / 3, 1 / 3, 1 / 3]


def _ensure_state_target_levels(eng: DeltaNeutralEngine, state: ManagedSetupState) -> list[dict]:
    raw_levels = state.metadata.get("target_levels")
    levels = raw_levels if isinstance(raw_levels, list) else []
    valid_levels = [
        level
        for level in levels
        if isinstance(level, dict)
        and float(level.get("price") or 0.0) > 0
        and (float(level.get("nado_qty") or 0.0) > 0 or float(level.get("kraken_qty") or 0.0) > 0)
    ]
    if valid_levels and (state.targets_hit > 0 or _target_levels_cover_total_qty(eng, state, valid_levels)):
        return valid_levels
    targets, weights = _fallback_three_target_ladder(state.reference_entry_price, state.take_profit)
    rebuilt = _build_target_levels(
        eng,
        state.pair_state,
        reference_entry_price=state.reference_entry_price,
        signal_targets=targets,
        target_weights=weights,
        effective_venue=state.effective_venue,
    )
    if rebuilt:
        state.metadata["target_levels"] = rebuilt
    return rebuilt


def _attach_solo_protective_orders(
    eng: DeltaNeutralEngine,
    state: ManagedSetupState,
    target_levels: list[dict] | None = None,
) -> bool:
    if state.effective_venue not in {"nado", "kraken"}:
        return True
    levels = target_levels if target_levels is not None else _ensure_state_target_levels(eng, state)
    is_long = state.side == "long"
    ok = True
    if state.effective_venue == "nado":
        qty_total = abs(float(state.pair_state.nado_qty or eng.nado.get_perp_position_size(state.pair_state.nado_product_id)))
        qty_total = float(eng.nado.round_quantity_to_increment(state.pair_state.nado_product_id, qty_total))
        min_notional_getter = getattr(eng.nado, "get_min_order_notional_usd", None)
        min_notional = float(
            min_notional_getter(state.pair_state.nado_product_id) if callable(min_notional_getter) else 0.0
        )
        nado_tp_below_min = False
        if min_notional > 0:
            stop_notional = abs(qty_total * state.stop_price) if state.stop_price > 0 else 0.0
            if state.stop_price > 0 and stop_notional + 1e-9 < min_notional:
                logger.warning(
                    "setup-live protecao | SL Nado abaixo do minimo em %s ($%.2f < $%.2f); fallback gerenciado pelo loop",
                    state.symbol,
                    stop_notional,
                    min_notional,
                )
                state.metadata["nado_native_stop_skipped_reason"] = "below_min_notional"
                ok = False
            for level in levels:
                price = float(level.get("price") or 0.0)
                qty = float(level.get("nado_qty") or 0.0)
                if price > 0 and qty > 0 and abs(price * qty) + 1e-9 < min_notional:
                    logger.warning(
                        "setup-live protecao | %s Nado abaixo do minimo em %s ($%.2f < $%.2f); TP ficara gerenciado pelo loop",
                        level.get("label") or "TP",
                        state.symbol,
                        abs(price * qty),
                        min_notional,
                    )
                    level["native_skipped_reason"] = "below_min_notional"
                    nado_tp_below_min = True
                    ok = False
        if nado_tp_below_min and levels and state.targets_hit <= 0:
            policy = os.environ.get("SETUP_LIVE_NADO_MANAGED_TP_POLICY", "first_target_full").strip().lower()
            if policy in {"first_target_full", "full_at_tp1", "tp1_full"}:
                first_level = dict(levels[0])
                first_level["label"] = str(first_level.get("label") or "TP1") + "-MANAGED-FULL"
                first_level["nado_qty"] = qty_total
                first_level["native_skipped_reason"] = "below_min_notional_managed_full"
                state.metadata["target_levels"] = [first_level]
                levels = state.metadata["target_levels"]
                state.metadata["nado_managed_tp_policy"] = "first_target_full"
                state.metadata["nado_managed_tp_reason"] = "native_tp_below_min_notional"
                logger.warning(
                    "setup-live protecao | %s Nado com TP nativo abaixo do minimo; fallback gerenciado ajustado para fechar 100%% no primeiro alvo (qty=%.8g)",
                    state.symbol,
                    qty_total,
                )
        if state.stop_price > 0 and qty_total > 0 and not state.metadata.get("nado_native_stop_skipped_reason"):
            try:
                order = eng.nado.place_stop_loss(
                    state.pair_state.nado_product_id,
                    qty_total,
                    state.stop_price,
                    is_long=is_long,
                    slippage_pct=float(getattr(eng, "protective_stop_trigger_slippage_pct", 0.01) or 0.01),
                )
                if order is None:
                    ok = False
                else:
                    _record_native_order_ref(
                        state,
                        eng,
                        "nado",
                        "sl",
                        order,
                        price=state.stop_price,
                        quantity=qty_total,
                        label="SL",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("setup-live protecao | falha ao anexar SL Nado em %s: %s", state.symbol, exc)
                ok = False
        for level in levels:
            price = float(level.get("price") or 0.0)
            if level.get("native_skipped_reason"):
                continue
            qty = float(level.get("nado_qty") or 0.0)
            qty = float(eng.nado.round_quantity_to_increment(state.pair_state.nado_product_id, qty))
            if price <= 0 or qty <= 0:
                continue
            try:
                order = eng.nado.place_take_profit(
                    state.pair_state.nado_product_id,
                    qty,
                    price,
                    is_long=is_long,
                    slippage_pct=float(getattr(eng, "protective_stop_trigger_slippage_pct", 0.01) or 0.01),
                )
                if order is None:
                    ok = False
                else:
                    level["native_order_ref"] = _record_native_order_ref(
                        state,
                        eng,
                        "nado",
                        "tp",
                        order,
                        price=price,
                        quantity=qty,
                        label=str(level.get("label") or "TP"),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("setup-live protecao | falha ao anexar TP Nado em %s: %s", state.symbol, exc)
                ok = False
        if not levels and state.take_profit > 0 and qty_total > 0:
            try:
                order = eng.nado.place_take_profit(state.pair_state.nado_product_id, qty_total, state.take_profit, is_long=is_long)
                if order is None:
                    ok = False
                else:
                    _record_native_order_ref(
                        state,
                        eng,
                        "nado",
                        "tp",
                        order,
                        price=state.take_profit,
                        quantity=qty_total,
                        label="TP-final",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("setup-live protecao | falha ao anexar TP final Nado em %s: %s", state.symbol, exc)
                ok = False
        return ok

    qty_total = abs(float(state.pair_state.kraken_qty))
    qty_total = float(eng.kraken.round_quantity_to_increment(state.pair_state.kraken_symbol, qty_total))
    if state.stop_price > 0 and qty_total > 0:
        try:
            order = eng.kraken.place_stop_loss(state.pair_state.kraken_symbol, qty_total, state.stop_price, is_long=is_long)
            if order is None:
                ok = False
            else:
                _record_native_order_ref(
                    state,
                    eng,
                    "kraken",
                    "sl",
                    order,
                    price=state.stop_price,
                    quantity=qty_total,
                    label="SL",
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("setup-live protecao | falha ao anexar SL Kraken em %s: %s", state.symbol, exc)
            ok = False
    for level in levels:
        price = float(level.get("price") or 0.0)
        qty = float(level.get("kraken_qty") or 0.0)
        qty = float(eng.kraken.round_quantity_to_increment(state.pair_state.kraken_symbol, qty))
        if price <= 0 or qty <= 0:
            continue
        try:
            order = eng.kraken.place_take_profit(state.pair_state.kraken_symbol, qty, price, is_long=is_long)
            if order is None:
                ok = False
            else:
                level["native_order_ref"] = _record_native_order_ref(
                    state,
                    eng,
                    "kraken",
                    "tp",
                    order,
                    price=price,
                    quantity=qty,
                    label=str(level.get("label") or "TP"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("setup-live protecao | falha ao anexar TP Kraken em %s: %s", state.symbol, exc)
            ok = False
    if not levels and state.take_profit > 0 and qty_total > 0:
        try:
            order = eng.kraken.place_take_profit(state.pair_state.kraken_symbol, qty_total, state.take_profit, is_long=is_long)
            if order is None:
                ok = False
            else:
                _record_native_order_ref(
                    state,
                    eng,
                    "kraken",
                    "tp",
                    order,
                    price=state.take_profit,
                    quantity=qty_total,
                    label="TP-final",
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("setup-live protecao | falha ao anexar TP final Kraken em %s: %s", state.symbol, exc)
            ok = False
    return ok


def _close_solo_setup(eng: DeltaNeutralEngine, state: ManagedSetupState, *, quantity: float | None = None) -> bool:
    venue = state.effective_venue
    if venue == "nado":
        close_qty = abs(float(quantity if quantity is not None else eng.nado.get_perp_position_size(state.pair_state.nado_product_id)))
        close_qty = float(eng.nado.round_quantity_to_increment(state.pair_state.nado_product_id, close_qty))
        if close_qty <= 0:
            logger.warning("setup-live close solo sem qty Nado em %s", state.symbol)
            return False
        eng.nado.place_market_order(
            product_id=state.pair_state.nado_product_id,
            quantity=close_qty,
            is_buy=state.side == "short",
            slippage_bps=eng.slippage_bps,
            reduce_only=True,
            margin_mode=state.margin_mode or MARGIN_MODE_CROSS,
            leverage=state.leverage or None,
        )
        return True
    if venue == "kraken":
        if quantity is None:
            eng.kraken.close_position(state.pair_state.kraken_symbol)
            return True
        close_qty = float(eng.kraken.round_quantity_to_increment(state.pair_state.kraken_symbol, abs(float(quantity))))
        if close_qty <= 0:
            logger.warning("setup-live close solo sem qty Kraken em %s", state.symbol)
            return False
        eng.kraken.place_market_order(
            state.pair_state.kraken_symbol,
            close_qty,
            is_buy=state.side == "short",
            reduce_only=True,
        )
        return True
    return False


def _partial_close_solo_setup(
    eng: DeltaNeutralEngine,
    state: ManagedSetupState,
    exit_signal: object,
    *,
    reconciled_closed_qty: float = 0.0,
) -> bool:
    if state.effective_venue == "nado":
        desired_qty = float(getattr(exit_signal, "metadata", {}).get("nado_qty") or 0.0)
        current_qty = abs(float(state.pair_state.nado_qty or 0.0))
        qty = min(max(desired_qty - max(float(reconciled_closed_qty), 0.0), 0.0), current_qty)
        qty = float(eng.nado.round_quantity_to_increment(state.pair_state.nado_product_id, qty))
    else:
        desired_qty = float(getattr(exit_signal, "metadata", {}).get("kraken_qty") or 0.0)
        current_qty = abs(float(state.pair_state.kraken_qty or 0.0))
        qty = min(max(desired_qty - max(float(reconciled_closed_qty), 0.0), 0.0), current_qty)
        qty = float(eng.kraken.round_quantity_to_increment(state.pair_state.kraken_symbol, qty))
    if qty <= 0 and reconciled_closed_qty > 0:
        state.metadata["_last_partial_close_qty"] = 0.0
        state.metadata["_last_partial_satisfied_by_native_fill"] = True
        logger.info("setup-live parcial solo ja satisfeita por fill nativo em %s", state.symbol)
        return True
    if qty <= 0:
        logger.warning("setup-live parcial solo sem qty executavel em %s", state.symbol)
        return False
    state.metadata["_last_partial_close_qty"] = qty
    state.metadata.pop("_last_partial_satisfied_by_native_fill", None)
    return _close_solo_setup(eng, state, quantity=qty)


def _apply_solo_partial_close_to_state(state: ManagedSetupState, exit_signal: object) -> None:
    """Atualiza o state gerenciado depois de uma saída parcial solo confirmada."""
    metadata = getattr(exit_signal, "metadata", {}) or {}
    state.metadata.pop("_last_partial_satisfied_by_native_fill", None)
    actual_closed_qty = state.metadata.pop("_last_partial_close_qty", None)
    if state.effective_venue == "nado":
        closed_qty = abs(float(actual_closed_qty if actual_closed_qty is not None else metadata.get("nado_qty") or 0.0))
        current_qty = abs(float(state.pair_state.nado_qty or 0.0))
        remaining_qty = max(current_qty - closed_qty, 0.0)
        state.pair_state.nado_qty = remaining_qty
        entry = float(state.pair_state.nado_entry or 0.0)
    else:
        closed_qty = abs(float(actual_closed_qty if actual_closed_qty is not None else metadata.get("kraken_qty") or 0.0))
        current_qty = abs(float(state.pair_state.kraken_qty or 0.0))
        remaining_qty = max(current_qty - closed_qty, 0.0)
        state.pair_state.kraken_qty = remaining_qty
        entry = float(state.pair_state.kraken_entry or 0.0)
    if entry > 0:
        state.pair_state.effective_notional_usd = remaining_qty * entry
    logger.info(
        "setup-live parcial aplicado | %s %s | qty_fechada=%.8f | qty_restante=%.8f | notional_restante=$%.2f",
        state.setup_key,
        state.symbol,
        closed_qty,
        remaining_qty,
        float(state.pair_state.effective_notional_usd or 0.0),
    )


def _log_setup_live_status(states: list[ManagedSetupState]) -> None:
    if not states:
        logger.info("(sem setups live gerenciados)")
        return
    logger.info("setups live gerenciados:")
    for state in states:
        extra = ""
        if state.setup_key == "funding-arb" and state.metadata:
            extra = (
                f" | entry_funding={float(state.metadata.get('entry_funding_rate', 0.0)) * 100:.4f}%/8h"
                f" | max_hold={int(state.metadata.get('max_hold_hours', 0))}h"
            )
        logger.info(
            "  %s | %s | %s | mode=%s/%s | margin=%s | lev=%.2fx | liq=%s | buffer=%.1f%% | timeframe=%s | profile=%s | stop=%.4f | target=%.4f | %s%s",
            state.setup_key,
            state.symbol,
            state.side,
            state.execution_mode,
            state.effective_venue,
            state.margin_mode or "-",
            state.leverage,
            _fmt_liq(state.liquidation_price),
            state.liquidation_buffer_pct,
            state.timeframe,
            state.hybrid_profile or "-",
            state.stop_price,
            state.take_profit,
            _state_potential_pnl_line(state),
            extra,
        )


@dataclass
class VenuePairSpec:
    venue_type: str
    venue_id: str


@dataclass
class VenuePairLeg:
    spec: VenuePairSpec
    trader: object
    label: str


@dataclass
class VenuePairOrderLeg:
    leg: VenuePairLeg
    side: str
    native_symbol: object
    entry_price: float
    quantity: float
    margin_mode: str
    leverage: float


def _venue_pair_state_path() -> Path:
    return VENUE_PAIR_STATE_FILE


def _venue_prefix(venue_id: str) -> str:
    out = []
    for char in str(venue_id or ""):
        out.append(char.upper() if char.isalnum() else "_")
    cleaned = "_".join(part for part in "".join(out).split("_") if part)
    return cleaned or "VENUE"


def _parse_venue_pair_spec(raw: str) -> VenuePairSpec:
    value = (raw or "").strip().lower()
    if not value:
        raise ValueError("venue vazia; use cex:<id> ou dex:<id>")
    if ":" in value:
        venue_type, venue_id = value.split(":", 1)
    else:
        venue_id = value
        venue_type = "dex" if venue_id in {"nado", "nado-dex", "nado_dex", "hyperliquid", "dydx", "uniswap"} else "cex"
    venue_type = venue_type.strip().lower()
    venue_id = venue_id.strip().lower()
    aliases = {"exchange": "cex", "centralized": "cex", "dex_adapter": "dex"}
    venue_type = aliases.get(venue_type, venue_type)
    if venue_type not in {"cex", "dex"}:
        raise ValueError(f"tipo de venue invalido: {venue_type}; use cex:<id> ou dex:<id>")
    if not venue_id:
        raise ValueError("venue_id vazio; use cex:<id> ou dex:<id>")
    return VenuePairSpec(venue_type=venue_type, venue_id=venue_id)


def _pair_env(prefix: str, generic: str, *, prefer_generic: bool = False) -> str | None:
    specific = f"{prefix}_{generic}"
    return _first_env(generic, specific) if prefer_generic else _first_env(specific, generic)


def _venue_specific_env(prefix: str, suffix: str, generic: str) -> str | None:
    return _first_env(f"{prefix}_{suffix}", generic)


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


def _load_pair_cex_market_type(cex_id: str) -> str:
    prefix = _venue_prefix(cex_id)
    value = _first_env(f"{prefix}_MARKET_TYPE", "CEX_MARKET_TYPE", "CEX_DEFAULT_TYPE")
    return _normalize_cex_market_type(value, cex_id)


def _load_pair_cex_sandbox(cex_id: str) -> bool:
    # Mesma pergunta, mesmo veredito: este helper e o `_load_cex_sandbox`
    # tinham precedencias invertidas entre si.
    return resolve_sandbox("cex", cex_id)


def _pair_cex_credentials(cex_id: str) -> dict[str, str]:
    prefix = _venue_prefix(cex_id)
    if _is_builtin_kraken_cex(cex_id):
        return {
            "api_key": _first_env("KRAKEN_API_KEY", "KRAKEN_API_KEY_", "CEX_API_KEY") or "",
            "api_secret": _first_env("KRAKEN_API_SECRET", "CEX_API_SECRET") or "",
            "api_password": _first_env("KRAKEN_API_PASSWORD", "CEX_API_PASSWORD") or "",
        }
    return {
        "api_key": _venue_specific_env(prefix, "API_KEY", "CEX_API_KEY") or "",
        "api_secret": _venue_specific_env(prefix, "API_SECRET", "CEX_API_SECRET") or "",
        "api_password": _venue_specific_env(prefix, "API_PASSWORD", "CEX_API_PASSWORD") or "",
    }


def _build_cex_leg_for_pair(cex_id: str) -> VenuePairLeg:
    creds = _pair_cex_credentials(cex_id)
    if not creds["api_key"] or not creds["api_secret"]:
        prefix = _venue_prefix(cex_id)
        raise SystemExit(
            f"Configure credenciais da CEX {cex_id}: {prefix}_API_KEY/{prefix}_API_SECRET "
            "ou CEX_API_KEY/CEX_API_SECRET no env/secret manager"
        )
    if _is_builtin_kraken_cex(cex_id):
        kraken_venue = _load_pair_cex_market_type(cex_id)
        if cex_id == "kraken-spot":
            kraken_venue = "spot"
        if kraken_venue == "swap":
            kraken_venue = "futures"
        trader = KrakenTrader(
            creds["api_key"],
            creds["api_secret"],
            venue=kraken_venue,
            sandbox=_load_pair_cex_sandbox(cex_id),
            account=(_first_env("KRAKEN_ACCOUNT") or "flex").lower(),
            account_symbol=_first_env("KRAKEN_ACCOUNT_SYMBOL"),
            require_subaccount=False,
            declared_is_subaccount=_load_bool_env("KRAKEN_API_IS_SUBACCOUNT", False),
        )
    else:
        prefix = _venue_prefix(cex_id)
        trader = GenericCcxtTrader.from_options_json(
            cex_id,
            creds["api_key"],
            creds["api_secret"],
            api_password=creds["api_password"],
            market_type=_load_pair_cex_market_type(cex_id),
            sandbox=_load_pair_cex_sandbox(cex_id),
            options_json=_first_env(f"{prefix}_OPTIONS_JSON", "CEX_OPTIONS_JSON") or "",
        )
    return VenuePairLeg(spec=VenuePairSpec("cex", cex_id), trader=trader, label=f"cex:{cex_id}")


def _load_pair_dex_config(dex_id: str) -> dict:
    prefix = _venue_prefix(dex_id)
    raw = _first_env(f"{prefix}_CONFIG_JSON", "DEX_CONFIG_JSON")
    payload = {"dex_id": dex_id}
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{prefix}_CONFIG_JSON/DEX_CONFIG_JSON precisa ser objeto JSON")
        payload.update(parsed)
    network = _first_env(f"{prefix}_NETWORK", "DEX_NETWORK")
    if network:
        payload.setdefault("network", network)
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def _build_dex_leg_for_pair(dex_id: str) -> VenuePairLeg:
    if _is_builtin_nado_dex(dex_id):
        nado_key = _load_nado_owner_private_key()
        if not nado_key:
            raise SystemExit("Configure NADO_OWNER_PRIVATE_KEY no env/secret manager para usar dex:nado")
        nado_network = (_first_env("NADO_NETWORK", "NETWORK") or "testnet").lower()
        nado_linked_signer = _first_env("NADO_LINKED_SIGNER_PRIVATE_KEY")
        nado_kwargs = {
            "subaccount_name": _first_env("NADO_SUBACCOUNT_NAME") or "default_1",
            "linked_signer_private_key": nado_linked_signer,
            "require_linked_signer": _load_bool_env("NADO_REQUIRE_LINKED_SIGNER", True),
        }
        nado_trader_cls = load_nado_trader_class()
        if "allow_owner_fallback" in inspect.signature(nado_trader_cls).parameters:
            nado_kwargs["allow_owner_fallback"] = bool(not nado_linked_signer)
        trader = nado_trader_cls(nado_key, nado_network, **nado_kwargs)
    elif _is_builtin_hyperliquid_dex(dex_id):
        trader = _build_hyperliquid_trader(dex_id, require_credentials=True)
    else:
        prefix = _venue_prefix(dex_id)
        adapter_spec = _first_env(f"{prefix}_ADAPTER_MODULE", f"{prefix}_ADAPTER", "DEX_ADAPTER_MODULE", "DEX_ADAPTER")
        if not adapter_spec:
            raise SystemExit(
                f"DEX {dex_id} exige {prefix}_ADAPTER_MODULE=pacote.modulo:Classe "
                "ou DEX_ADAPTER_MODULE no env/config"
            )
        trader = load_custom_dex_adapter(adapter_spec, _load_pair_dex_config(dex_id))
    return VenuePairLeg(spec=VenuePairSpec("dex", dex_id), trader=trader, label=f"dex:{dex_id}")


def _build_venue_pair_leg(spec: VenuePairSpec) -> VenuePairLeg:
    if spec.venue_type == "cex":
        return _build_cex_leg_for_pair(spec.venue_id)
    return _build_dex_leg_for_pair(spec.venue_id)


def _venue_pair_symbol_ref(leg: VenuePairLeg, symbol: str) -> object:
    symbol_map = leg.trader.get_symbol_to_product_map()
    if symbol in symbol_map:
        return symbol_map[symbol]
    normalized = symbol.upper()
    if normalized in symbol_map:
        return symbol_map[normalized]
    available = ", ".join(list(symbol_map.keys())[:12])
    raise SystemExit(f"{leg.label} nao lista {symbol}; primeiros simbolos: {available or '-'}")


def _venue_pair_mid_price(leg: VenuePairLeg, native_symbol: object) -> float:
    return float(leg.trader.get_market_mid_price(native_symbol))


def _venue_pair_existing_size(leg: VenuePairLeg, native_symbol: object) -> float:
    if leg.spec.venue_type == "dex":
        return float(leg.trader.get_perp_position_size(native_symbol))
    return float(leg.trader.get_position(native_symbol).size)


def _venue_pair_round_qty(leg: VenuePairLeg, native_symbol: object, quantity: float) -> float:
    return float(leg.trader.round_quantity_to_increment(native_symbol, quantity))


def _venue_pair_place_order(order_leg: VenuePairOrderLeg, *, reduce_only: bool = False) -> None:
    is_buy = order_leg.side == "long"
    if reduce_only:
        is_buy = not is_buy
    if order_leg.leg.spec.venue_type == "dex":
        kwargs = {
            "product_id": order_leg.native_symbol,
            "quantity": order_leg.quantity,
            "is_buy": is_buy,
            "slippage_bps": int(os.environ.get("SLIPPAGE_BPS", "100")),
            "margin_mode": order_leg.margin_mode,
            "leverage": order_leg.leverage or None,
        }
        if reduce_only:
            kwargs["reduce_only"] = True
        order_leg.leg.trader.place_market_order(**kwargs)
        return
    if not reduce_only and callable(getattr(order_leg.leg.trader, "configure_futures_risk_context", None)):
        order_leg.leg.trader.configure_futures_risk_context(
            order_leg.native_symbol,
            leverage=order_leg.leverage or None,
            margin_mode=order_leg.margin_mode or None,
        )
    order_leg.leg.trader.place_market_order(
        order_leg.native_symbol,
        order_leg.quantity,
        is_buy=is_buy,
        reduce_only=reduce_only,
        margin_mode=order_leg.margin_mode or None,
        leverage=order_leg.leverage or None,
    )


def _build_venue_pair_order_leg(
    leg: VenuePairLeg,
    *,
    symbol: str,
    side: str,
    notional_usd: float,
    margin_mode: str,
    leverage: float,
) -> VenuePairOrderLeg:
    native_symbol = _venue_pair_symbol_ref(leg, symbol)
    existing = _venue_pair_existing_size(leg, native_symbol)
    if abs(existing) > 1e-9:
        raise SystemExit(f"{leg.label} ja tem posicao aberta em {symbol}: {existing:+.8f}")
    entry_price = _venue_pair_mid_price(leg, native_symbol)
    if entry_price <= 0:
        raise SystemExit(f"{leg.label} sem preco medio valido para {symbol}")
    quantity = _venue_pair_round_qty(leg, native_symbol, notional_usd / entry_price)
    if quantity <= 0:
        raise SystemExit(f"{leg.label} quantidade arredondada ficou zero para notional ${notional_usd:.2f}")
    return VenuePairOrderLeg(
        leg=leg,
        side=side,
        native_symbol=native_symbol,
        entry_price=entry_price,
        quantity=quantity,
        margin_mode=margin_mode,
        leverage=leverage,
    )


def _venue_pair_state_payload(symbol: str, long_leg: VenuePairOrderLeg, short_leg: VenuePairOrderLeg, requested_notional: float, requested_margin: float, sizing_source: str) -> dict:
    return {
        "symbol": symbol,
        "execution_mode": "venue_pair",
        "effective_venue": f"{long_leg.leg.label}:{short_leg.leg.label}",
        "requested_notional_usd": requested_notional,
        "requested_margin_usd": requested_margin,
        "sizing_source": sizing_source,
        "opened_at": time.time(),
        "legs": [
            {
                "role": "long",
                "venue_type": long_leg.leg.spec.venue_type,
                "venue_id": long_leg.leg.spec.venue_id,
                "label": long_leg.leg.label,
                "side": long_leg.side,
                "native_symbol": long_leg.native_symbol,
                "quantity": long_leg.quantity,
                "entry_price": long_leg.entry_price,
                "margin_mode": long_leg.margin_mode,
                "leverage": long_leg.leverage,
            },
            {
                "role": "short",
                "venue_type": short_leg.leg.spec.venue_type,
                "venue_id": short_leg.leg.spec.venue_id,
                "label": short_leg.leg.label,
                "side": short_leg.side,
                "native_symbol": short_leg.native_symbol,
                "quantity": short_leg.quantity,
                "entry_price": short_leg.entry_price,
                "margin_mode": short_leg.margin_mode,
                "leverage": short_leg.leverage,
            },
        ],
    }


def _save_venue_pair_state(payload: dict, *, replace: bool = False) -> None:
    path = _venue_pair_state_path()
    if path.exists() and not replace:
        raise SystemExit(f"ja existe state de venue-pair em {path}; feche ou use --replace-state")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _load_venue_pair_state() -> dict:
    path = _venue_pair_state_path()
    if not path.exists():
        raise SystemExit(f"sem state de venue-pair em {path}")
    return json.loads(path.read_text())


def cmd_open_venue_pair(args: argparse.Namespace) -> None:
    symbol = args.symbol.upper()
    long_spec = _parse_venue_pair_spec(args.long_venue)
    short_spec = _parse_venue_pair_spec(args.short_venue)
    if long_spec == short_spec:
        raise SystemExit("long-venue e short-venue precisam ser venues diferentes")
    leverage = float(args.leverage or _load_optional_float_arg(None, "LEVERAGE", "DEFAULT_LEVERAGE") or 1.0)
    margin_mode = _normalize_margin_mode_arg(args.margin_mode) or _default_margin_mode_from_env() or MARGIN_MODE_CROSS
    notional_usd, requested_margin, sizing_source, sizing_error = _resolve_operational_notional(
        notional_usd=args.notional,
        margin_usd=args.margin_usd,
        leverage=leverage,
        default_notional_usd=float(os.environ.get("VOLUME_ORDER", "100")),
    )
    if sizing_error:
        raise SystemExit(sizing_error)
    if notional_usd <= 0:
        raise SystemExit("notional efetivo precisa ser maior que zero")

    long_leg = _build_venue_pair_leg(long_spec)
    short_leg = _build_venue_pair_leg(short_spec)
    long_order = _build_venue_pair_order_leg(
        long_leg,
        symbol=symbol,
        side="long",
        notional_usd=notional_usd,
        margin_mode=margin_mode,
        leverage=leverage,
    )
    short_order = _build_venue_pair_order_leg(
        short_leg,
        symbol=symbol,
        side="short",
        notional_usd=notional_usd,
        margin_mode=margin_mode,
        leverage=leverage,
    )

    logger.info("venue-pair plano | %s | long=%s qty=%.8f @ %.6f | short=%s qty=%.8f @ %.6f | notional=$%.2f | margin=%s | lev=%.2fx",
        symbol,
        long_order.leg.label,
        long_order.quantity,
        long_order.entry_price,
        short_order.leg.label,
        short_order.quantity,
        short_order.entry_price,
        notional_usd,
        margin_mode,
        leverage,
    )
    payload = _venue_pair_state_payload(symbol, long_order, short_order, notional_usd, requested_margin, sizing_source)
    if args.dry_run:
        logger.info("venue-pair dry-run | nenhuma ordem enviada")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    try:
        _venue_pair_place_order(long_order)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"falha ao abrir perna long em {long_order.leg.label}: {exc}") from exc
    try:
        _venue_pair_place_order(short_order)
    except Exception as exc:  # noqa: BLE001
        logger.error("venue-pair falhou na perna short; revertendo long em %s", long_order.leg.label)
        try:
            _venue_pair_place_order(long_order, reduce_only=True)
        except Exception as rollback_exc:  # noqa: BLE001
            logger.error("venue-pair rollback da perna long falhou: %s", rollback_exc)
        raise SystemExit(f"falha ao abrir perna short em {short_order.leg.label}: {exc}") from exc
    _save_venue_pair_state(payload, replace=args.replace_state)
    logger.info("venue-pair aberto e state salvo em %s", _venue_pair_state_path())


def cmd_close_venue_pair(args: argparse.Namespace) -> None:
    state = _load_venue_pair_state()
    legs = list(state.get("legs") or [])
    if len(legs) != 2:
        raise SystemExit("state de venue-pair invalido: esperado legs com 2 pernas")
    errors: list[str] = []
    for raw_leg in legs:
        spec = VenuePairSpec(str(raw_leg.get("venue_type") or ""), str(raw_leg.get("venue_id") or ""))
        leg = _build_venue_pair_leg(spec)
        order_leg = VenuePairOrderLeg(
            leg=leg,
            side=str(raw_leg.get("side") or ""),
            native_symbol=_venue_pair_symbol_ref(leg, str(state.get("symbol") or "")),
            entry_price=float(raw_leg.get("entry_price") or 0.0),
            quantity=float(raw_leg.get("quantity") or 0.0),
            margin_mode=str(raw_leg.get("margin_mode") or MARGIN_MODE_CROSS),
            leverage=float(raw_leg.get("leverage") or 0.0),
        )
        if order_leg.quantity <= 0 or order_leg.side not in {"long", "short"}:
            errors.append(f"perna invalida no state: {raw_leg}")
            continue
        if args.dry_run:
            logger.info("venue-pair close dry-run | %s %s qty=%.8f", leg.label, order_leg.side, order_leg.quantity)
            continue
        try:
            _venue_pair_place_order(order_leg, reduce_only=True)
            logger.info("venue-pair close | %s %s qty=%.8f", leg.label, order_leg.side, order_leg.quantity)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{leg.label}: {exc}")
    if errors:
        raise SystemExit("falha ao fechar venue-pair: " + "; ".join(errors))
    if not args.dry_run and args.clear_state:
        _venue_pair_state_path().unlink(missing_ok=True)
        logger.info("venue-pair state removido de %s", _venue_pair_state_path())


class _UnavailableNadoTrader:
    """Stub seguro para fluxos Kraken-only que nao devem exigir credencial Nado."""

    def __init__(self, symbol_map: dict[str, int] | None = None):
        self._symbol_map = dict(symbol_map or {})

    def get_symbol_to_product_map(self) -> dict[str, int]:
        return dict(self._symbol_map)

    def get_all_positions(self) -> list:
        return []

    def get_isolation_context(self) -> dict:
        return {
            "subaccount_name": "-",
            "signer_mode": "not_required_kraken_only",
            "trade_ready": False,
        }

    def __getattr__(self, name: str):
        raise RuntimeError(f"Nado indisponivel neste fluxo Kraken-only: {name}")


def load_nado_trader_class():
    """Importa a classe da venue Nado sob demanda.

    O SDK `nado-protocol` e a unica dependencia de venue que exige toolchain
    nativo (web3 + extensoes C). Quem opera Hyperliquid/CEX nao precisa dele,
    entao o import fica aqui em vez do topo do modulo. Ausencia vira erro
    explicito no ponto de uso -- nunca fallback mudo.
    """
    try:
        from workspace.nado.nado_integration import NadoTrader as _NadoTrader
    except ImportError as exc:
        raise SystemExit(
            "A venue Nado exige o SDK `nado-protocol`, que nao esta instalado neste ambiente "
            f"({exc}). Instale com `pip install -r workspace/requirements-nado.txt` "
            "(requer toolchain de build nativo) ou selecione outra DEX com DEX_ID=hyperliquid."
        ) from exc
    return _NadoTrader


def _is_builtin_nado_dex(dex_id: str) -> bool:
    return dex_id in {"nado", "nado-dex", "nado_dex"}


def _is_builtin_hyperliquid_dex(dex_id: str) -> bool:
    return dex_id in {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}


def _is_builtin_kraken_cex(cex_id: str) -> bool:
    return cex_id in {"kraken", "krakenfutures", "kraken-futures", "kraken_futures", "kraken-spot"}


def _load_cex_market_type(cex_id: str) -> str:
    value = _first_env("CEX_MARKET_TYPE", "CEX_DEFAULT_TYPE", f"{cex_id.upper().replace('-', '_')}_MARKET_TYPE")
    return _normalize_cex_market_type(value, cex_id)


def _load_cex_sandbox(cex_id: str) -> bool:
    return resolve_sandbox("cex", cex_id)


HYPERLIQUID_TESTNET_NETWORKS = frozenset({"testnet", "sandbox", "demo"})
# Os dois lados explicitos, pelo mesmo motivo do vocabulario de booleano: a
# versao anterior testava so a pertinencia ao conjunto de testnet, entao
# `HYPERLIQUID_NETWORK=testnetz` resolvia para producao em silencio. Pior que o
# `ture` original, porque este valor entra na camada de ambiente e por isso
# derruba tambem o `venues.dex.*.sandbox` do arquivo.
HYPERLIQUID_MAINNET_NETWORKS = frozenset({"mainnet", "main", "production", "prod", "live"})


def _hyperliquid_rede_implica_sandbox(network: str) -> bool | None:
    """`True`/`False` para rede declarada, `None` quando nao ha rede.

    Valor fora do vocabulario levanta em vez de virar producao.
    """
    if not network:
        return None
    if network in HYPERLIQUID_TESTNET_NETWORKS:
        return True
    if network in HYPERLIQUID_MAINNET_NETWORKS:
        return False
    raise ConfigError(
        f"rede invalida para a Hyperliquid: {network!r}. "
        f"Use um de {sorted(HYPERLIQUID_TESTNET_NETWORKS)} ou "
        f"{sorted(HYPERLIQUID_MAINNET_NETWORKS)}. "
        "Valor nao reconhecido nao e tratado como mainnet -- aqui isso "
        "significaria dinheiro real."
    )


def _first_env_name(*names: str) -> str | None:
    """Nome da primeira env definida do grupo -- para mensagens.

    O aviso de conflito citava `HYPERLIQUID_NETWORK` mesmo quando quem decidia
    era `DEX_NETWORK`, mandando o operador mexer numa variavel que ele nao
    tinha definido.
    """
    for name in names:
        if _clean_literal_env(os.environ.get(name)):
            return name
    return None


def _hyperliquid_sandbox(
    dex_id: str,
    network: str,
    rede_implica_sandbox: bool | None,
    rede_env: str | None = None,
) -> bool:
    """Sandbox da Hyperliquid, avisando quando a rede declarada e descartada.

    `HyperliquidDexTrader.__init__` faz `self.network = "testnet" if
    self.sandbox else "mainnet"`: a rede declarada nao sobrevive ao construtor,
    quem manda e o sandbox. Enquanto `HYPERLIQUID_SANDBOX=false` vinha ativo no
    `.env.example` ao lado de `HYPERLIQUID_NETWORK`, trocar so a rede para
    `testnet` deixava o operador na mainnet sem nada dizer.

    A precedencia nao muda -- a env explicita responde a pergunta e continua
    vencendo --, mas a contradicao para de ser silenciosa.
    """
    sandbox = resolve_sandbox(
        "dex",
        dex_id,
        env_default=rede_implica_sandbox,
        env_default_origem=rede_env or "a rede configurada",
    )
    if rede_implica_sandbox is not None and rede_implica_sandbox != sandbox:
        logger.warning(
            "hyperliquid: %s=%r implica sandbox=%s, mas a configuracao resolveu sandbox=%s. "
            "O adapter deriva a rede do sandbox, entao voce vai operar em %s. "
            "Alinhe a rede e a configuracao de sandbox (%s).",
            rede_env or "a rede configurada", network, rede_implica_sandbox, sandbox,
            "testnet" if sandbox else "mainnet",
            " / ".join(sandbox_env_names("dex", dex_id)),
        )
    return sandbox


def _load_hyperliquid_config(dex_id: str) -> dict:
    cfg = dex_config(dex_id)
    network = (_first_env("HYPERLIQUID_NETWORK", "DEX_NETWORK") or str(cfg.get("network") or "")).lower()
    # `None` quando nenhuma rede foi declarada: uma expressao como
    # `network in {...}` e sempre um bool, e esse `False` incondicional
    # entraria na camada de ambiente como se alguem o tivesse escrito,
    # derrubando o settings do operador.
    rede_env = _first_env_name("HYPERLIQUID_NETWORK", "DEX_NETWORK")
    rede_implica_sandbox = _hyperliquid_rede_implica_sandbox(network)
    options_json = _first_env("HYPERLIQUID_OPTIONS_JSON", "DEX_OPTIONS_JSON")
    cfg.update(
        wallet_address=(
            _first_env("HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_ACCOUNT_ADDRESS")
            or str(cfg.get("wallet_address") or cfg.get("walletAddress") or "")
        ),
        private_key=(
            _first_env(
                "HYPERLIQUID_PRIVATE_KEY",
                "HYPERLIQUID_API_PRIVATE_KEY",
                "HYPERLIQUID_AGENT_PRIVATE_KEY",
            )
            or str(cfg.get("private_key") or cfg.get("privateKey") or "")
        ),
        vault_address=(
            _first_env("HYPERLIQUID_VAULT_ADDRESS")
            or str(cfg.get("vault_address") or cfg.get("vaultAddress") or "")
        ),
        sandbox=_hyperliquid_sandbox(dex_id, network, rede_implica_sandbox, rede_env),
        market_type=_first_env("HYPERLIQUID_MARKET_TYPE", "DEX_MARKET_TYPE") or str(cfg.get("market_type") or "swap"),
        symbol_quote=_first_env("HYPERLIQUID_SYMBOL_QUOTE") or str(cfg.get("symbol_quote") or "USDT"),
    )
    if options_json:
        cfg["options_json"] = options_json
    return cfg


def _build_hyperliquid_trader(dex_id: str, *, require_credentials: bool) -> HyperliquidDexTrader:
    config = _load_hyperliquid_config(dex_id)
    if require_credentials and (not config.get("wallet_address") or not config.get("private_key")):
        raise SystemExit(
            "Configure HYPERLIQUID_WALLET_ADDRESS e HYPERLIQUID_PRIVATE_KEY "
            "no env/secret manager para operar Hyperliquid"
        )
    return HyperliquidDexTrader.from_config(config)


def build_engine(*, require_nado: bool = True, require_kraken: bool = True) -> DeltaNeutralEngine:
    # require_nado/require_kraken ficam por compatibilidade com os fluxos existentes.
    # Internamente eles significam require_dex/require_cex.
    require_dex = require_nado
    require_cex = require_kraken

    # OpenClaw: não carregar dotfile automaticamente quando secrets vêm do runtime/service keys.
    if os.environ.get("DELTA_NEUTRAL_ENV_FILE") or not (
        os.environ.get("QC_SECRETS_PROXY") or os.environ.get("QC_SERVICE_KEY_NAMES")
    ):
        load_dotenv()

    venues = selected_venues()
    dex_id = venues.dex_id
    cex_id = venues.cex_id

    if _is_builtin_kraken_cex(cex_id):
        kraken_key = (
            _clean_literal_env(os.environ.get("KRAKEN_API_KEY"))
            or _clean_literal_env(os.environ.get("KRAKEN_API_KEY_"))
            or cex_credentials(cex_id)["api_key"]
        )
        kraken_secret = _clean_literal_env(os.environ.get("KRAKEN_API_SECRET")) or cex_credentials(cex_id)["api_secret"]
        if require_cex and (not kraken_key or not kraken_secret):
            raise SystemExit("Configure KRAKEN_API_KEY/KRAKEN_API_KEY_ e KRAKEN_API_SECRET no env/secret manager")
        kraken_venue = (_clean_literal_env(os.environ.get("KRAKEN_VENUE")) or _load_cex_market_type(cex_id)).lower()
        if cex_id == "kraken-spot":
            kraken_venue = "spot"
        if kraken_venue == "swap":
            kraken_venue = "futures"
        # `KRAKEN_SANDBOX` continua valendo para as variantes: e uma env de
        # familia, declarada em `workspace.venues.sandbox`.
        kraken_sandbox = resolve_sandbox("cex", cex_id)
        kraken_account = (_clean_literal_env(os.environ.get("KRAKEN_ACCOUNT")) or "flex").lower()
        kraken_account_symbol = _clean_literal_env(os.environ.get("KRAKEN_ACCOUNT_SYMBOL"))
        kraken_require_subaccount = _load_bool_env("KRAKEN_REQUIRE_SUBACCOUNT", False)  # opcional: usuario decide exigir subconta
        kraken_api_is_subaccount = _load_bool_env("KRAKEN_API_IS_SUBACCOUNT", False)
        kraken_allow_main_account_requested = _load_bool_env("KRAKEN_ALLOW_MAIN_ACCOUNT", False)
        kraken = KrakenTrader(
            kraken_key,
            kraken_secret,
            venue=kraken_venue,
            sandbox=kraken_sandbox,
            account=kraken_account,
            account_symbol=kraken_account_symbol,
            require_subaccount=kraken_require_subaccount,
            declared_is_subaccount=kraken_api_is_subaccount,
        )
    else:
        creds = cex_credentials(cex_id)
        if require_cex and (not creds["api_key"] or not creds["api_secret"]):
            expected = venue_summary()["cex_required_env"]
            raise SystemExit(
                f"Configure credenciais da CEX {cex_id}: "
                f"api key em {expected['api_key']} e secret em {expected['api_secret']}"
            )
        kraken_require_subaccount = False
        kraken_api_is_subaccount = True
        kraken_allow_main_account_requested = False
        kraken = GenericCcxtTrader.from_options_json(
            cex_id,
            creds["api_key"],
            creds["api_secret"],
            api_password=creds["api_password"],
            market_type=_load_cex_market_type(cex_id),
            sandbox=_load_cex_sandbox(cex_id),
            options_json=_first_env("CEX_OPTIONS_JSON", f"{cex_id.upper().replace('-', '_')}_OPTIONS_JSON"),
        )

    privileged_fallback_confirmed = _load_bool_env("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK", False)
    nado_allow_owner_fallback = False

    if _is_builtin_nado_dex(dex_id):
        nado_key = _load_nado_owner_private_key()
        nado_network = (
            _clean_literal_env(os.environ.get("NADO_NETWORK"))
            or _clean_literal_env(os.environ.get("NETWORK"))
            or "testnet"
        ).lower()
        if require_dex and not nado_key:
            raise SystemExit("Configure NADO_OWNER_PRIVATE_KEY no env/secret manager para fluxos Nado/hedged")
        if require_dex and nado_key:
            nado_subaccount_name = _clean_literal_env(os.environ.get("NADO_SUBACCOUNT_NAME")) or "default_1"
            nado_linked_signer = _clean_literal_env(os.environ.get("NADO_LINKED_SIGNER_PRIVATE_KEY"))
            nado_require_linked_signer = _load_bool_env("NADO_REQUIRE_LINKED_SIGNER", True)
            nado_allow_owner_fallback_requested = _load_bool_env("NADO_ALLOW_OWNER_FALLBACK", False)
            # Regra operacional da skill: quando nao houver linked signer configurado,
            # a Nado deve assinar com o owner da subconta em vez de bloquear trade.
            # Fallback owner por erro/mismatch de linked signer continua exigindo
            # confirmacao privilegiada explicita.
            nado_allow_owner_fallback = bool(
                not nado_linked_signer
                or (nado_allow_owner_fallback_requested and privileged_fallback_confirmed)
            )
            nado_kwargs = {
                "subaccount_name": nado_subaccount_name,
                "linked_signer_private_key": nado_linked_signer,
                "require_linked_signer": nado_require_linked_signer,
            }
            nado_trader_cls = load_nado_trader_class()
            if "allow_owner_fallback" in inspect.signature(nado_trader_cls).parameters:
                nado_kwargs["allow_owner_fallback"] = nado_allow_owner_fallback
            nado = nado_trader_cls(nado_key, nado_network, **nado_kwargs)
        else:
            kraken_symbols = kraken.get_symbol_to_product_map()
            nado = _UnavailableNadoTrader({symbol: 0 for symbol in kraken_symbols})
    elif _is_builtin_hyperliquid_dex(dex_id):
        nado = _build_hyperliquid_trader(dex_id, require_credentials=require_dex)
    elif require_dex:
        adapter_spec = dex_adapter_spec(dex_id)
        if not adapter_spec:
            raise SystemExit(
                f"DEX_ID={dex_id} exige DEX_ADAPTER_MODULE no formato pacote.modulo:Classe. "
                "O adapter precisa implementar a interface de trading DEX documentada em SKILL.md."
            )
        nado = load_custom_dex_adapter(adapter_spec, dex_config(dex_id))
    else:
        kraken_symbols = kraken.get_symbol_to_product_map()
        nado = _UnavailableNadoTrader({symbol: 0 for symbol in kraken_symbols})

    engine = DeltaNeutralEngine(
        nado=nado,
        kraken=kraken,
        volume_per_leg_usd=float(os.environ.get("VOLUME_ORDER", "100")),
        drift_bps=int(os.environ.get("DRIFT_BPS", "50")),
        max_pair_loss_pct=float(os.environ.get("MAX_PAIR_LOSS_PCT", "0.03")),
        slippage_bps=int(os.environ.get("SLIPPAGE_BPS", "100")),
    )
    engine.dex_id = dex_id
    engine.cex_id = cex_id
    engine.kraken_require_subaccount = kraken_require_subaccount
    engine.kraken_api_is_subaccount = kraken_api_is_subaccount
    engine.privileged_fallback_confirmed = privileged_fallback_confirmed
    engine.nado_allow_owner_fallback = nado_allow_owner_fallback
    engine.kraken_allow_main_account = bool(kraken_allow_main_account_requested and privileged_fallback_confirmed)
    engine.protective_stop_loss_pct = float(
        os.environ.get("PROTECTIVE_STOP_LOSS_PCT", os.environ.get("MAX_PAIR_LOSS_PCT", "0.03"))
    )
    engine.protective_take_profit_pct = float(
        os.environ.get("PROTECTIVE_TAKE_PROFIT_PCT", "0.0")
    )
    engine.protective_stop_trigger_slippage_pct = float(
        os.environ.get("PROTECTIVE_STOP_TRIGGER_SLIPPAGE_PCT", "0.01")
    )
    return engine


def _symbol_universe_for_execution_mode(eng: DeltaNeutralEngine, execution_mode: str | None = None) -> list[str]:
    excluded = set(_parse_symbol_list(os.environ.get("DEX_DISABLED_PERP_SYMBOLS"), default=[]))
    excluded.update(_parse_symbol_list(os.environ.get("DEX_EXCLUDE_SYMBOLS"), default=[]))
    excluded.update(_parse_symbol_list(os.environ.get("NADO_DISABLED_PERP_SYMBOLS"), default=[]))
    excluded.update(_parse_symbol_list(os.environ.get("NADO_EXCLUDE_SYMBOLS"), default=[]))
    if not excluded and getattr(eng, "dex_id", "nado") in {"nado", "nado-dex", "nado_dex"}:
        excluded = {"ADA/USDT", "ARB/USDT"}
    if execution_mode == EXECUTION_MODE_KRAKEN_ONLY:
        raw_symbols = sorted(getattr(eng, "_kraken_symbol_map", {}) or {})
    elif execution_mode == EXECUTION_MODE_NADO_ONLY:
        raw_symbols = sorted(getattr(eng, "_nado_symbol_map", {}) or {})
    else:
        raw_symbols = eng.common_symbols()
    return [sym for sym in raw_symbols if sym not in excluded]


def _resolve_symbols(eng: DeltaNeutralEngine, symbol: str, *, execution_mode: str | None = None) -> list[str]:
    common = _symbol_universe_for_execution_mode(eng, execution_mode)
    raw = symbol.strip()
    if raw.lower() == "all":
        return common
    selected: list[str] = []
    for chunk in raw.split(","):
        requested = chunk.strip().upper()
        if not requested:
            continue
        if requested not in common:
            raise SystemExit(f"simbolo nao elegivel: {requested}")
        if requested not in selected:
            selected.append(requested)
    if not selected:
        raise SystemExit("informe ao menos um simbolo elegivel")
    return selected


def _collect_simulation_context(eng: DeltaNeutralEngine, symbol: str) -> dict:
    kraken_symbol = eng._kraken_symbol_map[symbol]
    funding_rate = eng.kraken.get_funding_rate(kraken_symbol)
    context_note = ""
    try:
        buy_conflicts = eng.kraken.get_market_order_conflicts(kraken_symbol, is_buy=True)
        sell_conflicts = eng.kraken.get_market_order_conflicts(kraken_symbol, is_buy=False)
        has_self_fill_risk = bool(buy_conflicts or sell_conflicts)
    except Exception as exc:  # noqa: BLE001
        has_self_fill_risk = True
        context_note = f"preflight Kraken indisponivel: {exc}"
    return {
        "kraken_symbol": kraken_symbol,
        "funding_rate": funding_rate,
        "has_self_fill_risk": has_self_fill_risk,
        "context_note": context_note,
    }


def _log_matrix_row(prefix: str, row) -> None:
    logger.info(
        "%s cenario=%s | risco=%s | acao=%s | ordem_real=%s | fluxo=%s | label=%s",
        prefix,
        row.scenario,
        row.risco,
        row.acao_esperada,
        _bool_pt(row.ordem_real_permitida),
        row.fluxo,
        row.response_label,
    )


def _save_json_payload(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("resultado salvo em %s", path)


def _serialize_candidate_results(candidates: list[CalibrationCandidateResult]) -> list[dict]:
    return [candidate.to_dict() for candidate in candidates]


def _log_calibration_leaderboard(
    title: str,
    candidates: list[CalibrationCandidateResult],
    *,
    top_n: int = 10,
) -> None:
    logger.info("%s", title)
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            not candidate.eligible,
            -candidate.median_sharpe_ratio,
            -candidate.median_total_pnl,
            candidate.median_max_drawdown,
            candidate.candidate_key,
        ),
    )
    for index, candidate in enumerate(ranked[:top_n], start=1):
        status = "eligible" if candidate.eligible else f"rejected ({candidate.rejection_reason})"
        logger.info(
            "  %d. %s | sharpe=%.3f | pnl=%+.2f%% | dd=%.2f%% | trades=%.1f | qualified=%d | %s",
            index,
            candidate.candidate_key,
            candidate.median_sharpe_ratio,
            candidate.median_total_pnl,
            candidate.median_max_drawdown,
            candidate.median_total_trades,
            candidate.trade_qualified_symbols,
            status,
        )


def cmd_venues(_: argparse.Namespace) -> None:
    # Este comando existe para mostrar a configuracao: se ela estiver
    # invalida, a mensagem e a resposta, nao um traceback.
    try:
        summary = venue_summary()
    except ConfigError as exc:
        raise SystemExit(f"Configuracao de venue invalida: {exc}") from exc
    logger.info("venues | DEX=%s adapter=%s | CEX=%s adapter=%s market=%s sandbox=%s",
                summary["dex_id"], summary["dex_adapter"], summary["cex_id"], summary["cex_adapter"],
                summary["cex_market_type"], summary["cex_sandbox"])
    logger.info("CEX credentials configured: %s", _bool_pt(bool(summary["cex_credentials_configured"])))
    logger.info("CEX env esperadas: api_key=%s api_secret=%s api_password=%s",
                ",".join(summary["cex_required_env"]["api_key"]),
                ",".join(summary["cex_required_env"]["api_secret"]),
                ",".join(summary["cex_required_env"]["api_password"]))
    logger.info("DEX adapter configured: %s", _bool_pt(bool(summary["dex_adapter_configured"])))
    logger.info("DEX env esperadas: %s", json.dumps(summary["dex_required_env"], ensure_ascii=False, sort_keys=True))


def cmd_symbols(_: argparse.Namespace) -> None:
    selected = selected_venues()
    eng = build_engine(require_nado=not _is_builtin_hyperliquid_dex(selected.dex_id))
    syms = eng.common_symbols()
    dex_label = getattr(eng, "dex_id", "dex")
    cex_label = getattr(eng, "cex_id", "cex")
    logger.info("%d simbolos comuns em DEX=%s e CEX=%s:", len(syms), dex_label, cex_label)
    for symbol in syms:
        logger.info(
            "  %s   dex=%s  cex=%s",
            symbol,
            eng._nado_symbol_map[symbol],
            eng._kraken_symbol_map[symbol],
        )


def _load_asset_scan_state() -> dict:
    try:
        if ASSET_SCAN_STATE_FILE.exists():
            return json.loads(ASSET_SCAN_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("asset-scan: falha ao ler estado anterior: %s", exc)
    return {}


def _save_asset_scan_state(payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_SCAN_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_kraken_mid(eng: DeltaNeutralEngine, symbol: str) -> float:
    kraken_symbol = eng._kraken_symbol_map.get(symbol, "")
    if not kraken_symbol:
        return 0.0
    try:
        return float(eng.kraken.get_market_mid_price(kraken_symbol) or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _safe_nado_mid(eng: DeltaNeutralEngine, symbol: str) -> float:
    product_id = eng._nado_symbol_map.get(symbol)
    if product_id is None:
        return 0.0
    try:
        return float(eng.nado.get_market_mid_price(product_id) or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _asset_health(eng: DeltaNeutralEngine, symbol: str, *, spread_limit_pct: float) -> dict:
    nado_mid = _safe_nado_mid(eng, symbol)
    kraken_mid = _safe_kraken_mid(eng, symbol)
    nado_valid = eng._is_valid_market_price(nado_mid)
    kraken_valid = kraken_mid > 0
    spread_pct = 0.0
    if nado_valid and kraken_valid:
        spread_pct = abs(nado_mid - kraken_mid) / kraken_mid * 100
    warnings: list[str] = []
    if not nado_valid:
        warnings.append(f"preco_nado_invalido={nado_mid:.8g}")
    if not kraken_valid:
        warnings.append("preco_kraken_indisponivel")
    if nado_valid and kraken_valid and spread_pct > spread_limit_pct:
        warnings.append(f"spread_nado_kraken_alto={spread_pct:.2f}%")
    return {
        "symbol": symbol,
        "nado_product_id": eng._nado_symbol_map.get(symbol),
        "kraken_symbol": eng._kraken_symbol_map.get(symbol, ""),
        "nado_mid": nado_mid,
        "kraken_mid": kraken_mid,
        "spread_pct": spread_pct,
        "healthy": nado_valid and kraken_valid and spread_pct <= spread_limit_pct,
        "warnings": warnings,
    }


def cmd_asset_scan(args: argparse.Namespace) -> None:
    eng = build_engine()
    previous = _load_asset_scan_state()
    prev_nado = set(previous.get("nado_perp_symbols") or [])
    prev_kraken = set(previous.get("kraken_symbols") or [])
    prev_common = set(previous.get("common_symbols") or [])

    nado_symbols = sorted(eng._nado_symbol_map)
    kraken_symbols = sorted(eng._kraken_symbol_map)
    common_symbols = sorted(set(nado_symbols) & set(kraken_symbols))
    disabled = set(_parse_symbol_list(os.environ.get("DEX_DISABLED_PERP_SYMBOLS"), default=[]))
    disabled.update(_parse_symbol_list(os.environ.get("DEX_EXCLUDE_SYMBOLS"), default=[]))
    disabled.update(_parse_symbol_list(os.environ.get("NADO_DISABLED_PERP_SYMBOLS"), default=[]))
    disabled.update(_parse_symbol_list(os.environ.get("NADO_EXCLUDE_SYMBOLS"), default=[]))
    effective_symbols = [symbol for symbol in common_symbols if symbol not in disabled]

    health = [_asset_health(eng, symbol, spread_limit_pct=args.spread_limit_pct) for symbol in effective_symbols]
    healthy = [item for item in health if item["healthy"]]
    suspect = [item for item in health if not item["healthy"]]

    logger.info("asset-scan | dex=%s perps=%d | cex=%s mercados=%d | common=%d | efetivos=%d | saudaveis=%d | suspeitos=%d",
                getattr(eng, "dex_id", "dex"), len(nado_symbols), getattr(eng, "cex_id", "cex"), len(kraken_symbols), len(common_symbols), len(effective_symbols), len(healthy), len(suspect))
    if disabled:
        logger.info("asset-scan desabilitados por env: %s", ",".join(sorted(disabled)))

    def _log_delta(label: str, current: set[str], previous_set: set[str]) -> None:
        added = sorted(current - previous_set)
        removed = sorted(previous_set - current)
        if added:
            logger.info("asset-scan %s adicionados: %s", label, ",".join(added))
        if removed:
            logger.warning("asset-scan %s removidos: %s", label, ",".join(removed))

    _log_delta("nado", set(nado_symbols), prev_nado)
    _log_delta("kraken", set(kraken_symbols), prev_kraken)
    _log_delta("common", set(common_symbols), prev_common)

    for item in suspect[: args.max_suspect]:
        logger.warning(
            "asset-scan suspeito | %s | nado=%s mid=%.8g | kraken=%s mid=%.8g | spread=%.2f%% | %s",
            item["symbol"],
            item["nado_product_id"],
            item["nado_mid"],
            item["kraken_symbol"] or "-",
            item["kraken_mid"],
            item["spread_pct"],
            "; ".join(item["warnings"]),
        )

    payload = {
        "scanned_at": datetime.utcnow().isoformat() + "Z",
        "spread_limit_pct": args.spread_limit_pct,
        "nado_perp_symbols": nado_symbols,
        "kraken_symbols": kraken_symbols,
        "common_symbols": common_symbols,
        "disabled_symbols": sorted(disabled),
        "effective_symbols": effective_symbols,
        "healthy_symbols": [item["symbol"] for item in healthy],
        "suspect_symbols": {item["symbol"]: item for item in suspect},
    }
    if not args.no_write:
        _save_asset_scan_state(payload)
        logger.info("asset-scan estado salvo em %s", ASSET_SCAN_STATE_FILE)


def cmd_setups(_: argparse.Namespace) -> None:
    logger.info("setups operacionais disponiveis:")
    for key in ACTIVE_SETUP_KEYS:
        definition = SETUP_CATALOG[key]
        logger.info(
            "  %s | %s | profile=%s | timeframe=%s",
            key,
            definition.label,
            definition.profile,
            definition.timeframe,
        )
        logger.info("    entrada: %s", definition.entry_rule)
        logger.info("    saida:   %s", definition.exit_rule)
        logger.info("    resumo:  %s", definition.description)
        if key == "hybrid":
            logger.info(
                "    perfis:  %s",
                ", ".join(f"{profile.key}/{profile.label}" for profile in HYBRID_PROFILE_MAP.values()),
            )


def cmd_backtest_operational(args: argparse.Namespace) -> None:
    setup_keys = parse_setup_selection(args.setup)
    hybrid_profile = normalize_hybrid_profile(args.hybrid_profile)
    dataset, results = run_operational_backtests(
        setup_keys=setup_keys,
        days=args.days,
        initial_price=args.initial_price,
        seed=args.seed,
        timeframe=args.timeframe,
        hybrid_profile=hybrid_profile,
    )
    per_setup_timeframes = dataset.attrs.get("per_setup_timeframes", {})
    logger.info(
        "validacao operacional concluida | timeframe=%s | candles=%d | periodo=%s -> %s | preco=%.2f -> %.2f",
        dataset.attrs.get("timeframe", args.timeframe or "1h"),
        len(dataset),
        dataset["timestamp"].iloc[0],
        dataset["timestamp"].iloc[-1],
        dataset["close"].iloc[0],
        dataset["close"].iloc[-1],
    )
    if per_setup_timeframes:
        logger.info("timeframes por setup: %s", ", ".join(f"{key}={value}" for key, value in per_setup_timeframes.items()))
    logger.info("ranking final:")
    for index, result in enumerate(rank_backtest_results(results), start=1):
        logger.info(
            "  %d. %s | pnl=%+.2f%% | trades=%d | win_rate=%.1f%% | pf=%.2fx | dd=%.2f%%",
            index,
            result.setup,
            result.total_pnl,
            result.total_trades,
            result.win_rate,
            result.profit_factor,
            result.max_drawdown,
        )

    if args.output:
        payload = {
            "meta": {
                "days": args.days,
                "initial_price": args.initial_price,
                "seed": args.seed,
                "generated_at": dataset["timestamp"].iloc[-1].isoformat(),
                "setup_keys": setup_keys,
                "timeframe": dataset.attrs.get("timeframe", args.timeframe or "1h"),
                "per_setup_timeframes": per_setup_timeframes,
                "hybrid_profile": hybrid_profile,
            },
            "results": serialize_backtest_results(results),
        }
        _save_json_payload(Path(args.output), payload)


def cmd_backtest_hybrid_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_HYBRID_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")
    profile_key = normalize_hybrid_profile(args.profile)

    results, errors = run_hybrid_real_backtests(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
        profile_key=profile_key,
    )
    logger.info(
        "validacao HYBRID real concluida | exchange=%s | timeframe=4h | profile=%s | symbols=%d | ok=%d | errors=%d",
        args.exchange,
        profile_key,
        len(symbols),
        len(results),
        len(errors),
    )
    for symbol, result in results.items():
        logger.info(
            "  %s | pnl=%+.2f%% | trades=%d | win_rate=%.1f%% | pf=%.2fx | dd=%.2f%%",
            symbol,
            result.total_pnl,
            result.total_trades,
            result.win_rate,
            result.profit_factor,
            result.max_drawdown,
        )
    for symbol, message in errors.items():
        logger.warning("  %s | erro=%s", symbol, message)

    if args.output:
        payload = {
            "meta": {
                "days": args.days,
                "exchange": args.exchange,
                "generated_at": datetime.now().isoformat(),
                "setup_keys": ["hybrid"],
                "symbols": symbols,
                "timeframe": "4h",
                "hybrid_profile": profile_key,
            },
            "results": serialize_backtest_results(results),
            "errors": errors,
        }
        _save_json_payload(Path(args.output), payload)


def cmd_backtest_divergence_volume_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")

    results, errors = run_divergence_volume_real_backtests(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
    )
    logger.info(
        "validacao Divergence and Volume real concluida | exchange=%s | timeframe=4h | days=%d | symbols=%d | ok=%d | errors=%d",
        args.exchange,
        args.days,
        len(symbols),
        len(results),
        len(errors),
    )
    for symbol, result in results.items():
        logger.info(
            "  %s | pnl=%+.2f%% | trades=%d | win_rate=%.1f%% | pf=%.2fx | dd=%.2f%%",
            symbol,
            result.total_pnl,
            result.total_trades,
            result.win_rate,
            result.profit_factor,
            result.max_drawdown,
        )
    for symbol, message in errors.items():
        logger.warning("  %s | erro=%s", symbol, message)

    if args.output:
        payload = {
            "meta": {
                "days": args.days,
                "exchange": args.exchange,
                "generated_at": datetime.now().isoformat(),
                "setup_keys": ["divergence-and-volume-4h"],
                "symbols": symbols,
                "timeframe": "4h",
            },
            "results": serialize_backtest_results(results),
            "errors": errors,
        }
        _save_json_payload(Path(args.output), payload)


def cmd_backtest_low_stoch_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_LOW_STOCH_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")

    results, errors = run_low_stoch_real_backtests(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
    )
    logger.info(
        "validacao Low Stoch Storm real concluida | exchange=%s | timeframe=4h | days=%d | symbols=%d | ok=%d | errors=%d",
        args.exchange,
        args.days,
        len(symbols),
        len(results),
        len(errors),
    )
    for symbol, result in results.items():
        logger.info(
            "  %s | pnl=%+.2f%% | trades=%d | win_rate=%.1f%% | pf=%.2fx | dd=%.2f%%",
            symbol,
            result.total_pnl,
            result.total_trades,
            result.win_rate,
            result.profit_factor,
            result.max_drawdown,
        )
    for symbol, message in errors.items():
        logger.warning("  %s | erro=%s", symbol, message)

    if args.output:
        payload = {
            "meta": {
                "days": args.days,
                "exchange": args.exchange,
                "generated_at": datetime.now().isoformat(),
                "setup_keys": ["low-stoch-storm"],
                "symbols": symbols,
                "timeframe": "4h",
            },
            "results": serialize_backtest_results(results),
            "errors": errors,
        }
        _save_json_payload(Path(args.output), payload)


def cmd_backtest_funding_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_FUNDING_ARB_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")

    results, errors = run_funding_real_backtests(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
        min_rate=args.min_rate,
        exit_rate=args.exit_rate,
        max_hold_intervals=args.max_hold_intervals,
    )
    logger.info(
        "validacao funding real concluida | exchange=%s | timeframe=8h | symbols=%d | ok=%d | errors=%d",
        args.exchange,
        len(symbols),
        len(results),
        len(errors),
    )
    for symbol, result in results.items():
        logger.info(
            "  %s | pnl=%+.2f%% | trades=%d | win_rate=%.1f%% | pf=%.2fx | dd=%.2f%%",
            symbol,
            result.total_pnl,
            result.total_trades,
            result.win_rate,
            result.profit_factor,
            result.max_drawdown,
        )
    for symbol, message in errors.items():
        logger.warning("  %s | erro=%s", symbol, message)

    if args.output:
        payload = {
            "meta": {
                "days": args.days,
                "exchange": args.exchange,
                "generated_at": datetime.now().isoformat(),
                "setup_keys": ["funding-arb"],
                "symbols": symbols,
                "timeframe": "8h",
                "min_rate": args.min_rate,
                "exit_rate": args.exit_rate,
                "max_hold_intervals": args.max_hold_intervals,
            },
            "results": serialize_backtest_results(results),
            "errors": errors,
        }
        _save_json_payload(Path(args.output), payload)


def cmd_calibrate_triangle_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_TRIANGLE_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")

    candidates, recommended = calibrate_triangle_real(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
    )
    eligible_count = sum(1 for candidate in candidates if candidate.eligible)
    logger.info(
        "calibracao triangle concluida | exchange=%s | timeframe=1h | days=%d | symbols=%d | candidates=%d | eligible=%d",
        args.exchange,
        args.days,
        len(symbols),
        len(candidates),
        eligible_count,
    )
    _log_calibration_leaderboard("leaderboard triangle-breakout:", candidates)
    if recommended is None:
        logger.warning("nenhuma combinacao triangle ficou elegivel")
    else:
        logger.info("config recomendada triangle-breakout: %s", json.dumps(recommended.config, ensure_ascii=False))

    if args.output:
        payload = {
            "meta": {
                "exchange": args.exchange,
                "days": args.days,
                "symbols": symbols,
                "setup_key": "triangle-breakout",
                "timeframe": "1h",
                "optimization_goal": "sharpe_with_drawdown_cap",
                "drawdown_cap_pct": 12.0,
                "min_trades_per_symbol": 8,
                "min_trade_symbols": 3,
                "generated_at": datetime.now().isoformat(),
            },
            "candidate_results": _serialize_candidate_results(candidates),
            "recommended_config": recommended.to_dict() if recommended is not None else None,
        }
        _save_json_payload(Path(args.output), payload)


def cmd_calibrate_funding_real(args: argparse.Namespace) -> None:
    symbols = _parse_symbol_list(args.symbols, default=DEFAULT_FUNDING_ARB_REAL_SYMBOLS)
    if not symbols:
        raise SystemExit("Informe ao menos um simbolo em --symbols")

    candidates, recommended = calibrate_funding_real(
        symbols=symbols,
        days=args.days,
        exchange_id=args.exchange,
    )
    eligible_count = sum(1 for candidate in candidates if candidate.eligible)
    logger.info(
        "calibracao funding concluida | exchange=%s | timeframe=8h | days=%d | symbols=%d | candidates=%d | eligible=%d",
        args.exchange,
        args.days,
        len(symbols),
        len(candidates),
        eligible_count,
    )
    _log_calibration_leaderboard("leaderboard funding-arb:", candidates)
    if recommended is None:
        logger.warning("nenhuma combinacao funding ficou elegivel")
    else:
        logger.info("config recomendada funding-arb: %s", json.dumps(recommended.config, ensure_ascii=False))

    if args.output:
        payload = {
            "meta": {
                "exchange": args.exchange,
                "days": args.days,
                "symbols": symbols,
                "setup_key": "funding-arb",
                "timeframe": "8h",
                "optimization_goal": "sharpe_with_drawdown_cap",
                "drawdown_cap_pct": 6.0,
                "min_trades_per_symbol": 3,
                "min_trade_symbols": 2,
                "max_spread_bps_fixed": get_funding_arb_config().max_spread_bps,
                "generated_at": datetime.now().isoformat(),
            },
            "candidate_results": _serialize_candidate_results(candidates),
            "recommended_config": recommended.to_dict() if recommended is not None else None,
        }
        _save_json_payload(Path(args.output), payload)


def _open_single_venue_manual(
    eng: DeltaNeutralEngine,
    *,
    symbol: str,
    side: str,
    notional_usd: float | None,
    margin_usd: float | None,
    execution_mode: str,
    margin_mode: str,
    leverage: float,
) -> PairState | None:
    venue = "nado" if execution_mode == EXECUTION_MODE_NADO_ONLY else "kraken"
    signal = SimpleNamespace(
        side=side,
        reason="manual-open",
        stop_price=0.0,
        take_profit=0.0,
        take_profit_targets=[],
        target_weights=[],
    )
    plan = _build_single_venue_order_plan(
        eng,
        setup_key="manual-open",
        symbol=symbol,
        venue=venue,
        signal=signal,
        notional_usd=notional_usd,
        margin_usd=margin_usd,
        margin_mode=margin_mode,
        leverage=leverage,
        min_liquidation_buffer_pct=0.0,
    )
    if not plan.can_execute:
        logger.error("open solo bloqueado | %s %s | reason=%s", venue, symbol, plan.blocked_reason)
        return None
    logger.info(
        "open solo plano | %s | venue=%s | side=%s | margin=%s | lev=%s | qty=%.8f | notional=$%.2f | sizing=%s",
        symbol,
        venue,
        side,
        plan.margin_mode,
        f"{plan.leverage:.2f}x" if plan.leverage > 0 else "-",
        plan.quantity,
        plan.effective_notional_usd,
        plan.sizing_source,
    )
    return _open_single_venue_setup(eng, plan=plan, signal=signal, log_prefix="open solo")


def cmd_open(args: argparse.Namespace) -> None:
    side = _normalize_order_side_arg(getattr(args, "side", None))
    execution_mode = (
        _normalize_execution_mode_arg(getattr(args, "execution_mode", None))
        or _default_execution_mode_from_env()
        or EXECUTION_MODE_HEDGED
    )
    margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "margin_mode", None))
        or _default_margin_mode_from_env()
        or MARGIN_MODE_CROSS
    )
    nado_margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "nado_margin_mode", None))
        or _default_nado_margin_mode_from_env()
        or margin_mode
    )
    kraken_margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "kraken_margin_mode", None))
        or _default_kraken_margin_mode_from_env()
        or margin_mode
    )
    leverage = _load_optional_float_arg(getattr(args, "leverage", None), "LEVERAGE", "DEFAULT_LEVERAGE")
    nado_leverage = _load_optional_float_arg(
        getattr(args, "nado_leverage", None),
        "NADO_LEVERAGE",
        "DEFAULT_NADO_LEVERAGE",
        "DEX_LEVERAGE",
    ) or leverage
    kraken_leverage = _load_optional_float_arg(
        getattr(args, "kraken_leverage", None),
        "KRAKEN_LEVERAGE",
        "DEFAULT_KRAKEN_LEVERAGE",
        "CEX_LEVERAGE",
    ) or leverage
    margin_usd = float(_load_optional_float_arg(getattr(args, "margin_usd", None), "MARGIN_USD", "DEFAULT_MARGIN_USD") or 0.0)
    nado_margin_usd = _load_optional_float_arg(
        getattr(args, "nado_margin_usd", None),
        "NADO_MARGIN_USD",
        "DEFAULT_NADO_MARGIN_USD",
        "DEX_MARGIN_USD",
    )
    nado_margin_usd = float(nado_margin_usd if nado_margin_usd is not None else margin_usd)
    kraken_margin_usd = _load_optional_float_arg(
        getattr(args, "kraken_margin_usd", None),
        "KRAKEN_MARGIN_USD",
        "DEFAULT_KRAKEN_MARGIN_USD",
        "CEX_MARGIN_USD",
    )
    kraken_margin_usd = float(kraken_margin_usd if kraken_margin_usd is not None else margin_usd)

    needs_nado = execution_mode in {EXECUTION_MODE_HEDGED, EXECUTION_MODE_NADO_ONLY}
    needs_kraken = execution_mode in {EXECUTION_MODE_HEDGED, EXECUTION_MODE_KRAKEN_ONLY}
    eng = build_engine(require_nado=needs_nado, require_kraken=needs_kraken)
    _log_active_trade_context(eng)

    if needs_nado:
        eng._assert_nado_trade_ready()
    if needs_kraken:
        eng.kraken.validate_entry_subaccount_rule(
            require_subaccount=getattr(eng, "kraken_require_subaccount", False),
            declared_is_subaccount=getattr(eng, "kraken_api_is_subaccount", False),
        )

    symbol = args.symbol.upper()
    if execution_mode == EXECUTION_MODE_HEDGED:
        hedged_margin_usd = _resolve_margin_for_execution_mode(
            execution_mode,
            margin_usd,
            nado_margin_usd,
            kraken_margin_usd,
        )
        open_notional = args.notional
        if hedged_margin_usd > 0:
            open_notional, _, _, sizing_error = _resolve_operational_notional(
                notional_usd=args.notional,
                margin_usd=hedged_margin_usd,
                leverage=kraken_leverage or nado_leverage,
                default_notional_usd=eng.volume_per_leg,
            )
            if sizing_error:
                raise SystemExit(sizing_error)
        state = eng.open_pair(
            symbol,
            nado_side=side,
            notional_usd=open_notional,
            nado_leverage=nado_leverage,
            nado_margin_mode=nado_margin_mode,
            kraken_leverage=kraken_leverage,
            kraken_margin_mode=kraken_margin_mode,
        )
    else:
        state = _open_single_venue_manual(
            eng,
            symbol=symbol,
            side=side,
            notional_usd=args.notional,
            margin_usd=nado_margin_usd if execution_mode == EXECUTION_MODE_NADO_ONLY else kraken_margin_usd,
            execution_mode=execution_mode,
            margin_mode=nado_margin_mode if execution_mode == EXECUTION_MODE_NADO_ONLY else kraken_margin_mode,
            leverage=nado_leverage if execution_mode == EXECUTION_MODE_NADO_ONLY else kraken_leverage,
        )
    if state:
        save_state(state)
        logger.info("estado salvo em %s", STATE_FILE)


def cmd_status(_: argparse.Namespace) -> None:
    state = load_state()
    if state is None:
        eng = build_engine()
        if _log_live_status(eng, header="sem par gerenciado em state.json; exibindo posicoes live detectadas"):
            return
        logger.info("(sem par aberto)")
        return
    eng = build_engine()
    eng.status(state)


def cmd_live_status(_: argparse.Namespace) -> None:
    eng = build_engine()
    _log_active_trade_context(eng)
    _log_live_status(eng, header="posicoes live detectadas:")


def cmd_live_hedge(args: argparse.Namespace) -> None:
    eng = build_engine()
    _log_active_trade_context(eng)
    actions = _plan_live_hedges(eng, symbol=args.symbol, target_exchange=args.target)
    _log_live_hedge_plan(actions, dry_run=args.dry_run)
    executed, blocked = _execute_live_hedges(eng, actions, dry_run=args.dry_run)
    logger.info(
        "live-hedge finalizado: executed=%d blocked=%d dry_run=%s",
        executed,
        blocked,
        _bool_pt(args.dry_run),
    )
    _log_live_status(eng, header="status live apos live-hedge:")


def cmd_live_sync(args: argparse.Namespace) -> None:
    eng = build_engine()
    _log_active_trade_context(eng)
    iteration = 0
    try:
        while True:
            iteration += 1
            logger.info("live-sync iteracao=%d", iteration)
            actions = _plan_live_hedges(eng, symbol=args.symbol, target_exchange=args.target)
            _log_live_hedge_plan(actions, dry_run=args.dry_run)
            executed, blocked = _execute_live_hedges(eng, actions, dry_run=args.dry_run)
            logger.info(
                "live-sync iteracao=%d resultado: executed=%d blocked=%d dry_run=%s",
                iteration,
                executed,
                blocked,
                _bool_pt(args.dry_run),
            )
            _log_live_status(eng, header="status live apos iteracao:")
            if args.max_iter is not None and iteration >= args.max_iter:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("live-sync interrompido pelo usuario")


def _scan_setup_entries(
    eng: DeltaNeutralEngine,
    *,
    setup_keys: list[str],
    symbols: list[str],
    hybrid_profile: str,
) -> list[tuple[str, str, pd.DataFrame, object]]:
    active_states = load_setup_live_states()
    active_bases = {_live_base_symbol(state.symbol) for state in active_states}
    scan_setup_keys = _prioritized_setup_keys(setup_keys)
    cycle_bases: set[str] = set()
    entries: list[tuple[str, str, pd.DataFrame, object]] = []
    strict_allowlist = _setup_allowlist_mode() != "open"
    if strict_allowlist:
        _log_setup_allowlists(setup_keys)
    divergence_volume_strict = any(normalize_setup_key(key) == "divergence-and-volume-4h" for key in setup_keys) and _divergence_volume_whitelist_mode() == "strict"
    if divergence_volume_strict:
        allowed_bases = _divergence_volume_allowed_bases()
        blocked_count = sum(1 for symbol in symbols if _live_base_symbol(symbol) not in allowed_bases)
        if blocked_count:
            logger.info(
                "Divergence and Volume whitelist strict ativa | permitidos=%s | bloqueados=%d",
                ",".join(sorted(allowed_bases)),
                blocked_count,
            )

    for symbol in symbols:
        base = _live_base_symbol(symbol)
        if base in active_bases or base in cycle_bases:
            continue
        for setup_key in scan_setup_keys:
            if strict_allowlist and not _setup_symbol_allowed(setup_key, symbol):
                logger.info(
                    "setup-live skip  | %s %s | reason=ativo fora da allowlist do setup",
                    setup_key,
                    symbol,
                )
                continue
            if normalize_setup_key(setup_key) == "divergence-and-volume-4h" and not _divergence_volume_symbol_allowed(symbol):
                logger.info("setup-live skip  | %s %s | reason=ativo fora da whitelist DIVERGENCE_AND_VOLUME", setup_key, symbol)
                continue
            timeframe = SETUP_CATALOG[setup_key].timeframe
            try:
                df = _fetch_setup_market_dataset(eng, symbol, timeframe)
                setup_context = _build_setup_runtime_context(eng, symbol=symbol, setup_key=setup_key)
                signal = evaluate_setup_entry(
                    setup_key,
                    df,
                    hybrid_profile=hybrid_profile,
                    setup_context=setup_context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("scan %s %s falhou: %s", setup_key, symbol, exc)
                break
            if signal is None:
                continue
            signal_side = str(getattr(signal, "side", "") or "").strip().lower()
            signal_reason = str(getattr(signal, "reason", "") or "").strip()
            if signal_side not in {"long", "short"} or not signal_reason:
                logger.warning(
                    "setup-live skip  | %s %s | reason=sinal invalido/incompleto (side=%s, reason=%s)",
                    setup_key,
                    symbol,
                    signal_side or "-",
                    signal_reason or "-",
                )
                continue
            entries.append((setup_key, symbol, df, signal))
            cycle_bases.add(base)
            break
    return entries


def _solo_setup_has_live_position(eng: DeltaNeutralEngine, state: ManagedSetupState) -> bool:
    venue = state.effective_venue
    if venue == "nado":
        qty = eng.nado.get_perp_position_size(state.pair_state.nado_product_id)
        return abs(float(qty or 0.0)) > 1e-9
    if venue == "kraken":
        position = eng.kraken.get_position(state.pair_state.kraken_symbol)
        return abs(float(getattr(position, "size", 0.0) or 0.0)) > 1e-9
    return True


def _live_role_position_qty(eng: DeltaNeutralEngine, state: ManagedSetupState, role: str) -> float | None:
    if role == "nado":
        qty = eng.nado.get_perp_position_size(state.pair_state.nado_product_id)
        return abs(float(qty or 0.0))
    if role == "kraken":
        position = eng.kraken.get_position(state.pair_state.kraken_symbol)
        return abs(float(getattr(position, "size", 0.0) or 0.0))
    return None


def _setup_partial_roles(state: ManagedSetupState) -> list[str]:
    if state.effective_venue == "nado":
        return ["nado"]
    if state.effective_venue == "kraken":
        return ["kraken"]
    return ["nado", "kraken"]


def _setup_has_executable_partial_qty(state: ManagedSetupState) -> bool:
    roles = _setup_partial_roles(state)
    if state.effective_venue == "hedged":
        return all(_state_role_qty(state, role) > 1e-9 for role in roles)
    return any(_state_role_qty(state, role) > 1e-9 for role in roles)


def _reconciled_closed_qty(sync_result: dict[str, Any], role: str) -> float:
    total = 0.0
    for item in sync_result.get("changes", []) if isinstance(sync_result, dict) else []:
        if isinstance(item, dict) and item.get("role") == role:
            total += abs(float(item.get("closed_qty") or 0.0))
    return total


def _reconcile_native_fills_before_partial(eng: DeltaNeutralEngine, state: ManagedSetupState) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    for role in _setup_partial_roles(state):
        try:
            live_qty = _live_role_position_qty(eng, state, role)
        except Exception as exc:  # noqa: BLE001
            logger.warning("setup-live sync parcial | falha ao ler posicao %s em %s: %s", role, state.symbol, exc)
            continue
        if live_qty is None:
            continue
        state_qty = _state_role_qty(state, role)
        if live_qty + 1e-9 < state_qty:
            closed_qty = max(state_qty - live_qty, 0.0)
            _set_state_role_qty(state, role, live_qty)
            changes.append(
                {
                    "role": role,
                    "venue_id": _native_order_venue_id(eng, role),
                    "state_qty_before": state_qty,
                    "live_qty": live_qty,
                    "closed_qty": closed_qty,
                }
            )
    if changes:
        _refresh_state_effective_notional(state)
        sync_event = {"ts": time.time(), "changes": changes}
        state.metadata.setdefault("native_fill_reconciliations", []).append(sync_event)
        summary = ", ".join(
            f"{item['role']} qty {item['state_qty_before']:.8g}->{item['live_qty']:.8g}" for item in changes
        )
        _append_setup_event(state, "Native Fill Sync", f"native TP/fill reconciled before partial: {summary}")
        logger.info("setup-live sync parcial | %s %s | %s", state.setup_key, state.symbol, summary)
    return {"changed": bool(changes), "changes": changes, "has_executable_qty": _setup_has_executable_partial_qty(state)}


def _process_setup_live_states(
    eng: DeltaNeutralEngine,
    states: list[ManagedSetupState],
    *,
    dry_run: bool,
) -> list[ManagedSetupState]:
    remaining: list[ManagedSetupState] = []
    for state in states:
        try:
            is_hedged_state = state.execution_mode == EXECUTION_MODE_HEDGED or state.effective_venue == "hedged"
            if not dry_run and not is_hedged_state and not _solo_setup_has_live_position(eng, state):
                try:
                    manual_close_price = _setup_reference_price(eng, state)
                except Exception:  # noqa: BLE001
                    manual_close_price = _state_entry_price(state)
                logger.info(
                    "setup-live sync | %s %s | venue=%s | posicao manualmente fechada; removendo estado",
                    state.setup_key,
                    state.symbol,
                    state.effective_venue,
                )
                _append_setup_event(
                    state,
                    "Manual Close",
                    f"{state.side.upper()} position manually closed at {manual_close_price}",
                )
                _notify_setup_state_event(
                    state,
                    title="🔒 FECHAMENTO MANUAL 🔒",
                    live_price=manual_close_price,
                    reason="posição não encontrada na corretora; estado removido",
                )
                continue
            df = _fetch_setup_market_dataset(eng, state.symbol, state.timeframe)
            live_price = _setup_reference_price(eng, state)
            _update_state_potential_pnl(state, live_price)
            setup_context = _build_setup_runtime_context(eng, symbol=state.symbol, setup_key=state.setup_key)
            is_dry_run_tracking = dry_run and bool(state.metadata.get("tracking_only"))
            if is_hedged_state and not is_dry_run_tracking and eng.should_unwind(state.pair_state):
                logger.warning("setup-live stop global disparado em %s %s", state.setup_key, state.symbol)
                if dry_run:
                    _append_setup_event(
                        state,
                        "Stop Loss",
                        f"{state.side.upper()} simulated position stopped by global risk at {live_price}",
                    )
                    _notify_setup_state_event(
                        state,
                        title="⛔ STOP LOSS ATINGIDO ⛔",
                        live_price=live_price,
                        reason="stop global disparado",
                    )
                else:
                    eng.unwind(state.pair_state)
                    _append_setup_event(
                        state,
                        "Stop Loss",
                        f"{state.side.upper()} position stopped by global risk at {live_price}",
                    )
                    _notify_setup_state_event(
                        state,
                        title="⛔ STOP LOSS ATINGIDO ⛔",
                        live_price=live_price,
                        reason="stop global disparado",
                    )
                continue
            exit_signal = evaluate_setup_exit(state, df, live_price=live_price, setup_context=setup_context)
            if exit_signal is not None:
                logger.info(
                    "setup-live exit | %s %s | reason=%s | live=%.4f",
                    state.setup_key,
                    state.symbol,
                    exit_signal.reason,
                    live_price,
                )
                if dry_run:
                    if exit_signal.action == "partial_exit":
                        previous_targets_hit = state.targets_hit
                        state.targets_hit += int(exit_signal.metadata.get("targets_advanced") or 1)
                        _append_setup_event(
                            state,
                            "Target Hit",
                            f"{state.side.upper()} simulated position reached target at {live_price}",
                        )
                        _apply_target_stop_mode(
                            state,
                            previous_targets_hit=previous_targets_hit,
                            targets_hit=state.targets_hit,
                        )
                        _notify_setup_state_event(
                            state,
                            title="🔄 ATUALIZAÇÃO 🔄",
                            live_price=live_price,
                            targets_hit=state.targets_hit,
                            reason=exit_signal.reason,
                            history_title="Histórico de Eventos",
                        )
                        remaining.append(state)
                    else:
                        if _reason_is_stop(exit_signal.reason):
                            title = "⛔ STOP LOSS ATINGIDO ⛔"
                            event_type = "Stop Loss"
                            description = f"{state.side.upper()} simulated position stopped out at {live_price}"
                            targets_hit = state.targets_hit
                        elif "target" in exit_signal.reason.lower() or "profit" in exit_signal.reason.lower() or "atingido" in exit_signal.reason.lower():
                            title = "🔄 ATUALIZAÇÃO 🔄"
                            event_type = "Target Hit"
                            description = f"{state.side.upper()} simulated position reached target at {live_price}"
                            targets_hit = max(state.targets_hit + 1, len(_state_notice_targets(state)) or state.targets_hit + 1)
                        else:
                            title = "🔒 FECHAMENTO MANUAL 🔒"
                            event_type = "Manual Close"
                            description = f"{state.side.upper()} simulated position closed at {live_price}"
                            targets_hit = state.targets_hit
                        _append_setup_event(state, event_type, description)
                        _notify_setup_state_event(
                            state,
                            title=title,
                            live_price=live_price,
                            targets_hit=targets_hit,
                            reason=exit_signal.reason,
                        )
                elif exit_signal.action == "partial_exit":
                    sync_result = _reconcile_native_fills_before_partial(eng, state)
                    if not sync_result.get("has_executable_qty"):
                        logger.info("setup-live parcial ignorada | %s %s | sem qty executavel apos reconciliacao nativa", state.setup_key, state.symbol)
                        if is_hedged_state:
                            remaining.append(state)
                        continue
                    if is_hedged_state:
                        nado_qty = max(
                            float(exit_signal.metadata.get("nado_qty") or 0.0) - _reconciled_closed_qty(sync_result, "nado"),
                            0.0,
                        )
                        kraken_qty = max(
                            float(exit_signal.metadata.get("kraken_qty") or 0.0) - _reconciled_closed_qty(sync_result, "kraken"),
                            0.0,
                        )
                        if nado_qty <= 0 and kraken_qty <= 0:
                            updated_state = state.pair_state
                        elif nado_qty <= 0 or kraken_qty <= 0:
                            logger.warning(
                                "setup-live parcial hedged incompleta apos fill nativo | %s %s | nado=%.8g kraken=%.8g",
                                state.setup_key,
                                state.symbol,
                                nado_qty,
                                kraken_qty,
                            )
                            remaining.append(state)
                            continue
                        else:
                            updated_state = eng.partial_unwind_quantities(
                                state.pair_state,
                                nado_qty=nado_qty,
                                kraken_qty=kraken_qty,
                            )
                            if updated_state is None:
                                continue
                        state.pair_state = updated_state
                    else:
                        role = "nado" if state.effective_venue == "nado" else "kraken"
                        if not _partial_close_solo_setup(
                            eng,
                            state,
                            exit_signal,
                            reconciled_closed_qty=_reconciled_closed_qty(sync_result, role),
                        ):
                            remaining.append(state)
                            continue
                        _apply_solo_partial_close_to_state(state, exit_signal)
                    previous_targets_hit = state.targets_hit
                    state.targets_hit += int(exit_signal.metadata.get("targets_advanced") or 1)
                    _append_setup_event(
                        state,
                        "Target Hit",
                        f"{state.side.upper()} position reached target at {live_price}",
                    )
                    _apply_target_stop_mode(
                        state,
                        previous_targets_hit=previous_targets_hit,
                        targets_hit=state.targets_hit,
                        eng=eng,
                    )
                    _notify_setup_state_event(
                        state,
                        title="🔄 ATUALIZAÇÃO 🔄",
                        live_price=live_price,
                        targets_hit=state.targets_hit,
                        reason=exit_signal.reason,
                        history_title="Histórico de Eventos",
                    )
                    remaining.append(state)
                else:
                    if is_hedged_state:
                        eng.unwind(state.pair_state)
                    else:
                        _close_solo_setup(eng, state)
                    if _reason_is_stop(exit_signal.reason):
                        title = "⛔ STOP LOSS ATINGIDO ⛔"
                        event_type = "Stop Loss"
                        description = f"{state.side.upper()} position stopped out at {live_price}"
                        targets_hit = state.targets_hit
                    elif "target" in exit_signal.reason.lower() or "profit" in exit_signal.reason.lower() or "atingido" in exit_signal.reason.lower():
                        title = "🔄 ATUALIZAÇÃO 🔄"
                        event_type = "Target Hit"
                        description = f"{state.side.upper()} position reached target at {live_price}"
                        targets_hit = max(state.targets_hit + 1, len(_state_notice_targets(state)) or state.targets_hit + 1)
                    else:
                        title = "🔒 FECHAMENTO MANUAL 🔒"
                        event_type = "Manual Close"
                        description = f"{state.side.upper()} position manually closed at {live_price}"
                        targets_hit = state.targets_hit
                    _append_setup_event(state, event_type, description)
                    _notify_setup_state_event(
                        state,
                        title=title,
                        live_price=live_price,
                        targets_hit=targets_hit,
                        reason=exit_signal.reason,
                    )
                continue
            if not dry_run and is_hedged_state:
                eng.rebalance(state.pair_state)
            remaining.append(state)
        except Exception as exc:  # noqa: BLE001
            logger.error("setup-live falhou ao monitorar %s %s: %s", state.setup_key, state.symbol, exc)
            remaining.append(state)
    return remaining


def _open_single_venue_setup(
    eng: DeltaNeutralEngine,
    *,
    plan: SetupOrderPlan,
    signal: object,
    log_prefix: str = "setup-live",
) -> PairState | None:
    is_buy = str(getattr(signal, "side", "") or "") == "long"
    timeframe = SETUP_CATALOG.get(plan.setup_key, SETUP_CATALOG["hybrid"]).timeframe
    leverage = plan.leverage if plan.leverage > 0 else None
    if plan.venue == "nado":
        existing = eng.nado.get_perp_position_size(plan.nado_product_id)
        if abs(existing) > 1e-9:
            logger.warning("%s skip  | %s %s | reason=Nado ja tem posicao aberta", log_prefix, plan.setup_key, plan.symbol)
            return None
        eng.nado.place_market_order(
            product_id=plan.nado_product_id,
            quantity=plan.quantity,
            is_buy=is_buy,
            slippage_bps=eng.slippage_bps,
            margin_mode=plan.margin_mode,
            leverage=leverage,
        )
        time.sleep(1)
        positions = getattr(eng.nado, "get_all_positions", lambda: [])()
        detected_mode = ""
        actual_liquidation_price = 0.0
        for position in positions:
            if getattr(position, "product_id", None) == plan.nado_product_id:
                detected_mode = str(getattr(position, "margin_mode", "") or "").lower()
                actual_liquidation_price = float(getattr(position, "liquidation_price", 0.0) or 0.0)
                break
        if plan.margin_mode == MARGIN_MODE_ISOLATED and not detected_mode:
            _close_solo_setup(
                eng,
                ManagedSetupState(
                    setup_key=plan.setup_key,
                    symbol=plan.symbol,
                    timeframe=timeframe,
                    side=str(getattr(signal, "side", "") or ""),
                    pair_state=PairState(
                        symbol=plan.symbol,
                        nado_product_id=plan.nado_product_id,
                        kraken_symbol=plan.kraken_symbol,
                        nado_side=str(getattr(signal, "side", "") or ""),
                        kraken_side="",
                        requested_notional_usd=plan.requested_notional_usd,
                        effective_notional_usd=plan.effective_notional_usd,
                        nado_qty=plan.quantity,
                        kraken_qty=0.0,
                        nado_entry=plan.entry_price,
                        kraken_entry=0.0,
                    ),
                    effective_venue="nado",
                    margin_mode=plan.margin_mode,
                    leverage=plan.leverage,
                ),
            )
            raise RuntimeError(f"modo {plan.margin_mode} nao confirmado na Nado")
        if plan.margin_mode and detected_mode and detected_mode != plan.margin_mode:
            _close_solo_setup(
                eng,
                ManagedSetupState(
                    setup_key=plan.setup_key,
                    symbol=plan.symbol,
                    timeframe=timeframe,
                    side=str(getattr(signal, "side", "") or ""),
                    pair_state=PairState(
                        symbol=plan.symbol,
                        nado_product_id=plan.nado_product_id,
                        kraken_symbol=plan.kraken_symbol,
                        nado_side=str(getattr(signal, "side", "") or ""),
                        kraken_side="",
                        requested_notional_usd=plan.requested_notional_usd,
                        effective_notional_usd=plan.effective_notional_usd,
                        nado_qty=plan.quantity,
                        kraken_qty=0.0,
                        nado_entry=plan.entry_price,
                        kraken_entry=0.0,
                    ),
                    effective_venue="nado",
                    margin_mode=plan.margin_mode,
                    leverage=plan.leverage,
                ),
            )
            raise RuntimeError(f"modo {plan.margin_mode} nao confirmado na Nado (detectado={detected_mode})")
        actual_buffer_pct = _liquidation_buffer_pct(plan.entry_price, plan.stop_price, actual_liquidation_price)
        logger.info(
            "%s entrada confirmada | %s %s | venue=nado | entry=%.6f | stop=%.6f | liq_corretora=%s | buffer=%.1f%%",
            log_prefix,
            plan.setup_key,
            plan.symbol,
            plan.entry_price,
            plan.stop_price,
            _fmt_liq(actual_liquidation_price),
            actual_buffer_pct,
        )
        _notify_setup_entry(
            plan=plan,
            side=str(getattr(signal, "side", "") or ""),
            venue="nado",
            liquidation_price=actual_liquidation_price,
            liquidation_buffer_pct=actual_buffer_pct,
            signal=signal,
        )
        return PairState(
            symbol=plan.symbol,
            nado_product_id=plan.nado_product_id,
            kraken_symbol=plan.kraken_symbol,
            nado_side=str(getattr(signal, "side", "") or ""),
            kraken_side="",
            requested_notional_usd=plan.requested_notional_usd,
            effective_notional_usd=plan.effective_notional_usd,
            nado_qty=plan.quantity,
            kraken_qty=0.0,
            nado_entry=plan.entry_price,
            kraken_entry=0.0,
            requested_margin_usd=plan.requested_margin_usd,
            sizing_source=plan.sizing_source,
            nado_network=str(getattr(eng.nado, "network", "")),
            nado_subaccount_name=str(getattr(eng.nado, "subaccount_name", "")),
            nado_subaccount_hex=str(getattr(eng.nado, "subaccount_hex", "")),
            nado_owner_address=str(getattr(eng.nado, "owner_address", getattr(eng.nado, "owner", ""))),
            nado_linked_signer_address=str(getattr(eng.nado, "linked_signer_address", "") or ""),
            execution_mode=plan.execution_mode,
            effective_venue="nado",
            nado_requested_leverage=plan.leverage,
            nado_margin_mode=plan.margin_mode,
            nado_liquidation_price=actual_liquidation_price,
            liquidation_buffer_pct=actual_buffer_pct,
        )

    existing_kraken_pos = eng.kraken.get_position(plan.kraken_symbol)
    if abs(existing_kraken_pos.size) > 1e-9:
        logger.warning("%s skip  | %s %s | reason=Kraken ja tem posicao aberta", log_prefix, plan.setup_key, plan.symbol)
        return None
    eng.kraken.configure_futures_risk_context(
        plan.kraken_symbol,
        leverage=leverage,
        margin_mode=plan.margin_mode,
    )
    eng.kraken.place_market_order(
        plan.kraken_symbol,
        plan.quantity,
        is_buy=is_buy,
        margin_mode=plan.margin_mode,
        leverage=leverage,
    )
    time.sleep(1)
    kraken_pos = eng.kraken.get_position(plan.kraken_symbol)
    actual_liquidation_price = float(getattr(kraken_pos, "liquidation_price", 0.0) or 0.0)
    actual_buffer_pct = _liquidation_buffer_pct(plan.entry_price, plan.stop_price, actual_liquidation_price)
    logger.info(
        "%s entrada confirmada | %s %s | venue=kraken | entry=%.6f | stop=%.6f | liq_corretora=%s | buffer=%.1f%%",
        log_prefix,
        plan.setup_key,
        plan.symbol,
        plan.entry_price,
        plan.stop_price,
        _fmt_liq(actual_liquidation_price),
        actual_buffer_pct,
    )
    _notify_setup_entry(
        plan=plan,
        side=str(getattr(signal, "side", "") or ""),
        venue="kraken",
        liquidation_price=actual_liquidation_price,
        liquidation_buffer_pct=actual_buffer_pct,
        signal=signal,
    )
    detected_mode = str(getattr(kraken_pos, "margin_mode", "") or "").lower()
    effective_margin_mode = detected_mode or plan.margin_mode
    if plan.margin_mode and detected_mode and detected_mode != plan.margin_mode:
        logger.warning(
            "%s aviso | %s %s | Kraken confirmou margin=%s embora solicitado=%s; mantendo posicao e registrando modo efetivo",
            log_prefix,
            plan.setup_key,
            plan.symbol,
            detected_mode,
            plan.margin_mode,
        )
    elif plan.margin_mode == MARGIN_MODE_ISOLATED and not detected_mode:
        logger.warning(
            "%s aviso | %s %s | isolated solicitado, mas Kraken nao retornou modo; mantendo posicao",
            log_prefix,
            plan.setup_key,
            plan.symbol,
        )
    return PairState(
        symbol=plan.symbol,
        nado_product_id=plan.nado_product_id,
        kraken_symbol=plan.kraken_symbol,
        nado_side="",
        kraken_side=str(getattr(signal, "side", "") or ""),
        requested_notional_usd=plan.requested_notional_usd,
        effective_notional_usd=plan.effective_notional_usd,
        nado_qty=0.0,
        kraken_qty=plan.quantity,
        nado_entry=0.0,
        kraken_entry=plan.entry_price,
        requested_margin_usd=plan.requested_margin_usd,
        sizing_source=plan.sizing_source,
        kraken_account=str(getattr(eng.kraken, "account", "") or ""),
        kraken_account_symbol=str(getattr(eng.kraken, "account_symbol", "") or ""),
        kraken_api_fingerprint=str(getattr(eng.kraken, "api_fingerprint", "") or ""),
        kraken_subaccount_mode=str(
            getattr(eng.kraken, "get_isolation_context", lambda: {})().get("subaccount_mode", "")
        ),
        execution_mode=plan.execution_mode,
        effective_venue="kraken",
        kraken_requested_leverage=plan.leverage,
        kraken_margin_mode=effective_margin_mode,
        kraken_liquidation_price=actual_liquidation_price,
        liquidation_buffer_pct=actual_buffer_pct,
        kraken_sandbox=getattr(eng.kraken, "sandbox", None),
    )


def _execute_setup_entries(
    eng: DeltaNeutralEngine,
    entries: list[tuple[str, str, pd.DataFrame, object]],
    *,
    dry_run: bool,
    notional_usd: float | None,
    hybrid_profile: str,
    margin_usd: float | None = None,
    nado_margin_usd: float | None = None,
    kraken_margin_usd: float | None = None,
    stop_loss_pct: float = 0.0,
    execution_mode: str = EXECUTION_MODE_HEDGED,
    margin_mode: str = MARGIN_MODE_CROSS,
    nado_margin_mode: str = "",
    kraken_margin_mode: str = "",
    target_stop_mode: str = TARGET_STOP_MODE_OFF,
    current_open_count: int = 0,
    max_open_setups: int = 0,
    setup_priority: list[str] | tuple[str, ...] | None = None,
) -> list[ManagedSetupState]:
    opened_states: list[ManagedSetupState] = []
    entries = _select_cycle_setup_entries(entries, setup_priority=setup_priority)
    for setup_key, symbol, df, signal in entries:
        if max_open_setups > 0 and current_open_count + len(opened_states) >= max_open_setups:
            logger.info(
                "setup-live limite | max_open_setups=%d atingido; novas entradas pausadas",
                max_open_setups,
            )
            break
        use_setup_managed_exit = _setup_uses_managed_targets(setup_key, signal)
        execution_config = get_setup_execution_config(setup_key)
        effective_execution_mode = _execution_mode_for_setup(setup_key, execution_mode)
        leverage = _setup_leverage_for_signal(
            setup_key,
            signal,
            fallback=execution_config.leverage_for_profile(hybrid_profile),
        )
        try:
            notice_entry_price = float(df.iloc[-1]["close"])
        except Exception:  # noqa: BLE001
            notice_entry_price = 0.0
        notice_take_profit_pct = float(getattr(eng, "protective_take_profit_pct", 0.0) or 0.0)
        setup_margin_mode = normalize_margin_mode(margin_mode) or MARGIN_MODE_CROSS
        if is_directional_setup(setup_key) and not effective_execution_mode:
            logger.info(
                "setup-live analise | %s %s | side=%s | falta --execution-mode para simular/executar ordem",
                setup_key,
                symbol,
                signal.side,
            )
            continue
        if effective_execution_mode not in execution_config.allowed_execution_modes:
            logger.warning(
                "setup-live skip  | %s %s | reason=modo %s nao permitido para este setup",
                setup_key,
                symbol,
                effective_execution_mode or "-",
            )
            continue

        order_plan: SetupOrderPlan | None = None
        if effective_execution_mode == EXECUTION_MODE_HEDGED:
            hedged_margin_usd = _resolve_margin_for_execution_mode(
                effective_execution_mode,
                margin_usd,
                nado_margin_usd,
                kraken_margin_usd,
            )
            can_execute, reason = _preflight_symbol_entry(
                eng,
                symbol=symbol,
                requested_notional_usd=notional_usd,
                requested_margin_usd=hedged_margin_usd,
                leverage=leverage,
            )
            if not can_execute:
                logger.warning("setup-live skip  | %s %s | reason=%s", setup_key, symbol, reason)
                continue
        else:
            venue = "nado" if effective_execution_mode == EXECUTION_MODE_NADO_ONLY else "kraken"
            venue_margin_mode = _margin_mode_for_venue(
                venue=venue,
                margin_mode=setup_margin_mode,
                nado_margin_mode=normalize_margin_mode(nado_margin_mode),
                kraken_margin_mode=normalize_margin_mode(kraken_margin_mode),
                config=execution_config,
            )
            order_plan = _build_single_venue_order_plan(
                eng,
                setup_key=setup_key,
                symbol=symbol,
                venue=venue,
                signal=signal,
                notional_usd=notional_usd,
                margin_usd=(
                    nado_margin_usd
                    if venue == "nado" and nado_margin_usd is not None and nado_margin_usd > 0
                    else kraken_margin_usd
                    if venue == "kraken" and kraken_margin_usd is not None and kraken_margin_usd > 0
                    else margin_usd
                ),
                margin_mode=venue_margin_mode,
                leverage=leverage,
                min_liquidation_buffer_pct=execution_config.liquidation_buffer_pct_min,
                stop_loss_pct=stop_loss_pct,
            )
            if not order_plan.can_execute:
                logger.warning("setup-live skip  | %s %s | reason=%s", setup_key, symbol, order_plan.blocked_reason)
                continue
        log_entry_price = float(getattr(signal, "reference_entry_price", 0.0) or notice_entry_price or 0.0)
        log_stop_price = _fallback_notice_stop_price(
            entry_price=log_entry_price,
            side=signal.side,
            stop_loss_pct=stop_loss_pct,
            explicit_stop_price=float(getattr(signal, "stop_price", 0.0) or 0.0),
        )
        log_take_profit = float(getattr(signal, "take_profit", 0.0) or 0.0)
        if log_take_profit <= 0 and log_entry_price > 0:
            log_take_profit = _take_profit_price_from_pct(
                log_entry_price,
                signal.side,
                _notice_take_profit_pct(notice_take_profit_pct),
            )
        log_targets: list[float] = []
        for raw_target in list(getattr(signal, "take_profit_targets", []) or []):
            try:
                target = float(raw_target or 0.0)
            except (TypeError, ValueError):
                continue
            if target > 0:
                log_targets.append(target)
        if not log_targets and log_take_profit > 0:
            log_targets.append(log_take_profit)
        log_targets_csv = ",".join(f"{target:.12g}" for target in log_targets)
        logger.info(
            "setup-live entry | %s %s | side=%s | mode=%s | entry=%.12g | stop=%.12g | tp=%.12g | targets=%s | reason=%s",
            setup_key,
            symbol,
            signal.side,
            effective_execution_mode,
            log_entry_price,
            log_stop_price,
            log_take_profit,
            log_targets_csv,
            signal.reason,
        )
        if effective_execution_mode != EXECUTION_MODE_HEDGED and order_plan is not None:
            logger.info(
                "setup-live plano | %s %s | venue=%s | margin=%s | lev=%.2fx | liq=%s | buffer=%.1f%%",
                setup_key,
                symbol,
                order_plan.venue,
                order_plan.margin_mode,
                order_plan.leverage,
                _fmt_liq(order_plan.liquidation_price),
                order_plan.liquidation_buffer_pct,
            )
        if dry_run:
            notice_result = _notify_setup_opportunity(
                setup_key=setup_key,
                symbol=symbol,
                signal=signal,
                execution_mode=effective_execution_mode,
                leverage=leverage,
                risk_profile=hybrid_profile,
                plan=order_plan,
                fallback_entry_price=notice_entry_price,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=notice_take_profit_pct,
            )
            dry_state = _build_dry_run_setup_state(
                eng,
                setup_key=setup_key,
                symbol=symbol,
                df=df,
                signal=signal,
                execution_mode=effective_execution_mode,
                leverage=leverage,
                hybrid_profile=hybrid_profile,
                plan=order_plan,
                fallback_entry_price=notice_entry_price,
                notional_usd=notional_usd,
                margin_usd=margin_usd,
                nado_margin_usd=nado_margin_usd,
                kraken_margin_usd=kraken_margin_usd,
                margin_mode=setup_margin_mode,
                nado_margin_mode=nado_margin_mode,
                kraken_margin_mode=kraken_margin_mode,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=notice_take_profit_pct,
                target_stop_mode=target_stop_mode,
            )
            if notice_result.get("discord_message_id"):
                dry_state.metadata["discord_entry_message_id"] = notice_result["discord_message_id"]
            if notice_result.get("whatsapp_message_id"):
                dry_state.metadata["whatsapp_entry_message_id"] = notice_result["whatsapp_message_id"]
            opened_states.append(dry_state)
            continue
        notice_result = _notify_setup_opportunity(
            setup_key=setup_key,
            symbol=symbol,
            signal=signal,
            execution_mode=effective_execution_mode,
            leverage=leverage,
            risk_profile=hybrid_profile,
            plan=order_plan,
            fallback_entry_price=notice_entry_price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=notice_take_profit_pct,
        )
        discord_entry_message_id = notice_result.get("discord_message_id", "")
        whatsapp_entry_message_id = notice_result.get("whatsapp_message_id", "")
        if effective_execution_mode == EXECUTION_MODE_HEDGED:
            nado_mode = normalize_margin_mode(nado_margin_mode) or execution_config.nado_margin_mode or MARGIN_MODE_CROSS
            kraken_mode = normalize_margin_mode(kraken_margin_mode) or execution_config.kraken_margin_mode or MARGIN_MODE_CROSS
            open_kwargs = {
                "nado_side": signal.side,
                "notional_usd": _resolve_operational_notional(
                    notional_usd=notional_usd,
                    margin_usd=hedged_margin_usd,
                    leverage=leverage,
                    default_notional_usd=eng.volume_per_leg,
                )[0],
                "attach_default_protective_orders": not use_setup_managed_exit,
                "kraken_leverage": leverage,
                "kraken_margin_mode": kraken_mode,
            }
            open_params = inspect.signature(eng.open_pair).parameters
            if "nado_leverage" in open_params:
                open_kwargs["nado_leverage"] = leverage
            if "nado_margin_mode" in open_params:
                open_kwargs["nado_margin_mode"] = nado_mode
            try:
                pair_state = eng.open_pair(symbol, **open_kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("setup-live skip  | %s %s | reason=%s", setup_key, symbol, exc)
                _notify_setup_cancelled(
                    setup_key=setup_key,
                    symbol=symbol,
                    signal=signal,
                    execution_mode=effective_execution_mode,
                    leverage=leverage,
                    risk_profile=hybrid_profile,
                    reason=str(exc),
                    plan=order_plan,
                    fallback_entry_price=notice_entry_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=notice_take_profit_pct,
                )
                continue
        else:
            try:
                pair_state = _open_single_venue_setup(eng, plan=order_plan, signal=signal) if order_plan is not None else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("setup-live skip  | %s %s | reason=%s", setup_key, symbol, exc)
                _notify_setup_cancelled(
                    setup_key=setup_key,
                    symbol=symbol,
                    signal=signal,
                    execution_mode=effective_execution_mode,
                    leverage=leverage,
                    risk_profile=hybrid_profile,
                    reason=str(exc),
                    plan=order_plan,
                    fallback_entry_price=notice_entry_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=notice_take_profit_pct,
                )
                continue
        if pair_state is None:
            _notify_setup_cancelled(
                setup_key=setup_key,
                symbol=symbol,
                signal=signal,
                execution_mode=effective_execution_mode,
                leverage=leverage,
                risk_profile=hybrid_profile,
                reason="ordem nao retornou estado de posicao",
                plan=order_plan,
                fallback_entry_price=notice_entry_price,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=notice_take_profit_pct,
            )
            continue
        reference_entry_price = float(getattr(signal, "reference_entry_price", 0.0) or 0.0)
        state_entry_price = (
            float(pair_state.kraken_entry)
            if pair_state.effective_venue in {"hedged", "kraken"}
            else float(pair_state.nado_entry)
        )
        actual_stop_price = _rebase_reference_price(
            float(getattr(signal, "stop_price", 0.0) or 0.0),
            from_entry=reference_entry_price,
            to_entry=state_entry_price,
        )
        if stop_loss_pct > 0:
            actual_stop_price = _stop_price_from_pct(state_entry_price, signal.side, stop_loss_pct)
        actual_take_profit = _rebase_reference_price(
            float(getattr(signal, "take_profit", 0.0) or 0.0),
            from_entry=reference_entry_price,
            to_entry=state_entry_price,
        )
        notice_stop_price = _fallback_notice_stop_price(
            entry_price=state_entry_price,
            side=signal.side,
            explicit_stop_price=actual_stop_price or float(getattr(signal, "stop_price", 0.0) or 0.0),
            stop_loss_pct=stop_loss_pct,
        )
        notice_take_profit = actual_take_profit or _take_profit_price_from_pct(
            state_entry_price,
            signal.side,
            _notice_take_profit_pct(notice_take_profit_pct),
        )
        if effective_execution_mode == EXECUTION_MODE_HEDGED:
            confirmed_notice_result = _notify_setup_entry(
                plan=SetupOrderPlan(
                    setup_key=setup_key,
                    symbol=symbol,
                    execution_mode=pair_state.execution_mode,
                    venue="hedged",
                    margin_mode=pair_state.nado_margin_mode or pair_state.kraken_margin_mode,
                    leverage=pair_state.nado_requested_leverage or pair_state.kraken_requested_leverage,
                    requested_notional_usd=pair_state.requested_notional_usd,
                    effective_notional_usd=pair_state.effective_notional_usd,
                    requested_margin_usd=pair_state.requested_margin_usd,
                    sizing_source=pair_state.sizing_source,
                    quantity=min(abs(float(pair_state.nado_qty or 0.0)), abs(float(pair_state.kraken_qty or 0.0))),
                    entry_price=state_entry_price,
                    stop_price=notice_stop_price,
                    take_profit=notice_take_profit,
                    liquidation_price=pair_state.nado_liquidation_price or pair_state.kraken_liquidation_price,
                    liquidation_buffer_pct=pair_state.liquidation_buffer_pct,
                    can_execute=True,
                    nado_product_id=pair_state.nado_product_id,
                    kraken_symbol=pair_state.kraken_symbol,
                ),
                side=str(getattr(signal, "side", "") or ""),
                venue="hedged",
                liquidation_price=pair_state.nado_liquidation_price or pair_state.kraken_liquidation_price,
                liquidation_buffer_pct=pair_state.liquidation_buffer_pct,
                signal=signal,
                risk_profile=hybrid_profile,
            )
            if confirmed_notice_result.get("discord_message_id"):
                discord_entry_message_id = confirmed_notice_result["discord_message_id"]
            if confirmed_notice_result.get("whatsapp_message_id"):
                whatsapp_entry_message_id = confirmed_notice_result["whatsapp_message_id"]
        target_levels: list[dict] = []
        if use_setup_managed_exit:
            target_levels = _build_target_levels(
                eng,
                pair_state,
                reference_entry_price=reference_entry_price,
                signal_targets=list(getattr(signal, "take_profit_targets", []) or []),
                target_weights=list(getattr(signal, "target_weights", []) or []),
                effective_venue=pair_state.effective_venue,
            )
        metadata = dict(getattr(signal, "metadata", {}) or {})
        opened_ts = time.time()
        metadata.update(
            {
                "execution_mode": pair_state.execution_mode,
                "effective_venue": pair_state.effective_venue,
                "margin_mode": pair_state.nado_margin_mode or pair_state.kraken_margin_mode,
                "leverage": pair_state.nado_requested_leverage or pair_state.kraken_requested_leverage,
                "liquidation_price": pair_state.nado_liquidation_price or pair_state.kraken_liquidation_price,
                "liquidation_buffer_pct": pair_state.liquidation_buffer_pct,
                "requested_margin_usd": pair_state.requested_margin_usd,
                "sizing_source": pair_state.sizing_source,
                "stop_loss_pct": stop_loss_pct,
                "target_stop_mode": target_stop_mode,
                "target_stop_native_replacement": "managed_loop",
                "events": [
                    {"ts": opened_ts, "type": "New", "description": "new position"},
                    {
                        "ts": opened_ts,
                        "type": "Entry",
                        "description": f"{str(signal.side).upper()} position opened at {state_entry_price}",
                    },
                ],
            }
        )
        if target_levels:
            metadata["target_levels"] = target_levels
        if discord_entry_message_id:
            metadata["discord_entry_message_id"] = discord_entry_message_id
        if whatsapp_entry_message_id:
            metadata["whatsapp_entry_message_id"] = whatsapp_entry_message_id
        if pair_state.effective_venue == "nado":
            metadata["initial_position_qty"] = abs(float(pair_state.nado_qty or 0.0))
        elif pair_state.effective_venue == "kraken":
            metadata["initial_position_qty"] = abs(float(pair_state.kraken_qty or 0.0))
        else:
            metadata["initial_position_qty"] = min(abs(float(pair_state.nado_qty or 0.0)), abs(float(pair_state.kraken_qty or 0.0)))
        opened_state = ManagedSetupState(
            setup_key=setup_key,
            symbol=symbol,
            timeframe=signal.timeframe,
            side=signal.side,
            pair_state=pair_state,
            hybrid_profile=hybrid_profile if setup_key in {"hybrid", "hybrid-15m"} else "",
            reference_entry_price=state_entry_price if use_setup_managed_exit else 0.0,
            stop_price=(actual_stop_price or float(getattr(signal, "stop_price", 0.0) or 0.0)) if use_setup_managed_exit else 0.0,
            take_profit=(actual_take_profit or float(getattr(signal, "take_profit", 0.0) or 0.0)) if use_setup_managed_exit else 0.0,
            close_after_bars=signal.close_after_bars,
            entry_reason=signal.reason,
            execution_mode=pair_state.execution_mode,
            effective_venue=pair_state.effective_venue,
            margin_mode=pair_state.nado_margin_mode or pair_state.kraken_margin_mode,
            leverage=pair_state.nado_requested_leverage or pair_state.kraken_requested_leverage,
            liquidation_price=pair_state.nado_liquidation_price or pair_state.kraken_liquidation_price,
            liquidation_buffer_pct=pair_state.liquidation_buffer_pct,
            opened_bar_at=str(df.iloc[-1]["timestamp"].isoformat()),
            opened_at_ts=opened_ts,
            metadata=metadata,
        )
        if opened_state.effective_venue in {"nado", "kraken"} and use_setup_managed_exit:
            attached = _attach_solo_protective_orders(eng, opened_state, target_levels=target_levels)
            opened_state.metadata["protective_orders_attached"] = attached
            if not attached:
                logger.warning("setup-live protecao | %s %s abriu, mas nem todos SL/TP foram anexados", setup_key, symbol)
        opened_states.append(opened_state)
    return opened_states


def cmd_setup_live_status(_: argparse.Namespace) -> None:
    states = load_setup_live_states()
    _log_setup_live_status(states)


def _notify_monitored_setup_states(
    eng: DeltaNeutralEngine,
    states: list[ManagedSetupState],
    *,
    force: bool = False,
) -> int:
    if not _setup_notifications_enabled():
        logger.info("setup-live notificacao monitoradas ignorada: notificacoes desativadas")
        return 0
    sent = 0
    for state in states:
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        state.metadata = metadata
        if not force and metadata.get("monitored_notice_sent_at"):
            continue
        try:
            live_price = _setup_reference_price(eng, state)
        except Exception:  # noqa: BLE001
            live_price = _state_entry_price(state)
        _notify_setup_state_event(
            state,
            title="📡 OPERAÇÃO MONITORADA 📡",
            live_price=live_price,
            reason="operação já está em monitoramento",
            history_title="Histórico de Eventos",
        )
        metadata["monitored_notice_sent_at"] = time.time()
        sent += 1
    logger.info("setup-live notificacao monitoradas | enviadas=%d | total=%d", sent, len(states))
    return sent


def cmd_setup_live_notify_monitored(args: argparse.Namespace) -> None:
    _configure_entry_notifications_from_args(args)
    states = load_setup_live_states()
    if not states:
        logger.info("setup-live monitoradas: nenhum estado gerenciado")
        return
    eng = build_engine()
    _log_active_trade_context(eng)
    _notify_monitored_setup_states(eng, states, force=bool(getattr(args, "force", False)))
    save_setup_live_states(states, base_states=states)


def cmd_setup_live(args: argparse.Namespace) -> None:
    # Antes do loop: dentro dele, `_scan_setup_entries` captura `Exception`,
    # loga warning e faz `break` -- um valor invalido no settings deixaria o
    # bot de pe, sem abrir nada e sem falhar.
    validate_setup_settings()
    _configure_entry_notifications_from_args(args)
    setup_keys = parse_setup_selection(args.setup)
    hybrid_profile = normalize_hybrid_profile(getattr(args, "risk_profile", None) or args.hybrid_profile)
    profile_leverage = _risk_profile_leverage(hybrid_profile)
    margin_usd = _load_optional_float_arg(getattr(args, "margin_usd", None), "MARGIN_USD", "DEFAULT_MARGIN_USD")
    nado_margin_usd = _load_optional_float_arg(
        getattr(args, "nado_margin_usd", None),
        "NADO_MARGIN_USD",
        "DEFAULT_NADO_MARGIN_USD",
        "DEX_MARGIN_USD",
    )
    kraken_margin_usd = _load_optional_float_arg(
        getattr(args, "kraken_margin_usd", None),
        "KRAKEN_MARGIN_USD",
        "DEFAULT_KRAKEN_MARGIN_USD",
        "CEX_MARGIN_USD",
    )
    stop_loss_pct = _resolve_stop_loss_pct(getattr(args, "stop_loss_pct", None), getattr(args, "stop_loss_preset", None))
    requested_execution_mode = (
        _normalize_execution_mode_arg(getattr(args, "execution_mode", None))
        or _default_execution_mode_from_env()
    )
    requested_margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "margin_mode", None))
        or _default_margin_mode_from_env()
    )
    requested_nado_margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "nado_margin_mode", None))
        or _default_nado_margin_mode_from_env()
    )
    requested_kraken_margin_mode = (
        _normalize_margin_mode_arg(getattr(args, "kraken_margin_mode", None))
        or _default_kraken_margin_mode_from_env()
    )
    has_directional = any(is_directional_setup(setup_key) for setup_key in setup_keys)
    has_hedged_only = any(is_hedged_only_setup(setup_key) for setup_key in setup_keys)
    provisional_execution_mode = requested_execution_mode or (EXECUTION_MODE_HEDGED if has_hedged_only else None)
    needs_nado = provisional_execution_mode in {EXECUTION_MODE_HEDGED, EXECUTION_MODE_NADO_ONLY}
    # Dry-run directional sem execution-mode é análise de sinal; usa Kraken para candles e não exige Nado.
    if args.dry_run and has_directional and not requested_execution_mode and not has_hedged_only:
        needs_nado = False
    needs_kraken = provisional_execution_mode in {None, EXECUTION_MODE_HEDGED, EXECUTION_MODE_KRAKEN_ONLY}
    # Dry-run CEX-only via CCXT publica/monitora sinais sem abrir ordem real.
    # Nesse modo as credenciais privadas da CEX não são necessárias: usamos apenas
    # dados públicos de mercado para montar plano, notificação e estado monitorado.
    if args.dry_run and requested_execution_mode == EXECUTION_MODE_KRAKEN_ONLY:
        needs_kraken = False
    eng = build_engine(require_nado=needs_nado, require_kraken=needs_kraken)
    _log_active_trade_context(eng)
    symbols = _resolve_setup_live_symbols(
        eng,
        args.symbol,
        setup_keys,
        execution_mode=requested_execution_mode or EXECUTION_MODE_HEDGED,
    )
    max_open_setups = int(getattr(args, "max_open_setups", None) or _load_int_env("SETUP_LIVE_MAX_OPEN_SETUPS", 0))
    try:
        target_stop_mode = _normalize_target_stop_mode(
            getattr(args, "target_stop_mode", None) or os.environ.get("SETUP_LIVE_TARGET_STOP_MODE", TARGET_STOP_MODE_OFF)
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    logger.info("setup-live modo-stop-alvo=%s", target_stop_mode)
    account_margin_reserve_usd = _load_optional_float_arg(
        getattr(args, "account_margin_reserve_usd", None),
        "SETUP_ACCOUNT_MARGIN_RESERVE_USD",
    ) or 0.0
    account_margin_reserve_pct = _load_optional_float_arg(
        getattr(args, "account_margin_reserve_pct", None),
        "SETUP_ACCOUNT_MARGIN_RESERVE_PCT",
    ) or 0.0
    account_margin_slots = int(
        getattr(args, "account_margin_slots", None)
        or _load_int_env("SETUP_ACCOUNT_MARGIN_SLOTS", 0)
    )
    account_max_maint_usage_pct = _load_optional_float_arg(
        getattr(args, "account_max_maint_usage_pct", None),
        "SETUP_ACCOUNT_MAX_MAINT_USAGE_PCT",
    ) or 0.0
    account_stress_pct = _load_optional_float_arg(
        getattr(args, "account_stress_pct", None),
        "SETUP_ACCOUNT_STRESS_PCT",
    ) or 0.0
    if has_directional and not args.dry_run and not requested_execution_mode:
        raise SystemExit("setup-live real com setup direcional exige --execution-mode hedged|dex_only|cex_only")
    if has_hedged_only and requested_execution_mode in {EXECUTION_MODE_NADO_ONLY, EXECUTION_MODE_KRAKEN_ONLY}:
        blocked = [setup_key for setup_key in setup_keys if is_hedged_only_setup(setup_key)]
        logger.warning(
            "setup-live: ignorando setups exclusivamente hedgeados com modo %s: %s",
            requested_execution_mode,
            ",".join(blocked),
        )
        setup_keys = [setup_key for setup_key in setup_keys if not is_hedged_only_setup(setup_key)]
        if not setup_keys:
            raise SystemExit("nenhum setup restante aceita o execution-mode solicitado")
    readiness_execution_mode = requested_execution_mode or EXECUTION_MODE_HEDGED
    analysis_only_dry_run = args.dry_run and has_directional and not requested_execution_mode
    iteration = 0

    try:
        while True:
            iteration += 1
            logger.info(
                "setup-live iteracao=%d | setups=%s | symbols=%s | dry_run=%s",
                iteration,
                ",".join(setup_keys),
                ",".join(symbols),
                _bool_pt(args.dry_run),
            )
            if args.dry_run:
                logger.warning(
                    "setup-live dry-run: ciclo apenas analisa/simula; nao fecha posicoes reais nem executa TP/SL gerenciado",
                )
            if args.dry_run and has_directional and not requested_execution_mode:
                logger.info("setup-live dry-run: setups direcionais em analise; informe --execution-mode para simular plano de ordem")
            managed_states = load_setup_live_states()
            base_managed_states = list(managed_states)
            managed_states = _process_setup_live_states(eng, managed_states, dry_run=args.dry_run)
            if max_open_setups > 0 and len(managed_states) < len(base_managed_states):
                logger.info(
                    "setup-live slots liberados | antes=%d | agora=%d | limite=%d | novas entradas podem ser avaliadas nesta mesma iteracao",
                    len(base_managed_states),
                    len(managed_states),
                    max_open_setups,
                )
            if iteration == 1 and (
                bool(getattr(args, "notify_monitored_on_start", False))
                or _load_bool_env("SETUP_NOTIFY_MONITORED_ON_START", False)
            ):
                _notify_monitored_setup_states(
                    eng,
                    managed_states,
                    force=bool(getattr(args, "notify_monitored_force", False))
                    or _load_bool_env("SETUP_NOTIFY_MONITORED_FORCE", False),
                )
            save_setup_live_states(managed_states, base_states=base_managed_states)

            readiness = _assess_setup_entry_readiness(
                eng,
                managed_states=managed_states,
                requested_notional_usd=args.notional,
                requested_margin_usd=margin_usd,
                nado_margin_usd=nado_margin_usd,
                kraken_margin_usd=kraken_margin_usd,
                leverage=profile_leverage,
                execution_mode=readiness_execution_mode,
                max_open_setups=max_open_setups,
                account_margin_reserve_usd=account_margin_reserve_usd,
                account_margin_reserve_pct=account_margin_reserve_pct,
                account_margin_slots=account_margin_slots,
                account_max_maint_usage_pct=account_max_maint_usage_pct,
                account_stress_pct=account_stress_pct,
            )
            if args.dry_run and requested_execution_mode == EXECUTION_MODE_KRAKEN_ONLY:
                readiness["can_open"] = True
                readiness["blockers"] = []
                readiness.setdefault("warnings", []).append(
                    "dry-run CEX-only: readiness privada ignorada; somente sinal/estado monitorado, sem ordem real"
                )
            _log_setup_entry_readiness(readiness)

            if not readiness["can_open"] and not analysis_only_dry_run:
                _log_setup_live_status(managed_states)
                if args.max_iter is not None and iteration >= args.max_iter:
                    return
                time.sleep(args.interval)
                continue

            effective_margin_usd = margin_usd
            if (
                float(effective_margin_usd or 0.0) <= 0
                and float(nado_margin_usd or 0.0) <= 0
                and float(kraken_margin_usd or 0.0) <= 0
                and float(readiness.get("account_margin_per_slot_usd") or 0.0) > 0
            ):
                effective_margin_usd = float(readiness.get("account_margin_per_slot_usd") or 0.0)

            entries = _scan_setup_entries(
                eng,
                setup_keys=setup_keys,
                symbols=symbols,
                hybrid_profile=hybrid_profile,
            )
            opened_states = _execute_setup_entries(
                eng,
                entries,
                dry_run=args.dry_run,
                notional_usd=args.notional,
                hybrid_profile=hybrid_profile,
                margin_usd=effective_margin_usd,
                nado_margin_usd=nado_margin_usd,
                kraken_margin_usd=kraken_margin_usd,
                stop_loss_pct=stop_loss_pct,
                execution_mode=requested_execution_mode,
                margin_mode=requested_margin_mode,
                nado_margin_mode=requested_nado_margin_mode,
                kraken_margin_mode=requested_kraken_margin_mode,
                target_stop_mode=target_stop_mode,
                current_open_count=len(managed_states),
                max_open_setups=max_open_setups,
                setup_priority=setup_keys,
            )
            if opened_states:
                base_before_open = list(managed_states)
                managed_states.extend(opened_states)
                save_setup_live_states(managed_states, base_states=base_before_open)
            _log_setup_live_status(managed_states)

            if args.max_iter is not None and iteration >= args.max_iter:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("setup-live interrompido pelo usuario")


def cmd_rebalance(_: argparse.Namespace) -> None:
    state = load_state()
    if state is None:
        logger.info("(sem par aberto)")
        return
    eng = build_engine()
    _log_active_trade_context(eng)
    eng.rebalance(state)


def cmd_unwind(_: argparse.Namespace) -> None:
    state = load_state()
    if state is None:
        logger.info("(sem par aberto)")
        return
    eng = build_engine()
    _log_active_trade_context(eng)
    eng.unwind(state)
    save_state(None)
    logger.info("estado limpo")


def cmd_farm(args: argparse.Namespace) -> None:
    state = load_state()
    if state is None:
        raise SystemExit("abra um par primeiro com `open`")
    eng = build_engine()
    _log_active_trade_context(eng)
    eng.farm_loop(state, check_interval_secs=args.interval, max_iterations=args.max_iter)


def cmd_funding(_: argparse.Namespace) -> None:
    eng = build_engine()
    logger.info("Funding rates nos simbolos comuns:")
    for sym in eng.common_symbols():
        kraken_symbol = eng._kraken_symbol_map[sym]
        rate = eng.kraken.get_funding_rate(kraken_symbol)
        logger.info("  %s  kraken=%s", sym, _fmt_percent(rate))


def cmd_kraken_accounts(_: argparse.Namespace) -> None:
    eng = build_engine()
    overview = eng.kraken.get_accounts_overview()
    selected = overview["selected"]
    safety = overview.get("trading_safety") or eng.kraken.get_trading_safety()
    logger.info(
        "Kraken account context: account=%s symbol=%s params=%s api=%s trading=%s",
        selected["account"],
        selected["account_symbol"] or "-",
        selected["balance_params"],
        selected.get("api_fingerprint") or "-",
        safety.get("label", "desconhecido"),
    )
    if safety.get("reason"):
        logger.info("  trading_reason=%s", safety["reason"])
    for account in overview["accounts"]:
        if account["type"] == "multiCollateralMarginAccount":
            logger.info(
                "  %s | %s | portfolio=%.4f | available_margin=%.4f | currencies=%s",
                account["name"],
                account["type"],
                account["portfolio_value"],
                account["available_margin"],
                ",".join(account["currencies"]),
            )
        elif account["type"] == "cashAccount":
            logger.info(
                "  %s | %s | balances=%s",
                account["name"],
                account["type"],
                account["balances"],
            )
        else:
            logger.info(
                "  %s | %s | currency=%s | portfolio=%.4f | available_funds=%.4f",
                account["name"],
                account["type"],
                account["currency"],
                account["portfolio_value"],
                account["available_funds"],
            )


def cmd_opportunistic(args: argparse.Namespace) -> None:
    eng = build_engine()
    _log_active_trade_context(eng)
    eng.kraken.validate_entry_subaccount_rule(
        require_subaccount=getattr(eng, "kraken_require_subaccount", False),
        declared_is_subaccount=getattr(eng, "kraken_api_is_subaccount", False),
    )
    from workspace.nado.decision import CryptoDecisionEngine  # lazy import

    symbols = eng.common_symbols()
    if not symbols:
        logger.error("sem simbolos em comum entre Nado e Kraken")
        return

    config = {
        "CERTAINTY": _load_certainty_env(),
        "VOLUME_ORDER": eng.volume_per_leg,
        "MAX_PERCENT_LOSS": os.environ.get("MAX_PERCENT_LOSS", "1%"),
        "MAX_PERCENT_PROFIT": os.environ.get("MAX_PERCENT_PROFIT", "2%"),
        "UNIQUE_TREND": _load_unique_trend_env(),
        "MAX_OPPORTUNITIES": _load_int_env("MAX_OPPORTUNITIES", 3),
        "EXCHANGES": [x.strip() for x in os.environ.get("EXCHANGES", "binance").split(",") if x.strip()],
        "SYMBOLS": symbols,
    }
    decision_engine = CryptoDecisionEngine(config)
    opportunities = decision_engine.evaluate_all_pairs()
    if not opportunities:
        logger.info("nenhuma oportunidade acima do threshold")
        return

    top = opportunities[0]
    logger.info(
        "melhor oportunidade: %s %s (certainty=%s%%)",
        top.symbol,
        top.side,
        top.certainty,
    )
    if args.dry_run:
        logger.info("--dry-run: nada executado")
        return

    state = eng.open_pair(top.symbol, nado_side=top.side, notional_usd=eng.volume_per_leg)
    if state:
        save_state(state)


def cmd_simulate(args: argparse.Namespace) -> None:
    eng = build_engine()
    symbols = _resolve_symbols(eng, args.symbol)
    profiles = parse_profiles(args.profiles)

    for symbol in symbols:
        context = _collect_simulation_context(eng, symbol)
        logger.info(
            "SIMULATE %s | setup=%s | kraken=%s | funding=%s | self_fill=%s",
            symbol,
            args.setup,
            context["kraken_symbol"],
            _fmt_percent(context["funding_rate"]),
            _bool_pt(context["has_self_fill_risk"]),
        )
        if context["context_note"]:
            logger.warning("  %s", context["context_note"])
        for profile in profiles:
            rows = build_scenario_matrix(
                setup=args.setup,
                profile=profile,
                funding_rate=context["funding_rate"],
                has_self_fill_risk=context["has_self_fill_risk"],
                drift_bps=eng.drift_bps,
                max_pair_loss_pct=eng.max_pair_loss_pct,
            )
            summary = summarize_simulation(
                symbol=symbol,
                setup=args.setup,
                profile=profile,
                rows=rows,
            )
            logger.info(
                "  perfil=%s | cenario=%s | risco=%s | acao=%s | ordem_real=%s | fluxo=%s | label=%s",
                summary.profile,
                summary.scenario,
                summary.risco,
                summary.acao_esperada,
                _bool_pt(summary.ordem_real_permitida),
                summary.fluxo,
                summary.response_label,
            )


def cmd_scenario_matrix(args: argparse.Namespace) -> None:
    eng = build_engine()
    symbols = _resolve_symbols(eng, args.symbol)
    profiles = parse_profiles(None)

    for symbol in symbols:
        context = _collect_simulation_context(eng, symbol)
        logger.info(
            "SCENARIO MATRIX %s | setup=%s | kraken=%s | funding=%s | self_fill=%s",
            symbol,
            args.setup,
            context["kraken_symbol"],
            _fmt_percent(context["funding_rate"]),
            _bool_pt(context["has_self_fill_risk"]),
        )
        if context["context_note"]:
            logger.warning("  %s", context["context_note"])
        for profile in profiles:
            logger.info("  perfil=%s", profile.name)
            rows = build_scenario_matrix(
                setup=args.setup,
                profile=profile,
                funding_rate=context["funding_rate"],
                has_self_fill_risk=context["has_self_fill_risk"],
                drift_bps=eng.drift_bps,
                max_pair_loss_pct=eng.max_pair_loss_pct,
            )
            for row in rows:
                _log_matrix_row("   ", row)


LIVE_TRADE_COMMANDS = {
    "open",
    "abrir",
    "open-venue-pair",
    "abrir-par-delta-neutro",
    "close-venue-pair",
    "fechar-par-delta-neutro",
    "rebalance",
    "unwind",
    "farm",
    "opportunistic",
    "setup-live",
    "rodar-setups-live",
    "live-hedge",
    "live-sync",
}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "sim"}


def _require_live_confirmation(args: argparse.Namespace) -> None:
    cmd = getattr(args, "cmd", "")
    if cmd not in LIVE_TRADE_COMMANDS:
        return
    if getattr(args, "dry_run", False):
        return
    if _live_trade_confirmed():
        return
    raise SystemExit(
        f"comando de trade bloqueado: defina {FRIENDLY_LIVE_CONFIRM_ENV}=sim apenas na execucao real aprovada "
        f"(tambem aceito: {LIVE_CONFIRM_ENV}=true; alias legado: {LEGACY_LIVE_CONFIRM_ENV}=true)"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog=SKILL_ID)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("venues", help="Mostra DEX/CEX selecionadas e envs esperadas").set_defaults(fn=cmd_venues)
    sub.add_parser("symbols", help="Lista simbolos em ambas exchanges").set_defaults(fn=cmd_symbols)
    parser_asset_scan = sub.add_parser("asset-scan", help="Compara ativos/perps Nado/Kraken e detecta atualizacoes")
    parser_asset_scan.add_argument("--spread-limit-pct", type=float, default=5.0, help="spread maximo Nado/Kraken para considerar saudavel")
    parser_asset_scan.add_argument("--max-suspect", type=int, default=20, help="limite de suspeitos exibidos no log")
    parser_asset_scan.add_argument("--no-write", action="store_true", help="nao salva snapshot em state/asset_scan_state.json")
    parser_asset_scan.set_defaults(fn=cmd_asset_scan)
    sub.add_parser("setups", help="Lista os setups operacionais disponiveis").set_defaults(fn=cmd_setups)

    parser_backtest = sub.add_parser("backtest-operational", help="Roda validacao operacional dos setups")
    parser_backtest.add_argument("--setup", default="all", help="all ou lista separada por virgula")
    parser_backtest.add_argument("--days", type=int, default=90, help="dias de dados sinteticos")
    parser_backtest.add_argument(
        "--timeframe",
        default=None,
        help="timeframe sintetico (15m, 1h ou 4h). Quando omitido, cada setup usa o timeframe padrao",
    )
    parser_backtest.add_argument(
        "--hybrid-profile",
        default=DEFAULT_HYBRID_PROFILE,
        help="perfil de risco do HYBRID: conservador/conservative, moderado/moderate, degen",
    )
    parser_backtest.add_argument("--initial-price", type=float, default=45000.0, dest="initial_price")
    parser_backtest.add_argument("--seed", type=int, default=42)
    parser_backtest.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_backtest.set_defaults(fn=cmd_backtest_operational)

    parser_hybrid_real = sub.add_parser(
        "backtest-hybrid-real",
        help="Valida o setup HYBRID com candles reais via CCXT",
    )
    parser_hybrid_real.add_argument(
        "--symbols",
        default=",".join(DEFAULT_HYBRID_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT)",
    )
    parser_hybrid_real.add_argument("--days", type=int, default=30, help="janela historica em dias")
    parser_hybrid_real.add_argument("--exchange", default="binance", help="exchange CCXT (default: binance)")
    parser_hybrid_real.add_argument(
        "--profile",
        default=DEFAULT_HYBRID_PROFILE,
        help="perfil de risco do HYBRID: conservador/conservative, moderado/moderate, degen",
    )
    parser_hybrid_real.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_hybrid_real.set_defaults(fn=cmd_backtest_hybrid_real)

    parser_divergence_volume_real = sub.add_parser(
        "backtest-divergence-volume-real",
        help="Valida o setup Divergence and Volume com candles reais 4h via CCXT",
    )
    parser_divergence_volume_real.add_argument(
        "--symbols",
        default=",".join(DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT)",
    )
    parser_divergence_volume_real.add_argument("--days", type=int, default=DEFAULT_DIVERGENCE_AND_VOLUME_REAL_DAYS, help="janela historica em dias")
    parser_divergence_volume_real.add_argument("--exchange", default="binance", help="exchange CCXT (default: binance)")
    parser_divergence_volume_real.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_divergence_volume_real.set_defaults(fn=cmd_backtest_divergence_volume_real)

    parser_low_stoch_real = sub.add_parser(
        "backtest-low-stoch-real",
        help="Valida o setup Low Stoch Storm com candles reais 4h via CCXT",
    )
    parser_low_stoch_real.add_argument(
        "--symbols",
        default=",".join(DEFAULT_LOW_STOCH_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT,AAVE/USDT)",
    )
    parser_low_stoch_real.add_argument("--days", type=int, default=DEFAULT_LOW_STOCH_REAL_DAYS, help="janela historica em dias")
    parser_low_stoch_real.add_argument("--exchange", default="binance", help="exchange CCXT (default: binance)")
    parser_low_stoch_real.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_low_stoch_real.set_defaults(fn=cmd_backtest_low_stoch_real)

    parser_funding_real = sub.add_parser(
        "backtest-funding-real",
        help="Valida o setup Funding Arb com historico real de funding",
    )
    parser_funding_real.add_argument(
        "--symbols",
        default=",".join(DEFAULT_FUNDING_ARB_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT)",
    )
    parser_funding_real.add_argument("--days", type=int, default=DEFAULT_FUNDING_ARB_REAL_DAYS, help="janela historica em dias")
    parser_funding_real.add_argument(
        "--exchange",
        default="krakenfutures",
        help="exchange CCXT (default: krakenfutures)",
    )
    parser_funding_real.add_argument(
        "--min-rate",
        type=float,
        default=DEFAULT_FUNDING_ARB_MIN_RATE,
        dest="min_rate",
        help="funding minimo absoluto para entrada",
    )
    parser_funding_real.add_argument(
        "--exit-rate",
        type=float,
        default=DEFAULT_FUNDING_ARB_EXIT_RATE,
        dest="exit_rate",
        help="funding absoluto maximo para considerar neutro e sair",
    )
    parser_funding_real.add_argument(
        "--max-hold-intervals",
        type=int,
        default=DEFAULT_FUNDING_ARB_MAX_HOLD_INTERVALS,
        dest="max_hold_intervals",
        help="maximo de intervals de funding para manter a posicao",
    )
    parser_funding_real.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_funding_real.set_defaults(fn=cmd_backtest_funding_real)

    parser_calibrate_triangle = sub.add_parser(
        "calibrate-triangle-real",
        help="Calibra thresholds reais do Triangle Breakout",
    )
    parser_calibrate_triangle.add_argument(
        "--symbols",
        default=",".join(DEFAULT_TRIANGLE_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT)",
    )
    parser_calibrate_triangle.add_argument("--days", type=int, default=DEFAULT_TRIANGLE_REAL_DAYS, help="janela historica em dias")
    parser_calibrate_triangle.add_argument("--exchange", default="binance", help="exchange CCXT (default: binance)")
    parser_calibrate_triangle.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_calibrate_triangle.set_defaults(fn=cmd_calibrate_triangle_real)

    parser_calibrate_funding = sub.add_parser(
        "calibrate-funding-real",
        help="Calibra thresholds reais do Funding Arb",
    )
    parser_calibrate_funding.add_argument(
        "--symbols",
        default=",".join(DEFAULT_FUNDING_ARB_REAL_SYMBOLS),
        help="lista separada por virgula (ex.: BTC/USDT,ETH/USDT)",
    )
    parser_calibrate_funding.add_argument("--days", type=int, default=DEFAULT_FUNDING_ARB_REAL_DAYS, help="janela historica em dias")
    parser_calibrate_funding.add_argument(
        "--exchange",
        default="krakenfutures",
        help="exchange CCXT (default: krakenfutures)",
    )
    parser_calibrate_funding.add_argument("--output", default=None, help="caminho opcional para salvar JSON")
    parser_calibrate_funding.set_defaults(fn=cmd_calibrate_funding_real)

    sub.add_parser("setup-live-status", help="Mostra os setups live atualmente gerenciados").set_defaults(fn=cmd_setup_live_status)

    parser_notify_monitored = sub.add_parser(
        "setup-live-notify-monitored",
        help="Envia notificação das operações que já estão em monitoramento",
    )
    parser_notify_monitored.add_argument("--force", action="store_true", help="reenviar mesmo que o status já tenha sido notificado")
    parser_notify_monitored.add_argument("--notify-entry-target", default=None, help="destino principal para avisos, ex.: chat_id Telegram ou destino WhatsApp")
    parser_notify_monitored.add_argument("--notify-entry-channel", default=None, help="canal principal para avisos, ex.: telegram ou whatsapp")
    parser_notify_monitored.add_argument("--notify-entry-discord-channel-id", default=None, help="envia uma copia extra ao canal Discord informado")
    parser_notify_monitored.add_argument("--notify-entry-account", default=None, help="account id opcional do canal principal de aviso")
    parser_notify_monitored.add_argument("--notify-entry-discord-account", default=None, help="account id opcional do Discord para o aviso extra")
    parser_notify_monitored.add_argument("--no-notify-entry", action="store_true", help="desativa envio de notificação nesta execução")
    parser_notify_monitored.set_defaults(fn=cmd_setup_live_notify_monitored)

    parser_setup_live = sub.add_parser(
        "setup-live",
        aliases=["rodar-setups-live"],
        help="Roda os setups em loop, abrindo/fechando pares enquanto monitora",
    )
    parser_setup_live.add_argument("--setup", default="all", help="all ou lista separada por virgula")
    parser_setup_live.add_argument(
        "--symbol",
        default="allowlist",
        help="simbolo, lista CSV ou allowlist; all fica bloqueado para setups direcionais em modo strict",
    )
    parser_setup_live.add_argument("--interval", type=int, default=60, help="segundos entre scans")
    parser_setup_live.add_argument("--max-iter", type=int, default=None, dest="max_iter")
    parser_setup_live.add_argument(
        "--hybrid-profile",
        default=DEFAULT_HYBRID_PROFILE,
        help="perfil de risco do HYBRID: conservador/conservative, moderado/moderate, degen",
    )
    parser_setup_live.add_argument(
        "--risk-profile",
        default=None,
        help="perfil de risco/leverage: conservador=1x, moderado=5x, degen=10x (alias moderno do hybrid-profile)",
    )
    parser_setup_live.add_argument(
        "--execution-mode",
        "--modo",
        dest="execution_mode",
        choices=EXECUTION_MODE_INPUT_CHOICES,
        default=None,
        help="modo de execucao: delta-neutro/hedged, somente-dex/dex_only ou somente-cex/cex_only",
    )
    parser_setup_live.add_argument(
        "--margin-mode",
        "--modo-margem",
        dest="margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="margin mode padrao para setups direcionais",
    )
    parser_setup_live.add_argument(
        "--nado-margin-mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="sobrescreve o margin mode da Nado/DEX",
    )
    parser_setup_live.add_argument(
        "--dex-margin-mode",
        dest="nado_margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="alias generico de --nado-margin-mode para a DEX selecionada",
    )
    parser_setup_live.add_argument(
        "--kraken-margin-mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="sobrescreve o margin mode da Kraken/CEX",
    )
    parser_setup_live.add_argument(
        "--cex-margin-mode",
        dest="kraken_margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="alias generico de --kraken-margin-mode para a CEX selecionada",
    )
    parser_setup_live.add_argument(
        "--notional",
        "--valor-nominal",
        dest="notional",
        type=float,
        default=None,
        help="valor nominal em USD por perna para entradas dos setups (default: VOLUME_ORDER do .env)",
    )
    parser_setup_live.add_argument("--margin-usd", "--margem-usd", dest="margin_usd", type=float, default=None, help="margem USD; valor nominal = margem * alavancagem do perfil")
    parser_setup_live.add_argument("--nado-margin-usd", "--margem-nado-usd", dest="nado_margin_usd", type=float, default=None, help="override de margem USD da Nado/DEX")
    parser_setup_live.add_argument("--dex-margin-usd", "--margem-dex-usd", dest="nado_margin_usd", type=float, default=None, help="alias generico de --nado-margin-usd para a DEX selecionada")
    parser_setup_live.add_argument("--kraken-margin-usd", "--margem-kraken-usd", dest="kraken_margin_usd", type=float, default=None, help="override de margem USD da Kraken/CEX")
    parser_setup_live.add_argument("--cex-margin-usd", "--margem-cex-usd", dest="kraken_margin_usd", type=float, default=None, help="alias generico de --kraken-margin-usd para a CEX selecionada")
    parser_setup_live.add_argument(
        "--max-open-setups",
        type=int,
        default=None,
        help="limite global de setups live abertos; 1 para abrir uma operacao e pausar novas entradas",
    )
    parser_setup_live.add_argument("--account-margin-reserve-usd", type=float, default=None, help="reserva minima em USD de health/margem cross da Nado")
    parser_setup_live.add_argument("--account-margin-reserve-pct", type=float, default=None, help="reserva minima percentual sobre assets/health da conta cross")
    parser_setup_live.add_argument("--account-margin-slots", "--slots-margem-conta", dest="account_margin_slots", type=int, default=None, help="divide o orcamento cross em N slots e calcula margem por entrada")
    parser_setup_live.add_argument("--account-max-maint-usage-pct", type=float, default=None, help="bloqueia novas entradas se Maint. Margin Usage da Nado passar deste limite")
    parser_setup_live.add_argument("--account-stress-pct", type=float, default=None, help="stress adverso percentual sobre exposicao gerenciada antes de liberar nova entrada")
    parser_setup_live.add_argument("--notify-entry-target", default=None, help="destino principal para avisos de entrada confirmada, ex.: chat_id Telegram ou destino WhatsApp")
    parser_setup_live.add_argument("--notify-entry-channel", default=None, help="canal principal para avisos de entrada confirmada, ex.: telegram ou whatsapp")
    parser_setup_live.add_argument("--notify-entry-discord-channel-id", default=None, help="envia uma copia extra do aviso ao canal Discord informado")
    parser_setup_live.add_argument("--notify-entry-account", default=None, help="account id opcional do canal principal de aviso")
    parser_setup_live.add_argument("--notify-entry-discord-account", default=None, help="account id opcional do Discord para o aviso extra")
    parser_setup_live.add_argument("--no-notify-entry", action="store_true", help="desativa aviso de entrada confirmada nesta execucao")
    parser_setup_live.add_argument("--notify-monitored-on-start", action="store_true", help="envia status das operações já monitoradas ao iniciar")
    parser_setup_live.add_argument("--notify-monitored-force", action="store_true", help="reenviar status monitorado mesmo se já marcado como enviado")
    parser_setup_live.add_argument(
        "--target-stop-mode",
        "--modo-stop-alvo",
        dest="target_stop_mode",
        metavar="desligado|entrada-no-tp1|escada",
        default=None,
        help=(
            "politica de ajuste do stop apos alvo: desligado/off mantem stop fixo; "
            "entrada-no-tp1/breakeven_on_tp1 move para entrada no TP1; "
            "escada/ladder move TP1->entrada, TP2->TP1, TP3->TP2"
        ),
    )
    parser_setup_live.add_argument("--stop-loss-pct", default=None, help="stop em porcentagem da entrada, ex.: 10, 20 ou 30")
    parser_setup_live.add_argument(
        "--stop-loss-preset",
        choices=["10", "20", "30", "conservador", "moderado", "degen"],
        default=None,
        help="preset de stop: conservador=10%%, moderado=20%%, degen=30%%",
    )
    parser_setup_live.add_argument("--dry-run", "--simular", dest="dry_run", action="store_true")
    parser_setup_live.set_defaults(fn=cmd_setup_live)

    parser_open = sub.add_parser("open", aliases=["abrir"], help="Abre ordem hedged, DEX-only ou CEX-only")
    parser_open.add_argument("symbol", help="Ex.: BTC/USDT")
    parser_open.add_argument("--side", "--lado", dest="side", choices=["long", "short", "comprado", "vendido", "compra", "venda"], default="long")
    parser_open.add_argument(
        "--execution-mode",
        "--modo",
        dest="execution_mode",
        choices=EXECUTION_MODE_INPUT_CHOICES,
        default=None,
        help="delta-neutro/hedged, somente-dex/dex_only ou somente-cex/cex_only",
    )
    parser_open.add_argument(
        "--margin-mode",
        "--modo-margem",
        dest="margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="margin mode padrao da ordem",
    )
    parser_open.add_argument(
        "--nado-margin-mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="sobrescreve margem da Nado/DEX",
    )
    parser_open.add_argument(
        "--dex-margin-mode",
        dest="nado_margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="alias generico de --nado-margin-mode para a DEX selecionada",
    )
    parser_open.add_argument(
        "--kraken-margin-mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="sobrescreve margem da Kraken/CEX",
    )
    parser_open.add_argument(
        "--cex-margin-mode",
        dest="kraken_margin_mode",
        choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED],
        default=None,
        help="alias generico de --kraken-margin-mode para a CEX selecionada",
    )
    parser_open.add_argument("--leverage", "--alavancagem", dest="leverage", type=float, default=None, help="alavancagem padrao da ordem")
    parser_open.add_argument("--nado-leverage", "--alavancagem-nado", dest="nado_leverage", type=float, default=None, help="sobrescreve leverage da Nado/DEX")
    parser_open.add_argument("--dex-leverage", "--alavancagem-dex", dest="nado_leverage", type=float, default=None, help="alias generico de --nado-leverage para a DEX selecionada")
    parser_open.add_argument("--kraken-leverage", "--alavancagem-kraken", dest="kraken_leverage", type=float, default=None, help="sobrescreve leverage da Kraken/CEX")
    parser_open.add_argument("--cex-leverage", "--alavancagem-cex", dest="kraken_leverage", type=float, default=None, help="alias generico de --kraken-leverage para a CEX selecionada")
    parser_open.add_argument("--margin-usd", "--margem-usd", dest="margin_usd", type=float, default=None, help="margem USD; valor nominal = margem * alavancagem")
    parser_open.add_argument("--nado-margin-usd", "--margem-nado-usd", dest="nado_margin_usd", type=float, default=None, help="override de margem USD da Nado/DEX")
    parser_open.add_argument("--dex-margin-usd", "--margem-dex-usd", dest="nado_margin_usd", type=float, default=None, help="alias generico de --nado-margin-usd para a DEX selecionada")
    parser_open.add_argument("--kraken-margin-usd", "--margem-kraken-usd", dest="kraken_margin_usd", type=float, default=None, help="override de margem USD da Kraken/CEX")
    parser_open.add_argument("--cex-margin-usd", "--margem-cex-usd", dest="kraken_margin_usd", type=float, default=None, help="alias generico de --kraken-margin-usd para a CEX selecionada")
    parser_open.add_argument(
        "--notional",
        "--valor-nominal",
        dest="notional",
        type=float,
        default=None,
        help="Valor nominal em USD por perna (default: VOLUME_ORDER do .env)",
    )
    parser_open.set_defaults(fn=cmd_open)

    parser_venue_pair = sub.add_parser("open-venue-pair", aliases=["abrir-par-delta-neutro"], help="Abre par delta-neutro manual entre duas CEXs ou duas DEXs")
    parser_venue_pair.add_argument("symbol", help="Ex.: BTC/USDT")
    parser_venue_pair.add_argument("--long-venue", "--comprado-em", dest="long_venue", required=True, help="onde abrir a perna comprada/long, ex.: cex:binance, dex:nado")
    parser_venue_pair.add_argument("--short-venue", "--vendido-em", dest="short_venue", required=True, help="onde abrir a perna vendida/short, ex.: cex:kraken, dex:hyperliquid")
    parser_venue_pair.add_argument("--margin-mode", "--modo-margem", dest="margin_mode", choices=[MARGIN_MODE_CROSS, MARGIN_MODE_ISOLATED], default=None)
    parser_venue_pair.add_argument("--leverage", "--alavancagem", dest="leverage", type=float, default=None, help="alavancagem usada nas duas pernas")
    parser_venue_pair.add_argument("--margin-usd", "--margem-usd", dest="margin_usd", type=float, default=None, help="margem em USD por perna; valor nominal = margem * alavancagem")
    parser_venue_pair.add_argument("--notional", "--valor-nominal", dest="notional", type=float, default=None, help="valor nominal em USD por perna")
    parser_venue_pair.add_argument("--dry-run", "--simular", dest="dry_run", action="store_true")
    parser_venue_pair.add_argument("--replace-state", action="store_true", help="substitui venue_pair_state.json existente")
    parser_venue_pair.set_defaults(fn=cmd_open_venue_pair)

    parser_close_venue_pair = sub.add_parser("close-venue-pair", aliases=["fechar-par-delta-neutro"], help="Fecha as duas pernas salvas em venue_pair_state.json")
    parser_close_venue_pair.add_argument("--dry-run", "--simular", dest="dry_run", action="store_true")
    parser_close_venue_pair.add_argument("--clear-state", action="store_true", default=True, help="remove state depois de fechar")
    parser_close_venue_pair.set_defaults(fn=cmd_close_venue_pair)

    sub.add_parser("status", help="Mostra status do par").set_defaults(fn=cmd_status)
    sub.add_parser("live-status", help="Mostra posicoes live nas duas exchanges").set_defaults(fn=cmd_live_status)
    parser_live_hedge = sub.add_parser("live-hedge", help="Hedgeia a exposicao live detectada")
    parser_live_hedge.add_argument(
        "--symbol",
        default="all",
        help="simbolo, lista CSV (ex.: ETH/USDT,SOL/USDT) ou all",
    )
    parser_live_hedge.add_argument("--target", choices=["auto", "nado", "kraken"], default="auto")
    parser_live_hedge.add_argument("--dry-run", action="store_true")
    parser_live_hedge.set_defaults(fn=cmd_live_hedge)

    parser_live_sync = sub.add_parser("live-sync", help="Monitora e replica abertura manual entre as exchanges")
    parser_live_sync.add_argument(
        "--symbol",
        default="all",
        help="simbolo, lista CSV (ex.: ETH/USDT,SOL/USDT) ou all",
    )
    parser_live_sync.add_argument("--target", choices=["auto", "nado", "kraken"], default="auto")
    parser_live_sync.add_argument("--interval", type=int, default=10, help="segundos entre checks")
    parser_live_sync.add_argument("--max-iter", type=int, default=None, dest="max_iter")
    parser_live_sync.add_argument("--dry-run", action="store_true")
    parser_live_sync.set_defaults(fn=cmd_live_sync)

    sub.add_parser("rebalance", help="Rebalanceia drift").set_defaults(fn=cmd_rebalance)
    sub.add_parser("unwind", help="Fecha ambas as pernas").set_defaults(fn=cmd_unwind)

    parser_farm = sub.add_parser("farm", help="Loop: rebalance periodico + stop global")
    parser_farm.add_argument("--interval", type=int, default=60, help="segundos entre checks")
    parser_farm.add_argument("--max-iter", type=int, default=None, dest="max_iter")
    parser_farm.set_defaults(fn=cmd_farm)

    parser_opp = sub.add_parser("opportunistic", help="Decide lado via motor tecnico, ainda hedgeado")
    parser_opp.add_argument("--dry-run", action="store_true")
    parser_opp.set_defaults(fn=cmd_opportunistic)

    sub.add_parser("funding", help="Mostra funding rates").set_defaults(fn=cmd_funding)
    sub.add_parser("kraken-accounts", help="Mostra wallets/contas da CEX selecionada").set_defaults(fn=cmd_kraken_accounts)
    sub.add_parser("cex-accounts", help="Alias generico de kraken-accounts para a CEX selecionada").set_defaults(fn=cmd_kraken_accounts)

    parser_sim = sub.add_parser("simulate", help="Resume cenarios simulados por ativo/perfil")
    parser_sim.add_argument(
        "--symbol",
        default="all",
        help="simbolo, lista CSV (ex.: ETH/USDT,SOL/USDT) ou all",
    )
    parser_sim.add_argument("--setup", choices=["delta", "funding"], default="delta")
    parser_sim.add_argument("--profiles", default="1x,2x,3x", help="Perfis separados por virgula")
    parser_sim.set_defaults(fn=cmd_simulate)

    parser_matrix = sub.add_parser("scenario-matrix", help="Mostra a matriz completa de cenarios")
    parser_matrix.add_argument(
        "--symbol",
        default="all",
        help="simbolo, lista CSV (ex.: ETH/USDT,SOL/USDT) ou all",
    )
    parser_matrix.add_argument("--setup", choices=["delta", "funding"], default="delta")
    parser_matrix.set_defaults(fn=cmd_scenario_matrix)

    args = parser.parse_args(argv)
    _require_live_confirmation(args)
    try:
        args.fn(args)
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
