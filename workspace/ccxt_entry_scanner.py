#!/usr/bin/env python3
"""Scan public CCXT markets for setup entry signals and notify Discord.

This is analysis-only. It fetches public candles from configured exchanges,
evaluates setup entries, and sends Discord batches. It never places orders.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from workspace.core import evaluate_setup_entry, prepare_market_dataset
from workspace.core.setups import SETUP_CATALOG, normalize_hybrid_profile, normalize_setup_key

try:
    from workspace.cli import (
        _entry_chart_payload as _canonical_entry_chart_payload,
        _format_entry_notice as _canonical_format_entry_notice,
        _format_whatsapp_from_notice as _canonical_format_whatsapp_from_notice,
    )
except Exception:  # noqa: BLE001
    _canonical_entry_chart_payload = None
    _canonical_format_entry_notice = None
    _canonical_format_whatsapp_from_notice = None

try:
    from workspace.trade_dashboard import record_scanner_signals as _record_dashboard_signals
except Exception:  # noqa: BLE001
    _record_dashboard_signals = None


SKILL_ID = "trade-automatizado-openclaw"
HOME = Path.home()
DEFAULT_STATE_PATH = HOME / ".openclaw" / "state" / SKILL_ID / "ccxt_entry_scanner_state.json"
DEFAULT_LOG_PATH = HOME / ".openclaw" / "logs" / SKILL_ID / "ccxt-entry-scanner.log"
DEFAULT_ENV_PATH = HOME / ".config" / "openclaw" / f"{SKILL_ID}.env"


def _parse_setup_asset_allowlist(raw: str) -> dict[str, set[str]]:
    """Parse setup-specific asset allowlist.

    Format: ``setup-a:BTC|ETH;setup-b:SOL,XRP``. Empty means no extra filter.
    """
    parsed: dict[str, set[str]] = {}
    for chunk in str(raw or "").split(";"):
        if ":" not in chunk:
            continue
        setup_raw, assets_raw = chunk.split(":", 1)
        setup_key = normalize_setup_key(setup_raw.strip())
        assets = {
            asset.strip().upper()
            for asset in assets_raw.replace("|", ",").split(",")
            if asset.strip()
        }
        if setup_key and assets:
            parsed[setup_key] = assets
    return parsed


EXCHANGES = [item.strip() for item in os.environ.get("SETUP_TEST_EXCHANGES", "binanceusdm,bybit,okx,kucoinfutures,gateio").split(",") if item.strip()]
RAW_SYMBOLS = [
    item.strip()
    for item in os.environ.get(
        "SETUP_TEST_SYMBOLS",
        "all-perps",
    ).split(",")
    if item.strip()
]
SYMBOL_MODE = "all-perps" if any(item.lower() in {"all", "all-perps", "perps", "perpetuals"} for item in RAW_SYMBOLS) else "list"
SYMBOL_QUOTES = {item.strip().upper() for item in os.environ.get("SETUP_TEST_QUOTES", "USDT").split(",") if item.strip()}
BASE_ALLOWLIST = {
    item.strip().upper()
    for item in os.environ.get("SETUP_TEST_BASE_ALLOWLIST", "").split(",")
    if item.strip()
}
MAX_SYMBOLS_PER_EXCHANGE = int(os.environ.get("SETUP_TEST_MAX_SYMBOLS_PER_EXCHANGE", "0"))
SETUPS = [
    normalize_setup_key(item)
    for item in os.environ.get(
        "SETUP_TEST_SETUPS",
        "grid-strict,institutional-strict,bollinger-mean-reversion,low-stoch-storm,divergence-and-volume-4h,delta-neutral",
    ).split(",")
    if item.strip()
]
SETUP_ASSET_ALLOWLIST = _parse_setup_asset_allowlist(os.environ.get("SETUP_TEST_SETUP_ASSET_ALLOWLIST", ""))
INTERVAL_SECONDS = int(os.environ.get("SETUP_TEST_INTERVAL_SECONDS", "300"))
HYBRID_PROFILE = normalize_hybrid_profile(os.environ.get("SETUP_TEST_RISK_PROFILE", "moderate"))
DEDUP_SECONDS = int(os.environ.get("SETUP_TEST_DEDUP_SECONDS", "1800"))
MAX_SIGNALS_PER_BATCH = int(os.environ.get("SETUP_TEST_MAX_SIGNALS_PER_BATCH", "1"))
TEST_LEVERAGE = float(os.environ.get("SETUP_TEST_LEVERAGE", "5"))
STATE_PATH = Path(os.environ.get("SETUP_TEST_STATE_PATH", DEFAULT_STATE_PATH)).expanduser()
LOG_PATH = Path(os.environ.get("SETUP_TEST_LOG_PATH", DEFAULT_LOG_PATH)).expanduser()
OUTBOX_PATH = Path(os.environ.get("SETUP_TRADING_OUTBOX_PATH", STATE_PATH.with_name("trading-signal-outbox.jsonl"))).expanduser()
DISCORD_TARGET = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "").strip()
DISCORD_ACCOUNT = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT", "default").strip()
WHATSAPP_TARGET = os.environ.get("SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET", "").strip()
WHATSAPP_ACCOUNT = os.environ.get("SETUP_NOTIFY_ENTRY_WHATSAPP_ACCOUNT", "default").strip()
NOTIFY_WHATSAPP = bool(WHATSAPP_TARGET) and os.environ.get("SETUP_NOTIFY_WHATSAPP_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "nao",
    "off",
}
OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "openclaw")
NOTIFY_TIMEOUT_SECONDS = max(1, int(os.environ.get("SETUP_NOTIFY_TIMEOUT_SECONDS", "15")))
SECRET_LOOKUP_TIMEOUT_SECONDS = max(1, min(10, NOTIFY_TIMEOUT_SECONDS))
NOTIFY_BLOCKING = os.environ.get("SETUP_NOTIFY_BLOCKING", "0").strip().lower() in {"1", "true", "yes", "sim"}
NOTIFY_QUEUE_MAX = max(1, int(os.environ.get("SETUP_NOTIFY_QUEUE_MAX", "25")))
NOTIFY_DROP_OLDEST = os.environ.get("SETUP_NOTIFY_DROP_OLDEST", "1").strip().lower() not in {"0", "false", "no", "nao"}
NOTIFY_DISCORD_DIRECT = os.environ.get("SETUP_NOTIFY_DISCORD_DIRECT", "1").strip().lower() not in {"0", "false", "no", "nao"}
NOTIFY_FALLBACK_OPENCLAW = os.environ.get("SETUP_NOTIFY_FALLBACK_OPENCLAW", "0").strip().lower() in {"1", "true", "yes", "sim"}
NOTIFY_MIN_INTERVAL_SECONDS = max(0.0, float(os.environ.get("SETUP_NOTIFY_MIN_INTERVAL_SECONDS", "0.5")))
REQUIRE_CHART_FOR_ENTRY = os.environ.get("SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY", "1").strip().lower() not in {"0", "false", "no", "nao", "off"}
TRADE_NOTICE_TZ = ZoneInfo(os.environ.get("SETUP_NOTIFY_TIMEZONE", "America/Sao_Paulo") or "America/Sao_Paulo")

_DISCORD_QUEUE: queue.Queue[tuple[str, str, list[str], str, Path | None, dict[str, Any] | None]] = queue.Queue(
    maxsize=NOTIFY_QUEUE_MAX
)
_DISCORD_WORKER_LOCK = threading.Lock()
_DISCORD_WORKER_STARTED = False


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _parse_pct_value(raw: float | str | None) -> float:
    if raw is None:
        return 0.0
    value = float(str(raw).strip().rstrip("%"))
    if value > 1:
        value /= 100
    return max(value, 0.0)


def _pct_from_env(*names: str, default: float = 0.0) -> float:
    """Percentual de risco vindo do ambiente, com o vocabulario do `cli`.

    Esta funcao tinha a sua propria copia do parser e o mesmo
    `except ... return default` -- e consulta exatamente as mesmas variaveis
    (`PROTECTIVE_STOP_LOSS_PCT`, `MAX_PAIR_LOSS_PCT`). Corrigir so o `cli`
    deixaria dois vereditos para a mesma pergunta, que e o defeito de origem
    do sandbox.
    """
    from workspace.cli import _parse_pct_value as _pct

    raw = _first_env(*names)
    if raw is None:
        return default
    # Mesmo criterio do `_first_env` acima: a variavel que de fato carregou o
    # valor, e nao a primeira da cadeia -- citar a primeira mandaria o operador
    # mexer numa variavel que ele nao definiu.
    declarada = next(
        (n for n in names if os.environ.get(n) is not None and str(os.environ[n]).strip()),
        names[0],
    )
    return _pct(raw, declarada)


TEST_STOP_LOSS_PCT = _pct_from_env(
    "SETUP_TEST_STOP_LOSS_PCT",
    "SETUP_NOTIFY_STOP_LOSS_PCT",
    "PROTECTIVE_STOP_LOSS_PCT",
    "MAX_PAIR_LOSS_PCT",
    default=0.03,
)
TEST_TAKE_PROFIT_PCT = _pct_from_env(
    "SETUP_TEST_TAKE_PROFIT_PCT",
    "SETUP_NOTIFY_TAKE_PROFIT_PCT",
    "PROTECTIVE_TAKE_PROFIT_PCT",
    default=0.03,
)


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


def _log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _load_state() -> dict[str, float]:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {str(key): float(value) for key, value in payload.items()}
    except Exception:
        return {}


def _save_state(state: dict[str, float]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max(DEDUP_SECONDS * 4, 3600)
    compact = {key: value for key, value in state.items() if value >= cutoff}
    STATE_PATH.write_text(json.dumps(compact, indent=2), encoding="utf-8")


def _build_exchange(exchange_id: str):
    import ccxt

    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise ValueError(f"exchange invalida: {exchange_id}")
    exchange = exchange_cls({"enableRateLimit": True})
    if hasattr(exchange, "load_markets"):
        exchange.load_markets()
    return exchange


def _is_perpetual_market(market: dict[str, Any]) -> bool:
    if market.get("active") is False:
        return False
    quote = str(market.get("quote") or "").upper()
    settle = str(market.get("settle") or "").upper()
    if SYMBOL_QUOTES and quote not in SYMBOL_QUOTES and settle not in SYMBOL_QUOTES:
        return False
    if market.get("swap") is True:
        return True
    market_type = str(market.get("type") or "").lower()
    contract_type = str(
        market.get("contractType")
        or (market.get("info") or {}).get("contractType")
        or (market.get("info") or {}).get("ctType")
        or ""
    ).lower()
    return market_type == "swap" or "perpetual" in contract_type or contract_type in {"linearperpetual", "inverseperpetual"}


def _resolve_symbols_for_exchange(exchange: Any) -> list[str]:
    markets = getattr(exchange, "markets", {}) or {}
    if SYMBOL_MODE != "all-perps":
        symbols = list(RAW_SYMBOLS)
        if BASE_ALLOWLIST and markets:
            symbols = [symbol for symbol in symbols if _market_base_symbol(markets.get(symbol), symbol) in BASE_ALLOWLIST]
        return symbols

    symbols = sorted(
        {
            str(market.get("symbol") or symbol)
            for symbol, market in markets.items()
            if isinstance(market, dict) and _is_perpetual_market(market)
            and (not BASE_ALLOWLIST or _market_base_symbol(market, str(market.get("symbol") or symbol)) in BASE_ALLOWLIST)
        }
    )
    if MAX_SYMBOLS_PER_EXCHANGE > 0:
        return symbols[:MAX_SYMBOLS_PER_EXCHANGE]
    return symbols


def _market_base_symbol(market: dict[str, Any] | None, fallback_symbol: str) -> str:
    if isinstance(market, dict):
        base = str(market.get("base") or "").strip().upper()
        if base:
            return base
    raw = str(fallback_symbol or "").strip().upper()
    return re.split(r"[/:-]", raw, maxsplit=1)[0].strip()


def _raw_ohlcv_to_frame(raw: list[list[Any]]) -> pd.DataFrame:
    if not raw:
        raise ValueError("sem candles")
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def _resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe != "4h":
        return df
    frame = df.sort_values("timestamp").set_index("timestamp")
    resampled = (
        frame.resample("4h", label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    if resampled.empty:
        raise ValueError("sem candles 4h agregados")
    return resampled


def _fetch_dataset(exchange: Any, symbol: str, timeframe: str) -> pd.DataFrame:
    limit = 240 if timeframe == "15m" else 180
    source_timeframe = timeframe
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = _raw_ohlcv_to_frame(raw)
    except Exception as exc:
        if timeframe != "4h":
            raise
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=limit * 4)
            df = _resample_ohlcv(_raw_ohlcv_to_frame(raw), timeframe)
            source_timeframe = "1h"
        except Exception:
            raise exc
    df = prepare_market_dataset(df)
    df.attrs["exchange"] = getattr(exchange, "id", "unknown")
    df.attrs["timeframe"] = timeframe
    df.attrs["source_timeframe"] = source_timeframe
    return df


def _timeframe_for_setup(setup_key: str) -> str:
    return SETUP_CATALOG[setup_key].timeframe


def _discord_message_prefix() -> str:
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_MENTION", "").strip()
    if raw.lower() in {"0", "false", "no", "nao", "off", "none"}:
        return ""
    if raw.lower() in {"1", "true", "yes", "sim", "everyone"}:
        return "@everyone"
    return raw


def _message_already_has_prefix(message: str, prefix: str) -> bool:
    if not prefix:
        return True
    first_lines = [line.strip() for line in str(message or "").splitlines()[:5] if line.strip()]
    return any(line == prefix or line.startswith(f"{prefix} ") for line in first_lines)


def _discord_allowed_mentions(text: str) -> dict[str, Any]:
    clean = str(text or "")
    roles = list(dict.fromkeys(re.findall(r"<@&(\d+)>", clean)))[:25]
    parse = ["everyone"] if clean.strip().startswith("@everyone") else []
    payload: dict[str, Any] = {"parse": parse}
    if roles:
        payload["roles"] = roles
    return payload


def _discord_box_enabled() -> bool:
    # Box/código no Discord fica reservado para atualização de posição/alvo.
    # Scanner publica trade novo detectado em texto normal, mesmo no fallback.
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


def _with_discord_message_prefix(message: str) -> str:
    prefix = _discord_message_prefix()
    clean_message = message
    if prefix and clean_message.startswith(prefix):
        clean_message = clean_message[len(prefix):].lstrip("\n")
    if prefix and _discord_box_enabled() and _discord_box_style() == "code":
        return f"{prefix}\n{_box_discord_message(clean_message)}"
    if prefix and not _message_already_has_prefix(clean_message, prefix):
        clean_message = f"{prefix}\n{clean_message}"
    return _box_discord_message(clean_message)


def _notice_brand_label() -> str:
    return os.environ.get("SETUP_NOTIFY_BRAND", "").strip()


def _notice_header_lines(title: str) -> list[str]:
    brand = _notice_brand_label()
    if not brand:
        return [title]
    return [brand, title]


def _format_trade_datetime(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=TRADE_NOTICE_TZ)
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year}, {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} BRT"


def _format_trade_symbol(symbol: str) -> str:
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("/", "")
    if cleaned and not cleaned.endswith(("USDT", "USDC", "USD")):
        cleaned = f"{cleaned}USDT"
    return cleaned or "N/A"


def _format_trade_price(value: Any) -> str:
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
    return f"${formatted}"


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
        "degen": "Agressivo",
    }.get(normalized, normalized.capitalize() if normalized else "Moderado")


def _leverage_notice_label(leverage: Any) -> str:
    try:
        value = float(leverage or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    if value <= 0:
        return "N/A"
    return f"{value:g}x"


def _signal_targets_lines(targets: list[float]) -> list[str]:
    valid_targets = [target for target in targets if float(target or 0.0) > 0]
    if not valid_targets:
        return ["ALVO 1: N/A ⏳"]
    return [f"ALVO {idx}: {_format_trade_price(target)} ⏳" for idx, target in enumerate(valid_targets, start=1)]


def _signal_targets_inline(targets: list[float]) -> str:
    return " | ".join(_signal_targets_lines(targets))


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


def _risk_reward_ratio(entry_price: Any, stop_price: Any, targets: list[float]) -> str:
    try:
        entry = float(entry_price or 0.0)
        stop = float(stop_price or 0.0)
        target = float((targets or [0.0])[-1] or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0 or reward <= 0:
        return "N/A"
    return f"{reward / risk:.2f}"


def _ensure_four_targets(targets: list[float]) -> list[float]:
    valid = [float(target) for target in targets if float(target or 0.0) > 0]
    return valid[:4]


def _format_targets_block(targets: list[float]) -> list[str]:
    valid = _ensure_four_targets(targets)
    if not valid:
        return ["→ Alvo 1: N/A"]
    return [f"→ Alvo {idx}: {_format_trade_price(target)}" for idx, target in enumerate(valid, start=1)]


def _format_activation_bullets(signal: dict[str, Any], targets: list[float]) -> list[str]:
    side = str(signal.get("side") or "").upper() or "N/A"
    reason = str(signal.get("reason") or "Setup detectado pelo scanner.").strip().rstrip(".")
    entry = _format_trade_price(signal.get("entry_price"))
    stop = _format_trade_price(signal.get("stop_price"))
    rr = _risk_reward_ratio(signal.get("entry_price"), signal.get("stop_price"), targets)
    final_target = _format_trade_price(targets[-1]) if targets else "N/A"
    bullets = [f"→ {reason}."]
    bullets.append(f"→ Entrada técnica em {entry} com invalidação em {stop}.")
    bullets.append(f"→ Alvos definidos até {final_target}; relação risco/retorno estimada: {rr}.")
    bullets.append(f"→ Operação {side} segue válida enquanto não perder a invalidação em {stop}.")
    return bullets


def _format_signal_notice(signal: dict[str, Any]) -> str:
    if _canonical_format_entry_notice is not None:
        return _canonical_format_entry_notice(
            title="🚨 NOVA OPERAÇÃO 🚨",
            setup_key=str(signal.get("setup") or ""),
            symbol=str(signal.get("symbol") or ""),
            side=str(signal.get("side") or ""),
            entry_price=float(signal.get("entry_price") or 0.0),
            stop_price=float(signal.get("stop_price") or 0.0),
            targets=_ensure_four_targets(list(signal.get("targets") or [])),
            leverage=float(signal.get("leverage") or TEST_LEVERAGE or 0.0),
            risk_profile=str(signal.get("risk_profile") or HYBRID_PROFILE or "moderate"),
            timeframe=str(signal.get("timeframe") or "N/A"),
            reason=str(signal.get("reason") or "Setup detectado pelo scanner CCXT."),
            venue=str(signal.get("exchange") or "ccxt"),
            margin_mode=str(signal.get("margin_mode") or ""),
        )

    symbol_pair = _format_symbol_pair(str(signal.get("symbol") or ""))
    base = _symbol_base(symbol_pair)
    setup_label = _setup_notice_strategy(str(signal.get("setup") or ""))
    timeframe = str(signal.get("timeframe") or "N/A")
    side = str(signal.get("side") or "").upper() or "N/A"
    targets = _ensure_four_targets(list(signal.get("targets") or []))
    rr = _risk_reward_ratio(signal.get("entry_price"), signal.get("stop_price"), targets)
    audience = os.environ.get("SETUP_NOTIFY_DISCORD_AUDIENCE", "@intus Club Member").strip()
    risk_text = os.environ.get(
        "SETUP_NOTIFY_RISK_TEXT",
        "5% da banca destinada a trading futuros com alavancagem máxima de 5x.",
    ).strip()
    disclaimer = os.environ.get(
        "SETUP_NOTIFY_DISCLAIMER",
        "O mercado de criptomoedas é altamente volátil e imprevisível. As análises e operações compartilhadas aqui são baseadas em indicadores técnicos, price action e outros dados de mercado, mas NÃO constituem recomendação de investimento. Cada participante deve realizar sua própria análise e entrar em qualquer operação por conta e risco próprios.",
    ).strip()
    reason = str(signal.get("reason") or "Setup detectado pelo scanner.").strip().rstrip(".")
    lines = [symbol_pair]
    if audience:
        lines.append(audience)
    lines.extend(
        [
            "",
            f"Análise Técnica - {setup_label} - Time Frame {timeframe}",
            "",
            f"{base} aciona sinal do setup {setup_label} após {reason}.",
            "",
            "Por que ativou:",
            *_format_activation_bullets(signal, targets),
            "",
            "Leitura técnica:",
            f"A estrutura favorece busca pelos alvos enquanto as condições do setup continuarem sustentando a direção do movimento. Relação risco/retorno estimada: {rr}.",
            "",
            "Trading:",
            f"Operação: {side}",
            f"Entrada: {_format_trade_price(signal.get('entry_price'))}",
            f"Stop: {_format_trade_price(signal.get('stop_price'))}",
            "",
            "Alvos:",
            *_format_targets_block(targets),
            "",
            "⚠ (AS OUTRAS ORDENS SÓ DEVEM SER COLOCADAS SE ACIONAR A ORDEM 1)",
            "",
            "⚡ Após chegar ao ALVO 1, é interessante mudar o stoploss para o ponto de entrada e realizar parcial de acordo com seu gerenciamento de risco.",
            "",
            "Gerenciamento de risco:",
            risk_text,
        ]
    )
    if disclaimer:
        lines.extend(["", "Disclaimer:", disclaimer])
    return "\n".join(lines)


def _format_messages(signals: list[dict[str, Any]]) -> list[str]:
    return [_format_signal_notice(signal) for signal in signals]


def _utc_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(float(ts or time.time()), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _signal_symbol_text(signal: dict[str, Any]) -> str:
    return _format_symbol_pair(str(signal.get("symbol") or "")).replace("/", "")


def _signal_idempotency_key(signal: dict[str, Any]) -> str:
    parts = [
        str(signal.get("exchange") or "ccxt"),
        str(signal.get("symbol") or ""),
        str(signal.get("setup") or ""),
        str(signal.get("side") or ""),
        str(signal.get("timeframe") or ""),
        str(signal.get("bar_at") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _structured_signal_call(signal: dict[str, Any]) -> dict[str, Any]:
    targets = _ensure_four_targets(list(signal.get("targets") or []))
    created_at = float(signal.get("created_at") or time.time())
    pair = _format_symbol_pair(str(signal.get("symbol") or ""))
    setup = str(signal.get("setup") or "")
    side = str(signal.get("side") or "").upper()
    return {
        "schema": "aspira.trading.signal_call.v1",
        "idempotency_key": _signal_idempotency_key(signal),
        "source": "unified_scanner",
        "called_at": _utc_iso(created_at),
        "bar_at": signal.get("bar_at") or "",
        "asset_text": _symbol_base(pair),
        "setup_text": _setup_notice_strategy(setup),
        "setup_slug": setup,
        "pair": pair,
        "symbol": _signal_symbol_text(signal),
        "venue": str(signal.get("exchange") or "ccxt"),
        "side": side,
        "timeframe": str(signal.get("timeframe") or ""),
        "entry": float(signal.get("entry_price") or 0.0),
        "initial_stop": float(signal.get("stop_price") or 0.0),
        "targets": targets,
        "thesis": str(signal.get("reason") or "Setup detectado pelo scanner."),
        "leverage": float(signal.get("leverage") or TEST_LEVERAGE or 0.0),
        "risk_profile": str(signal.get("risk_profile") or HYBRID_PROFILE or "moderate"),
        "context": {
            "exchange": signal.get("exchange"),
            "raw_symbol": signal.get("symbol"),
            "take_profit": signal.get("take_profit"),
            "margin_mode": signal.get("margin_mode") or "",
            "scanner_state_path": str(STATE_PATH),
        },
        "raw_payload": signal,
    }


def _append_outbox_record(record: dict[str, Any]) -> None:
    try:
        OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:  # noqa: BLE001
        _log(f"outbox erro | {exc}")


def _format_whatsapp_from_discord_notice(discord_message: str) -> str:
    """Adapt the already-built Discord notice to WhatsApp without changing Discord."""
    if _canonical_format_whatsapp_from_notice is not None:
        return _canonical_format_whatsapp_from_notice(discord_message)
    text = str(discord_message or "").strip()
    audience = os.environ.get("SETUP_NOTIFY_WHATSAPP_AUDIENCE", "Intus Club Member").strip()
    if audience:
        text = re.sub(r"<@&\d+>", audience, text)
        text = text.replace("@Intus Club Member", audience)

    # Discord heading/list syntax is noisy in WhatsApp; keep the same content,
    # only adapt lightweight markup for the channel.
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = line.replace("**", "*")
        lines.append(line)

    compact: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            compact.append(line)
            blank_count = 0
            continue
        blank_count += 1
        if blank_count <= 1:
            compact.append("")

    prefix = os.environ.get("SETUP_NOTIFY_WHATSAPP_PREFIX", "").strip()
    if prefix:
        compact = [prefix, "", *compact]
    return "\n".join(compact).strip()


def _discord_channel_id(target: str) -> str:
    if target.startswith("channel:"):
        return target.split(":", 1)[1].strip()
    if target.isdigit():
        return target
    return ""


def _discord_bot_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    env_path = Path(os.environ.get("SETUP_NOTIFY_ENV_FILE", DEFAULT_ENV_PATH)).expanduser()
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_BOT_TOKEN":
                token = value.strip().strip('"').strip("'")
                if token:
                    return token
    except Exception:
        pass
    return _discord_bot_token_from_openclaw_config()


def _discord_bot_token_from_openclaw_config() -> str:
    config_path = Path(os.environ.get("OPENCLAW_CONFIG_PATH", HOME / ".openclaw" / "openclaw.json")).expanduser()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        token_ref = ((config.get("channels") or {}).get("discord") or {}).get("token")
        if isinstance(token_ref, str):
            return token_ref.strip()
        if not isinstance(token_ref, dict) or token_ref.get("source") != "exec":
            return ""
        provider_name = str(token_ref.get("provider") or "").strip()
        provider = ((config.get("secrets") or {}).get("providers") or {}).get(provider_name) or {}
        command = str(provider.get("command") or "").strip()
        args = [str(arg) for arg in provider.get("args") or []]
        if not command:
            return ""
        pass_env = {str(name) for name in provider.get("passEnv") or []}
        env = {name: os.environ[name] for name in pass_env if name in os.environ}
        if "HOME" in os.environ:
            env.setdefault("HOME", os.environ["HOME"])
        result = subprocess.run(
            [command, *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=SECRET_LOOKUP_TIMEOUT_SECONDS,
            env=env,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return ""
    return ""


def _setup_chart_enabled() -> bool:
    raw = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_IMAGE", os.environ.get("SETUP_NOTIFY_CHART_ENABLED", "true")).strip().lower()
    return raw not in {"0", "false", "no", "nao", "off", "none"}


def _force_canonical_tradingview_env() -> None:
    # CCXT é só mecanismo de scan. A entrega visual precisa ser a mesma do
    # setup-live/último PR: widget TradingView canônico, nunca canvas estático.
    os.environ["SETUP_NOTIFY_TRADINGVIEW_RENDERER"] = "widget"
    os.environ["SETUP_NOTIFY_TRADINGVIEW_STATIC_RENDERER"] = "false"
    os.environ["SETUP_NOTIFY_TRADINGVIEW_NATIVE_ONLY"] = "true"
    os.environ["SETUP_NOTIFY_TRADINGVIEW_ALLOW_FALLBACK_SCALE"] = "false"
    os.environ["SETUP_NOTIFY_TRADINGVIEW_ESTIMATED_OVERLAY"] = "false"
    os.environ["SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY"] = "true"


def _canonical_chart_payload(signal: dict[str, Any]) -> dict[str, Any]:
    targets = _ensure_four_targets(list(signal.get("targets") or []))
    if _canonical_entry_chart_payload is not None:
        payload = _canonical_entry_chart_payload(
            setup_key=str(signal.get("setup") or ""),
            symbol=str(signal.get("symbol") or ""),
            side=str(signal.get("side") or ""),
            entry_price=float(signal.get("entry_price") or 0.0),
            stop_price=float(signal.get("stop_price") or 0.0),
            targets=targets,
            timeframe=str(signal.get("timeframe") or "N/A"),
            reason=str(signal.get("reason") or "Setup detectado pelo scanner CCXT."),
        )
    else:
        payload = dict(signal)
        payload["targets"] = targets
    payload["exchange"] = str(signal.get("exchange") or payload.get("exchange") or "").strip()
    payload["market_symbol"] = str(signal.get("symbol") or payload.get("symbol") or "").strip()
    return payload


def _signal_chart_image(signal: dict[str, Any]) -> Path | None:
    if not _setup_chart_enabled():
        return None
    try:
        from workspace.tradingview_chart import render_tradingview_chart

        _force_canonical_tradingview_env()
        return render_tradingview_chart(_canonical_chart_payload(signal))
    except Exception as exc:  # noqa: BLE001
        _log(
            f"grafico TradingView canonico falhou | symbol={signal.get('symbol', '')} "
            f"setup={signal.get('setup', '')} | {exc}"
        )
    return None


def _discord_multipart_body(payload: dict, image_path: Path) -> tuple[bytes, str]:
    boundary = f"aspira-trade-{int(time.time() * 1000)}"
    filename = image_path.name or "trade-chart.png"
    content_type = mimetypes.guess_type(filename)[0] or "image/png"
    chunks: list[bytes] = []
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
    chunks.append(b"Content-Type: application/json\r\n\r\n")
    chunks.append(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'.encode())
    chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    chunks.append(image_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _discord_plain_content(message: str, prefix: str = "") -> str:
    clean_message = str(message or "").strip()
    clean_prefix = str(prefix or "").strip()
    if clean_prefix and not _message_already_has_prefix(clean_message, clean_prefix):
        clean_message = f"{clean_prefix}\n{clean_message}" if clean_message else clean_prefix
    if len(clean_message) <= 2000:
        return clean_message
    for marker in ("\nDisclaimer:", "\nGerenciamento de risco:"):
        head = clean_message.split(marker, 1)[0].rstrip()
        if head and len(head) <= 1980:
            return f"{head}\n\nTexto encurtado para caber em uma única mensagem do Discord."
    return clean_message[:1970].rstrip() + "\n…"


def _build_discord_embed(message: str, image_path: Path | None = None) -> dict[str, object]:
    lines = [line.rstrip() for line in str(message or "").splitlines()]
    title = next((line for line in lines if line.strip()), "🚨 NOVA OPERAÇÃO 🚨")
    body = "\n".join(line for line in lines[1:] if line.strip())[:4096]
    upper = str(message or "").upper()
    embed: dict[str, object] = {
        "title": title[:256],
        "description": body or "\u200b",
        "color": 0xE74C3C if "SHORT" in upper or "STOP" in upper else 0x2ECC71 if "LONG" in upper else 0xF1C40F,
    }
    author = os.environ.get("SETUP_NOTIFY_DISCORD_EMBED_AUTHOR", os.environ.get("SETUP_NOTIFY_BRAND", "")).strip()
    if author:
        embed["author"] = {"name": author}
    if image_path is not None and image_path.is_file():
        embed["image"] = {"url": f"attachment://{image_path.name}"}
    return embed


def _send_discord_direct(target: str, message: str, context: str, image_path: Path | None = None) -> dict[str, Any]:
    if not NOTIFY_DISCORD_DIRECT:
        return {"ok": False, "message_id": "", "method": "direct", "status": "disabled"}
    token = _discord_bot_token()
    channel_id = _discord_channel_id(target)
    if not token or not channel_id:
        return {"ok": False, "message_id": "", "method": "direct", "status": "missing_token_or_channel"}
    prefix = _discord_message_prefix()
    content = _discord_plain_content(message, prefix)
    payload = {
        "content": content,
        "allowed_mentions": _discord_allowed_mentions(content),
    }
    if image_path is not None and image_path.is_file():
        payload["attachments"] = [{"id": 0, "filename": image_path.name}]
        data, boundary = _discord_multipart_body(payload, image_path)
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        content_type = "application/json"
    for attempt in range(2):
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=data,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": content_type,
                "User-Agent": "trader-low_stoch-scanner",
            },
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_SECONDS) as response:
                elapsed = time.monotonic() - start
                body = response.read().decode("utf-8", errors="replace")
                ok = 200 <= int(response.status) < 300
                try:
                    payload_out = json.loads(body or "{}")
                except Exception:
                    payload_out = {}
                message_id = _extract_message_id(payload_out)
                _log(
                    f"discord direct status={response.status} {context} elapsed={elapsed:.1f}s "
                    f"message_id={message_id or 'n/a'}"
                )
                return {
                    "ok": ok,
                    "message_id": message_id,
                    "method": "direct",
                    "status": int(response.status),
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read(200).decode("utf-8", errors="replace")
            if exc.code == 429 and attempt == 0:
                try:
                    retry_after = float(json.loads(detail).get("retry_after", 1.0))
                except Exception:
                    retry_after = 1.0
                retry_after = min(max(retry_after, 0.3), float(NOTIFY_TIMEOUT_SECONDS))
                _log(f"discord direct rate_limit {context} retry_after={retry_after:.1f}s")
                time.sleep(retry_after)
                continue
            _log(f"discord direct erro {context} | status={exc.code} | detail={detail}")
        except Exception as exc:  # noqa: BLE001
            _log(f"discord direct erro {context} | {exc}")
        return {"ok": False, "message_id": "", "method": "direct", "status": "failed"}
    return {"ok": False, "message_id": "", "method": "direct", "status": "failed"}


def _run_openclaw_discord_command(cmd: list[str], context: str) -> dict[str, Any]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=NOTIFY_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start
        parsed: Any = None
        stdout = (result.stdout or "").strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = None
        message_id = _extract_message_id(parsed)
        _log(f"discord rc={result.returncode} {context} elapsed={elapsed:.1f}s message_id={message_id or 'n/a'}")
        return {
            "ok": result.returncode == 0,
            "message_id": message_id,
            "method": "openclaw",
            "status": result.returncode,
            "payload": parsed,
        }
    except subprocess.TimeoutExpired:
        _log(f"discord timeout {context} timeout={NOTIFY_TIMEOUT_SECONDS}s")
        return {"ok": False, "message_id": "", "method": "openclaw", "status": "timeout"}
    except Exception as exc:  # noqa: BLE001
        _log(f"discord erro {context} | {exc}")
        return {"ok": False, "message_id": "", "method": "openclaw", "status": "error"}


def _extract_message_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = [
        payload.get("messageId"),
        payload.get("message_id"),
        payload.get("id"),
        (payload.get("result") or {}).get("messageId") if isinstance(payload.get("result"), dict) else None,
        (payload.get("result") or {}).get("id") if isinstance(payload.get("result"), dict) else None,
        ((payload.get("payload") or {}).get("result") or {}).get("messageId") if isinstance(payload.get("payload"), dict) else None,
        ((payload.get("payload") or {}).get("result") or {}).get("id") if isinstance(payload.get("payload"), dict) else None,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _run_openclaw_message_command(cmd: list[str], label: str, context: str) -> dict[str, Any]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=NOTIFY_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start
        stdout = (result.stdout or "").strip()
        parsed: Any = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = None
        message_id = _extract_message_id(parsed)
        _log(f"{label} rc={result.returncode} {context} elapsed={elapsed:.1f}s message_id={message_id or 'n/a'}")
        return {"ok": result.returncode == 0, "message_id": message_id, "payload": parsed}
    except subprocess.TimeoutExpired:
        _log(f"{label} timeout {context} timeout={NOTIFY_TIMEOUT_SECONDS}s")
    except Exception as exc:  # noqa: BLE001
        _log(f"{label} erro {context} | {exc}")
    return {"ok": False, "message_id": "", "payload": None}


def _send_whatsapp(discord_message: str, context: str, image_path: Path | None = None) -> dict[str, Any]:
    if not NOTIFY_WHATSAPP:
        return {"ok": False, "message_id": "", "payload": None}
    cmd = [
        OPENCLAW_BIN,
        "message",
        "send",
        "--channel",
        "whatsapp",
        "--target",
        WHATSAPP_TARGET,
        "--message",
        _format_whatsapp_from_discord_notice(discord_message),
    ]
    if image_path is not None and image_path.is_file():
        cmd.extend(["--media", str(image_path)])
    if WHATSAPP_ACCOUNT:
        cmd.extend(["--account", WHATSAPP_ACCOUNT])
    return _run_openclaw_message_command(cmd, "whatsapp", context)


def _run_discord_delivery(target: str, message: str, cmd: list[str], context: str, image_path: Path | None = None) -> dict[str, Any]:
    direct_result = _send_discord_direct(target, message, context, image_path)
    if direct_result.get("ok"):
        return direct_result
    if NOTIFY_FALLBACK_OPENCLAW:
        fallback_result = _run_openclaw_discord_command(cmd, context)
        fallback_result["direct"] = direct_result
        return fallback_result
    _log(f"discord entrega ignorada {context} | direct_failed=true fallback_openclaw=false")
    return {"ok": False, "message_id": "", "method": "none", "status": "direct_failed_fallback_disabled", "direct": direct_result}


def _discord_worker() -> None:
    while True:
        target, message, cmd, context, image_path, outbox_base = _DISCORD_QUEUE.get()
        try:
            result = _run_discord_delivery(target, message, cmd, context, image_path)
            if outbox_base is not None:
                _append_outbox_record(
                    {
                        **outbox_base,
                        "recorded_at": _utc_iso(),
                        "event": "discord_delivery_result",
                        "delivery": {"discord": result},
                    }
                )
        finally:
            _DISCORD_QUEUE.task_done()
        if NOTIFY_MIN_INTERVAL_SECONDS > 0:
            time.sleep(NOTIFY_MIN_INTERVAL_SECONDS)


def _ensure_discord_worker() -> None:
    global _DISCORD_WORKER_STARTED
    if NOTIFY_BLOCKING or _DISCORD_WORKER_STARTED:
        return
    with _DISCORD_WORKER_LOCK:
        if _DISCORD_WORKER_STARTED:
            return
        thread = threading.Thread(target=_discord_worker, name="discord-notify-worker", daemon=True)
        thread.start()
        _DISCORD_WORKER_STARTED = True
        _log(f"discord worker iniciado | timeout={NOTIFY_TIMEOUT_SECONDS}s | queue_max={NOTIFY_QUEUE_MAX}")


def _enqueue_discord_delivery(
    target: str,
    message: str,
    cmd: list[str],
    context: str,
    image_path: Path | None = None,
    outbox_base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if NOTIFY_BLOCKING:
        result = _run_discord_delivery(target, message, cmd, context, image_path)
        if outbox_base is not None:
            _append_outbox_record(
                {
                    **outbox_base,
                    "recorded_at": _utc_iso(),
                    "event": "discord_delivery_result",
                    "delivery": {"discord": result},
                }
            )
        return {"queued": False, "status": "attempted", **result}

    _ensure_discord_worker()
    try:
        _DISCORD_QUEUE.put_nowait((target, message, cmd, context, image_path, outbox_base))
    except queue.Full:
        if NOTIFY_DROP_OLDEST:
            try:
                _DISCORD_QUEUE.get_nowait()
                _DISCORD_QUEUE.task_done()
                _log("discord queue cheia | alerta antigo descartado")
            except queue.Empty:
                pass
            try:
                _DISCORD_QUEUE.put_nowait((target, message, cmd, context, image_path, outbox_base))
            except queue.Full:
                _log(f"discord queue cheia | alerta novo descartado {context}")
                return {"queued": False, "ok": False, "status": "queue_full"}
        else:
            _log(f"discord queue cheia | alerta novo descartado {context}")
            return {"queued": False, "ok": False, "status": "queue_full"}
    _log(f"discord queued {context} queue={_DISCORD_QUEUE.qsize()}/{NOTIFY_QUEUE_MAX}")
    return {"queued": True, "ok": None, "status": "queued"}


def _send_discord(signals: list[dict[str, Any]]) -> None:
    if not signals:
        return
    target = DISCORD_TARGET if DISCORD_TARGET.startswith(("channel:", "user:")) else f"channel:{DISCORD_TARGET}" if DISCORD_TARGET else ""
    sent = 0
    for signal in signals:
        raw_message = _format_signal_notice(signal)
        whatsapp_message = _format_whatsapp_from_discord_notice(raw_message)
        structured_call = _structured_signal_call(signal)
        image_path = _signal_chart_image(signal)
        has_chart = image_path is not None and image_path.is_file()
        chart_path = image_path if has_chart else None
        outbox_base = {
            "recorded_at": _utc_iso(),
            "idempotency_key": structured_call["idempotency_key"],
            "structured_call": structured_call,
            "rendered": {
                "discord": raw_message,
                "whatsapp": whatsapp_message,
            },
            "chart_path": str(chart_path) if chart_path else "",
            "targets": {
                "discord": DISCORD_TARGET,
                "whatsapp": WHATSAPP_TARGET if NOTIFY_WHATSAPP else "",
            },
        }
        _append_outbox_record({**outbox_base, "event": "signal_detected"})
        delivery: dict[str, Any] = {}
        if DISCORD_TARGET:
            if REQUIRE_CHART_FOR_ENTRY and not has_chart:
                delivery["discord"] = {"status": "skipped", "reason": "chart_required_missing"}
                _log(
                    "discord skip | grafico obrigatorio indisponivel | whatsapp continua texto-only | "
                    f"exchange={signal.get('exchange', '')} symbol={signal.get('symbol', '')} setup={signal.get('setup', '')}"
                )
            else:
                message = _with_discord_message_prefix(raw_message)
                cmd = [
                    OPENCLAW_BIN,
                    "message",
                    "send",
                    "--channel",
                    "discord",
                    "--target",
                    target,
                    "--message",
                    message,
                ]
                if has_chart:
                    cmd.extend(["--media", str(chart_path)])
                if DISCORD_ACCOUNT:
                    cmd.extend(["--account", DISCORD_ACCOUNT])
                discord_result = _enqueue_discord_delivery(
                    target,
                    raw_message,
                    cmd,
                    f"sinais={len(signals)} mensagem={sent + 1}",
                    chart_path,
                    outbox_base,
                )
                delivery["discord"] = discord_result
                if discord_result.get("queued") or discord_result.get("ok"):
                    sent += 1
        whatsapp_result = _send_whatsapp(raw_message, f"sinais={len(signals)} mensagem={sent + 1}", chart_path)
        if NOTIFY_WHATSAPP:
            delivery["whatsapp"] = {
                "status": "sent" if whatsapp_result.get("ok") else "failed",
                "ok": bool(whatsapp_result.get("ok")),
                "source": "whatsapp",
                "source_message_id": whatsapp_result.get("message_id") or "",
                "source_channel_id": WHATSAPP_TARGET,
            }
        _append_outbox_record({**outbox_base, "recorded_at": _utc_iso(), "event": "publish_attempted", "delivery": delivery})


def _scan_once(state: dict[str, float]) -> list[dict[str, Any]]:
    now = time.time()
    signals: list[dict[str, Any]] = []
    for exchange_id in EXCHANGES:
        exchange_signals: list[dict[str, Any]] = []
        exchange_signal_count = 0
        try:
            _log(f"exchange start | {exchange_id}")
            exchange = _build_exchange(exchange_id)
        except Exception as exc:
            _log(f"exchange skip | {exchange_id} | {exc}")
            continue
        markets = getattr(exchange, "markets", {}) or {}
        resolved_symbols = _resolve_symbols_for_exchange(exchange)
        _log(f"exchange symbols | {exchange_id} | mode={SYMBOL_MODE} | count={len(resolved_symbols)}")
        for symbol in resolved_symbols:
            if markets and symbol not in markets:
                _log(f"symbol skip | {exchange_id} {symbol} | nao listado")
                continue
            base = _market_base_symbol(markets.get(symbol), symbol).upper()
            datasets: dict[str, pd.DataFrame] = {}
            for setup_key in SETUPS:
                if setup_key not in SETUP_CATALOG:
                    _log(f"setup skip | {setup_key} | desconhecido")
                    continue
                setup_allowed_assets = SETUP_ASSET_ALLOWLIST.get(setup_key)
                if setup_allowed_assets is not None and base not in setup_allowed_assets:
                    continue
                timeframe = _timeframe_for_setup(setup_key)
                try:
                    if timeframe not in datasets:
                        datasets[timeframe] = _fetch_dataset(exchange, symbol, timeframe)
                    signal = evaluate_setup_entry(setup_key, datasets[timeframe], hybrid_profile=HYBRID_PROFILE)
                except Exception as exc:
                    _log(f"scan erro | {exchange_id} {symbol} {setup_key} | {exc}")
                    continue
                if signal is None:
                    continue
                key = f"{exchange_id}:{symbol}:{setup_key}:{signal.side}"
                if now - state.get(key, 0.0) < DEDUP_SECONDS:
                    continue
                state[key] = now
                entry_price = float(getattr(signal, "reference_entry_price", 0.0) or 0.0)
                if entry_price <= 0:
                    try:
                        entry_price = float(datasets[timeframe].iloc[-1]["close"])
                    except Exception:
                        entry_price = 0.0
                stop_price = float(getattr(signal, "stop_price", 0.0) or 0.0)
                if stop_price <= 0:
                    stop_price = _stop_price_from_pct(entry_price, signal.side, TEST_STOP_LOSS_PCT)
                take_profit = float(getattr(signal, "take_profit", 0.0) or 0.0)
                if take_profit <= 0:
                    take_profit = _take_profit_price_from_pct(entry_price, signal.side, TEST_TAKE_PROFIT_PCT)
                targets = [
                    float(target)
                    for target in list(getattr(signal, "take_profit_targets", []) or [])
                    if float(target or 0.0) > 0
                ]
                if not targets and take_profit > 0:
                    targets = [take_profit]
                try:
                    bar_at = pd.Timestamp(datasets[timeframe].iloc[-1]["timestamp"]).isoformat()
                except Exception:
                    bar_at = ""
                payload = {
                    "exchange": exchange_id,
                    "symbol": symbol,
                    "setup": setup_key,
                    "side": signal.side,
                    "timeframe": signal.timeframe,
                    "reason": signal.reason,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "take_profit": take_profit,
                    "targets": targets,
                    "leverage": TEST_LEVERAGE,
                    "risk_profile": HYBRID_PROFILE,
                    "created_at": now,
                    "bar_at": bar_at,
                }
                signals.append(payload)
                exchange_signals.append(payload)
                exchange_signal_count += 1
                if _record_dashboard_signals is not None:
                    try:
                        _record_dashboard_signals([payload])
                    except Exception as exc:  # noqa: BLE001
                        _log(f"dashboard erro | {exchange_id} {symbol} {setup_key} | {exc}")
                targets_csv = ",".join(f"{target:.12g}" for target in targets)
                _log(
                    f"entry | {exchange_id} {symbol} | setup={setup_key} | side={signal.side} | timeframe={signal.timeframe} "
                    f"| entry={entry_price:.12g} | stop={stop_price:.12g} | tp={take_profit:.12g} | targets={targets_csv} | reason={signal.reason}"
                )
                if len(exchange_signals) >= MAX_SIGNALS_PER_BATCH:
                    _send_discord(exchange_signals)
                    exchange_signals.clear()
        if exchange_signals:
            _send_discord(exchange_signals)
        _log(f"exchange done | {exchange_id} | novos_sinais={exchange_signal_count}")
    return signals


def main() -> None:
    _log(
        "scanner iniciado | exchanges=%s | symbols=%s | quotes=%s | max_symbols=%s | setups=%s | interval=%ss"
        % (
            ",".join(EXCHANGES),
            SYMBOL_MODE if SYMBOL_MODE == "all-perps" else ",".join(RAW_SYMBOLS),
            ",".join(sorted(SYMBOL_QUOTES)) or "all",
            MAX_SYMBOLS_PER_EXCHANGE or "all",
            ",".join(SETUPS),
            INTERVAL_SECONDS,
        )
    )
    state = _load_state()
    while True:
        try:
            signals = _scan_once(state)
            _save_state(state)
            if not signals:
                _log("scan concluido | sem sinais novos")
        except Exception as exc:
            _log(f"scan fatal | {exc}")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
