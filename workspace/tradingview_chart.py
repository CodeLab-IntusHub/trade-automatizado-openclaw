"""Renderiza screenshot visual de trade para Discord.

Fonte visual canonica: widget publico do TradingView, carregado via `tv.js`,
com overlay local apenas para legenda, fonte e niveis operacionais do sinal.
Nao injeta Pine na entrega do Discord por padrao. A entrega funcional atual
usa estudos nativos do TradingView + overlay operacional do sinal.
O renderer estatico via CCXT fica apenas como fallback/debug explicito por env,
mantendo o contrato publico `render_tradingview_chart(signal) -> Path`.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import ccxt  # type: ignore
except Exception:  # noqa: BLE001
    ccxt = None

ROOT = Path(__file__).resolve().parent
SKILL_ID = "trade-automatizado-openclaw"
TRADE_NOTICE_TZ = ZoneInfo("America/Sao_Paulo")

SETUP_STUDIES: dict[str, dict[str, Any]] = {
    "btc-intraday-short-breakdown": {
        "label": "BTC Intraday Short Breakdown · EMA2d/EMA6d + Volume/SMA50 + ATR",
        "mode": "btc-intraday-short-breakdown",
        "studies": [
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 576}, "color": "#00D4FF", "lineWidth": 2},
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 1728}, "color": "#A855F7", "lineWidth": 2},
        ],
    },
    "bollinger-mean-reversion": {
        "label": "Bollinger Bands + RSI + Volume",
        "mode": "bollinger",
        "studies": [
            {"id": "BB@tv-basicstudies", "version": 60},
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "low-stoch-storm": {
        "label": "EMAs 8/21/80 + Estocástico Lento 14,3,3 + RSI14 separado (perfil nativo simplificado)",
        "mode": "low-stoch",
        "studies": [
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 8}, "color": "#FF7000", "lineWidth": 2},
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 21}, "color": "#0088FA", "lineWidth": 2},
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 80}, "color": "#FA00D0", "lineWidth": 2},
            {"id": "Stochastic@tv-basicstudies", "version": 60, "inputs": {"periodK": 14, "smoothK": 3, "periodD": 3}},
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "divergence-and-volume-15m": {
        "label": "RSI + Volume",
        "mode": "divergence",
        "studies": [
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "divergence-and-volume-1h": {
        "label": "RSI + Volume",
        "mode": "divergence",
        "studies": [
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "divergence-and-volume-4h": {
        "label": "RSI + Volume",
        "mode": "divergence",
        "studies": [
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "grid": {
        "label": "SMA50 + RSI",
        "mode": "grid",
        "studies": [
            {"id": "MASimple@tv-basicstudies", "version": 60, "inputs": {"length": 50}},
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "grid-strict": {
        "label": "SMA50 + RSI",
        "mode": "grid",
        "studies": [
            {"id": "MASimple@tv-basicstudies", "version": 60, "inputs": {"length": 50}},
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
    "institutional-strict": {
        "label": "EMA9/21/50 + MACD + RSI + Volume",
        "mode": "institutional",
        "studies": [
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 9}, "color": "#FF7000", "lineWidth": 2},
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 21}, "color": "#0088FA", "lineWidth": 2},
            {"id": "MAExp@tv-basicstudies", "version": 60, "inputs": {"length": 50}, "color": "#FA00D0", "lineWidth": 2},
            {"id": "MACD@tv-basicstudies", "version": 60},
            {"id": "RSI@tv-basicstudies", "version": 60},
        ],
    },
}

_TIMEFRAME_TO_TV = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "d": "D",
}
_TV_TO_CCXT = {"1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "240": "4h", "D": "1d"}
_RANGE_BY_INTERVAL = {"1": "1D", "3": "1D", "5": "1D", "15": "5D", "30": "5D", "60": "5D", "240": "1M", "D": "6M"}
PUBLIC_TARGET_R_MULTIPLES = (1.0, 1.5, 2.0, 2.5)
PUBLIC_TARGET_WEIGHTS = (0.25, 0.25, 0.25, 0.25)


def _setup_key(signal: dict[str, Any]) -> str:
    return str(signal.get("setup") or signal.get("setup_key") or "").strip().lower().replace("_", "-")


def _env_setup_key(setup: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", setup.upper()).strip("_")


def _parse_study_env(raw: str) -> list[str]:
    raw = str(raw or "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def _pine_studies_for_setup(setup: str) -> list[str]:
    enabled = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_PINE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "sim"}
    if not enabled:
        return []
    setup_key = _env_setup_key(setup)
    candidates = [
        f"SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_{setup_key}",
        f"SETUP_NOTIFY_TRADINGVIEW_STUDIES_{setup_key}",
    ]
    # Alias operacional: divergence-and-volume sem sufixo usa a variante 1h.
    if setup == "divergence-and-volume":
        candidates.append("SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_1H")
    for env_key in candidates:
        studies = _parse_study_env(os.environ.get(env_key, ""))
        if studies:
            return studies
    return []


def _base_quote(symbol: str, default_quote: str | None = None) -> tuple[str, str]:
    default_quote = default_quote or os.environ.get("SETUP_NOTIFY_TRADINGVIEW_DEFAULT_QUOTE", "USDT")
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("-", "/")
    if "/" in cleaned:
        base, quote = cleaned.split("/", 1)
        return base.strip(), (quote.strip() or default_quote)
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            return cleaned[: -len(quote)], quote
    return cleaned or "BTC", default_quote


def _ccxt_to_tradingview_exchange(exchange_id: str) -> str:
    mapping = {
        "hyperliquid": "HYPERLIQUID",
        "bybit": "BYBIT",
        "binanceusdm": "BINANCE",
        "binance": "BINANCE",
        "okx": "OKX",
        "bitget": "BITGET",
        "gateio": "GATEIO",
        "mexc": "MEXC",
        "kucoinfutures": "KUCOIN",
        "kucoin": "KUCOIN",
        "krakenfutures": "KRAKEN",
        "kraken": "KRAKEN",
    }
    return mapping.get(str(exchange_id or "").lower(), str(exchange_id or "BYBIT").upper())


def tradingview_symbol(symbol: str, setup: str = "", exchange: str = "") -> str:
    return tradingview_symbol_candidates(symbol, setup=setup, exchange=exchange)[0]


def tradingview_symbol_candidates(symbol: str, setup: str = "", exchange: str = "") -> list[str]:
    base, quote = _base_quote(symbol)
    setup_env = _env_setup_key(setup)
    override = os.environ.get(f"SETUP_NOTIFY_TRADINGVIEW_SYMBOL_{setup_env}", "").strip() if setup_env else ""
    tv_exchange = (exchange or os.environ.get("SETUP_NOTIFY_TRADINGVIEW_EXCHANGE", "BYBIT")).strip().upper()
    suffix = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_PERP_SUFFIX", ".P")
    if override:
        first = override.format(base=base, quote=quote, exchange=tv_exchange, suffix=suffix)
    else:
        first = f"{tv_exchange}:{base}{quote}{suffix}"
    exchanges = os.environ.get(
        "SETUP_NOTIFY_TRADINGVIEW_SYMBOL_FALLBACK_EXCHANGES",
        "HYPERLIQUID,BYBIT,BINANCE,OKX,BITGET,KRAKEN,COINBASE",
    )
    suffixes = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_SYMBOL_FALLBACK_SUFFIXES", f"{suffix},").split(",")
    quote_candidates = [quote]
    # Hyperliquid perps frequently originate as USDC in CCXT while TradingView
    # may expose the same market as USD/USDC depending on asset. Try both before
    # falling back to other venues, preserving explicit symbol overrides above.
    if quote in {"USDT", "USDC"}:
        quote_candidates.append("USD")
    if quote == "USD":
        quote_candidates.append("USDC")
    candidates = [first]
    for ex in [tv_exchange, *[x.strip().upper() for x in exchanges.split(",") if x.strip()]]:
        for q in quote_candidates:
            for suf in suffixes:
                candidates.append(f"{ex}:{base}{q}{suf.strip()}")
    return list(dict.fromkeys([c for c in candidates if c and ":" in c]))


def _preferred_tradingview_exchange(exchange_id: str) -> str:
    if os.environ.get("SETUP_NOTIFY_TRADINGVIEW_SYMBOL_PREFLIGHT", "true").strip().lower() in {"0", "false", "no", "nao"}:
        return ""
    return _ccxt_to_tradingview_exchange(exchange_id)


def _chart_interval(signal: dict[str, Any]) -> str:
    setup = _setup_key(signal)
    override = os.environ.get(f"SETUP_NOTIFY_TRADINGVIEW_INTERVAL_{_env_setup_key(setup)}", "").strip()
    if override:
        return override
    raw = str(signal.get("timeframe") or "15m").strip().lower()
    return _TIMEFRAME_TO_TV.get(raw, raw.upper() if raw == "d" else raw)


def _chart_range(interval: str, setup: str) -> str:
    setup_override = os.environ.get(f"SETUP_NOTIFY_TRADINGVIEW_RANGE_{_env_setup_key(setup)}", "").strip()
    generic_override = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_RANGE", "").strip()
    return setup_override or generic_override or _RANGE_BY_INTERVAL.get(interval, "5D")


def _default_tradingview_profile_dir() -> Path:
    return Path.home() / ".openclaw" / "state" / SKILL_ID / "tradingview-profile"


def _requested_renderer(setup: str = "") -> str:
    renderer = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_RENDERER", "widget").strip().lower()
    managed_values = {"managed", "managed-layout", "full", "full-chart", "chart"}
    if renderer in managed_values:
        return "managed-layout"
    return renderer


def _managed_layout_url(setup: str) -> str:
    setup_key = _env_setup_key(setup)
    for env_key in [
        f"SETUP_NOTIFY_TRADINGVIEW_LAYOUT_URL_{setup_key}",
        f"SETUP_NOTIFY_TRADINGVIEW_MANAGED_LAYOUT_URL_{setup_key}",
        "SETUP_NOTIFY_TRADINGVIEW_LAYOUT_URL",
    ]:
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    path = ROOT.parent / "references" / "pine-setups" / "tradingview-managed-layouts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        layout = (data.get("layouts") or {}).get(setup) or {}
        return str(layout.get("layout_url") or "").strip()
    except Exception:
        return ""


def _output_dir() -> Path:
    raw = os.environ.get(
        "SETUP_NOTIFY_TRADINGVIEW_OUTPUT_DIR",
        str(Path.home() / ".openclaw" / "state" / SKILL_ID / "tradingview-charts"),
    )
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _coerce_price_list(value: Any) -> list[float]:
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    out: list[float] = []
    for item in value or []:
        try:
            price = float(item)
        except (TypeError, ValueError):
            continue
        if price > 0:
            out.append(price)
    return out


def _price(value: Any) -> float | None:
    try:
        price = float(str(value).strip().replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _r_multiple_targets(signal: dict[str, Any]) -> list[float]:
    try:
        entry = float(signal.get("entry_price") or signal.get("reference_entry_price") or signal.get("entry") or 0.0)
        stop = float(signal.get("stop_price") or signal.get("stop") or 0.0)
    except (TypeError, ValueError):
        return []
    if entry <= 0 or stop <= 0 or abs(entry - stop) < 1e-12:
        return []
    side = str(signal.get("side") or "").strip().lower()
    if not side:
        side = "long" if stop < entry else "short"
    risk = abs(entry - stop)
    if side in {"short", "sell", "vendido", "venda"}:
        return [float(entry - risk * multiple) for multiple in PUBLIC_TARGET_R_MULTIPLES]
    return [float(entry + risk * multiple) for multiple in PUBLIC_TARGET_R_MULTIPLES]


def _normalize_targets(signal: dict[str, Any]) -> list[float]:
    # Prioridade operacional: targets > targets_csv > take_profit_targets > take_profit.
    # Se nenhum alvo vier no sinal, mas entrada/stop estiverem disponíveis, usa
    # a régua pública 1R/1.5R/2R/2.5R como fallback defensivo do renderer.
    targets = signal.get("targets")
    if not targets:
        targets = signal.get("targets_csv")
    if not targets:
        targets = signal.get("take_profit_targets")
    if isinstance(targets, str):
        targets = [item.strip() for item in targets.split(",") if item.strip()]
    out = _coerce_price_list(targets)
    if not out and signal.get("take_profit"):
        out = _coerce_price_list([signal.get("take_profit")])
    if not out:
        out = _r_multiple_targets(signal)
    return out[:4]


def _signal_time_payload(signal: dict[str, Any]) -> dict[str, str]:
    raw = (
        signal.get("entry_time_utc")
        or signal.get("signal_time_utc")
        or signal.get("timestamp_utc")
        or signal.get("entry_time")
        or signal.get("timestamp")
        or ""
    )
    if not raw:
        return {}
    try:
        value = str(raw).strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)
        dt_brt = dt_utc.astimezone(TRADE_NOTICE_TZ)
        return {
            "signal_time_utc": dt_utc.isoformat(),
            "signal_time_brt": dt_brt.isoformat(),
            "signal_date": dt_brt.strftime("%Y-%m-%d"),
            "signal_time": dt_brt.strftime("%H:%M"),
            "signal_label": dt_brt.strftime("%d/%m/%Y %H:%M BRT"),
        }
    except Exception:
        return {"signal_time_utc": str(raw)}


def _indicator_checks(signal: dict[str, Any], setup: str) -> list[str]:
    raw = signal.get("indicator_checks") or signal.get("setup_checks") or signal.get("chart_checks")
    if isinstance(raw, str):
        return [item.strip() for item in re.split(r"[|;\n]+", raw) if item.strip()][:8]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()][:8]
    if setup == "btc-intraday-short-breakdown":
        checks = ["TF 5m"]
        initial_ret = signal.get("initial_ret_pct")
        atr_pct = signal.get("atr_pct")
        vol_mult = signal.get("vol_mult") or signal.get("volume_multiplier") or "1.5"
        try:
            checks.append(f"queda janela 11:00–11:30 BRT {float(initial_ret):.2f}%")
        except Exception:
            checks.append("queda janela 11:00–11:30 BRT")
        checks.append(f"volume janela ≥ {vol_mult}x SMA50")
        checks.append("EMA 2d > EMA 6d")
        try:
            checks.append(f"ATR mínimo OK ({float(atr_pct):.2f}%)")
        except Exception:
            checks.append("ATR mínimo OK")
        return checks[:8]
    return []


def _fibonacci_levels(signal: dict[str, Any], targets: list[float]) -> list[dict[str, float | str]]:
    raw = signal.get("fibonacci_levels") or signal.get("fib_levels")
    parsed: list[dict[str, float | str]] = []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        for idx, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                price = _price(item.get("price") or item.get("value"))
                label = str(item.get("label") or item.get("ratio") or f"Fib {idx}").strip()
            else:
                price = _price(item)
                label = f"Fib {idx}"
            if price is not None:
                parsed.append({"label": label, "price": price})
    if parsed:
        return parsed[:4]
    return []


def _resolve_ccxt_exchange(signal: dict[str, Any]):
    if ccxt is None:
        raise RuntimeError("ccxt indisponivel")
    preferred = str(signal.get("exchange") or os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_PRIMARY", "bybit")).strip().lower()
    candidates = [preferred]
    extra = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_EXCHANGES", "binanceusdm,bybit,okx,bitget,gateio,mexc,kucoinfutures,krakenfutures")
    candidates.extend(item.strip().lower() for item in extra.split(",") if item.strip())
    seen: set[str] = set()
    for exchange_id in candidates:
        if exchange_id in seen or not hasattr(ccxt, exchange_id):
            continue
        seen.add(exchange_id)
        exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_TIMEOUT_MS", "8000"))})
        try:
            exchange.load_markets()
            return exchange
        except Exception:
            continue
    raise RuntimeError("nenhuma exchange CCXT publica disponivel para candles")


def _iter_ccxt_exchanges(signal: dict[str, Any]):
    if ccxt is None:
        raise RuntimeError("ccxt indisponivel")
    preferred = str(signal.get("exchange") or os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_PRIMARY", "binanceusdm")).strip().lower()
    extra = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_EXCHANGES", "binanceusdm,bybit,okx,bitget,gateio,mexc,kucoinfutures,krakenfutures")
    candidates = [preferred, *(item.strip().lower() for item in extra.split(",") if item.strip())]
    seen: set[str] = set()
    for exchange_id in candidates:
        if exchange_id in seen or not hasattr(ccxt, exchange_id):
            continue
        seen.add(exchange_id)
        exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CCXT_TIMEOUT_MS", "8000"))})
        try:
            exchange.load_markets()
            yield exchange
        except Exception:
            continue


def _resolve_market_symbol(exchange: Any, symbol: str) -> str:
    base, quote = _base_quote(symbol)
    candidates = [
        symbol,
        symbol.replace("-", "/"),
        f"{base}/{quote}:{quote}",
        f"{base}/{quote}",
        f"{base}{quote}",
    ]
    markets = getattr(exchange, "markets", {}) or {}
    by_id = getattr(exchange, "markets_by_id", {}) or {}
    for candidate in candidates:
        if candidate in markets:
            return candidate
        if candidate in by_id:
            market = by_id[candidate]
            if isinstance(market, list) and market:
                return market[0].get("symbol") or candidate
            if isinstance(market, dict):
                return market.get("symbol") or candidate
    compact = f"{base}{quote}".replace("/", "")
    for market in markets.values():
        mid = str(market.get("id") or "").upper().replace("-", "")
        msym = str(market.get("symbol") or "").upper().replace("/", "").replace(":", "")
        if compact in {mid, msym} or mid.startswith(compact):
            return market.get("symbol") or f"{base}/{quote}"
    return f"{base}/{quote}:{quote}"


def _fetch_ohlcv(signal: dict[str, Any], interval: str) -> tuple[list[list[float]], str, str]:
    timeframe = _TV_TO_CCXT.get(interval, str(signal.get("timeframe") or "15m"))
    limit = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CANDLE_LIMIT") or os.environ.get("SETUP_NOTIFY_TRADINGVIEW_CANDLES", "160"))
    errors: list[str] = []
    for exchange in _iter_ccxt_exchanges(signal):
        exchange_id = getattr(exchange, "id", "ccxt")
        market_symbol = _resolve_market_symbol(exchange, str(signal.get("symbol") or ""))
        try:
            candles = exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, limit=limit)
            if candles:
                return candles, exchange_id, market_symbol
            errors.append(f"{exchange_id} {market_symbol}: sem candles retornados")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{exchange_id} {market_symbol}: {exc}")
            continue
    detail = " | ".join(errors[-5:]) if errors else "nenhuma exchange CCXT publica disponivel para candles"
    raise RuntimeError(f"sem candles publicos para {signal.get('symbol')}: {detail}")


def _exchange_label(exchange_id: str) -> str:
    labels = {
        "bybit": "Bybit",
        "binanceusdm": "Binance Futures",
        "okx": "OKX",
        "bitget": "Bitget",
        # Evita autolink do Discord/Telegram para gate.io quando a fonte aparecer
        # em texto/rodapé de entrega.
        "gateio": "Gate IO",
        "mexc": "MEXC",
        "kucoinfutures": "KuCoin Futures",
        "krakenfutures": "Kraken Futures",
    }
    return labels.get(str(exchange_id or "").lower(), str(exchange_id or "CCXT").upper())


def _source_line(exchange_id: str, market_symbol: str, interval: str, tv_symbol: str = "") -> str:
    pair = str(market_symbol or "").split(":", 1)[0].replace("-", "/") or "N/A"
    market_type = "perp" if ":" in str(market_symbol or "") or str(market_symbol or "").upper().endswith(".P") else "spot/perp público"
    timeframe = _TV_TO_CCXT.get(interval, interval)
    generated = datetime.now(TRADE_NOTICE_TZ).strftime("%d/%m/%Y %H:%M")
    tv = f"TradingView {tv_symbol} · " if tv_symbol else "TradingView widget · "
    return f"Fonte: {tv}{_exchange_label(exchange_id)} via CCXT · {pair} {market_type} · {timeframe} · candles públicos · gerado em {generated} BRT"


def _study_override_prefix(study_id: str) -> str | None:
    mapping = {
        "MAExp@tv-basicstudies": "moving average exponential",
        "MASimple@tv-basicstudies": "moving average",
        "BB@tv-basicstudies": "bollinger bands",
        "RSI@tv-basicstudies": "relative strength index",
        "Stochastic@tv-basicstudies": "stochastic",
        "MACD@tv-basicstudies": "macd",
    }
    return mapping.get(study_id)


def _study_runtime_name(study_id: str) -> str | None:
    mapping = {
        "MAExp@tv-basicstudies": "Moving Average Exponential",
        "MASimple@tv-basicstudies": "Moving Average",
        "Stochastic@tv-basicstudies": "Stochastic",
    }
    return mapping.get(study_id)


def _expected_study_title(study_id: str, inputs: dict[str, Any] | None) -> str:
    inputs = inputs or {}
    length = inputs.get("length") or inputs.get("in_0")
    if study_id == "MAExp@tv-basicstudies":
        return f"EMA ({int(length or 9)}"
    if study_id == "MASimple@tv-basicstudies":
        return f"MA ({int(length or 9)}"
    if study_id == "BB@tv-basicstudies":
        return f"BB ({int(length or 20)}"
    if study_id == "RSI@tv-basicstudies":
        return f"RSI ({int(length or 14)}"
    if study_id == "Stochastic@tv-basicstudies":
        period_k = int(inputs.get("periodK") or inputs.get("length") or inputs.get("in_0") or 14)
        smooth_k = int(inputs.get("smoothK") or inputs.get("smooth") or inputs.get("in_1") or 3)
        period_d = int(inputs.get("periodD") or inputs.get("smoothD") or inputs.get("in_2") or 3)
        return f"Stoch ({period_k}, {smooth_k}, {period_d})"
    if study_id == "MACD@tv-basicstudies":
        return "MACD (12, 26"
    return study_id


def _tradingview_study_payload(study: dict[str, Any]) -> tuple[list[str], dict[str, Any], list[str], list[dict[str, Any]]]:
    items = [item for item in (study.get("studies") or []) if item]
    ids: list[str] = []
    expected: list[str] = []
    counts: dict[str, int] = {}
    for item in items:
        study_id = str(item.get("id") if isinstance(item, dict) else item or "")
        if not study_id:
            continue
        ids.append(study_id)
        counts[study_id] = counts.get(study_id, 0) + 1
        expected.append(_expected_study_title(study_id, item.get("inputs") if isinstance(item, dict) else {}))

    # O widget público aceita `studies_overrides`, mas o override é global por
    # tipo de estudo. Portanto só é seguro aplicar inputs quando há uma única
    # instância daquele indicador. Multi-EMA com períodos diferentes exige
    # Pine/layout canônico; caso contrário a validação pós-render bloqueia.
    overrides: dict[str, Any] = {}
    patches: list[dict[str, Any]] = []
    ema_colors = ["#00D4FF", "#F2C94C", "#A855F7", "#22C55E"]
    ema_idx = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        study_id = str(item.get("id") or "")
        inputs = item.get("inputs") or {}
        runtime_name = _study_runtime_name(study_id)
        patch: dict[str, Any] = {}
        if runtime_name and isinstance(inputs, dict) and inputs:
            patch = {"name": runtime_name, "id": study_id, "inputs": dict(inputs), "lineWidth": int(item.get("lineWidth") or item.get("linewidth") or 2)}
            if item.get("color"):
                patch["color"] = str(item.get("color"))
            elif study_id == "MAExp@tv-basicstudies":
                patch["color"] = ema_colors[ema_idx % len(ema_colors)]
            ema_idx += 1 if study_id == "MAExp@tv-basicstudies" else 0
            patches.append(patch)
        if not study_id or not isinstance(inputs, dict) or counts.get(study_id, 0) != 1:
            continue
        prefix = _study_override_prefix(study_id)
        if not prefix:
            continue
        if "length" in inputs:
            overrides[f"{prefix}.length"] = inputs["length"]
        if study_id == "Stochastic@tv-basicstudies":
            period_k = int(inputs.get("periodK") or inputs.get("length") or inputs.get("in_0") or 14)
            smooth_k = int(inputs.get("smoothK") or inputs.get("smooth") or inputs.get("in_1") or 3)
            period_d = int(inputs.get("periodD") or inputs.get("smoothD") or inputs.get("in_2") or 3)
            for stochastic_prefix in {prefix, study_id}:
                overrides[f"{stochastic_prefix}.periodK"] = period_k
                overrides[f"{stochastic_prefix}.smoothK"] = smooth_k
                overrides[f"{stochastic_prefix}.periodD"] = period_d
    return ids, overrides, expected, patches


def _html_config(signal: dict[str, Any], candles: list[list[float]], exchange_id: str, market_symbol: str, tv_symbol: str | None = None) -> str:
    setup = _setup_key(signal)
    interval = _chart_interval(signal)
    study = SETUP_STUDIES.get(setup, {"label": "Momentum + Volume", "mode": "generic", "studies": []})
    pine_studies = _pine_studies_for_setup(setup)
    native_studies, native_overrides, native_expected, native_patches = _tradingview_study_payload(study)
    targets = _normalize_targets(signal)
    tv_exchange = _preferred_tradingview_exchange(exchange_id)
    symbol_candidates = tradingview_symbol_candidates(str(signal.get("symbol") or market_symbol), setup=setup, exchange=tv_exchange)
    tv_symbol = tv_symbol or symbol_candidates[0]
    static_renderer = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_STATIC_RENDERER", "false").strip().lower() in {"1", "true", "yes", "sim"}
    renderer = _requested_renderer(setup)
    payload = {
        "symbol": str(signal.get("symbol") or market_symbol),
        "market_symbol": market_symbol,
        "exchange_id": exchange_id,
        "tradingview_symbol": tv_symbol,
        "tradingview_symbols": symbol_candidates,
        "setup": setup,
        "setup_label": str(signal.get("setup_label") or study.get("label") or setup),
        "indicator_label": "Pine canônico do setup" if pine_studies else study.get("label"),
        "studies": pine_studies or native_studies,
        "studies_overrides": {} if pine_studies else native_overrides,
        "expected_studies": [] if pine_studies else native_expected,
        "study_patches": [] if pine_studies else native_patches,
        "pine_studies_configured": bool(pine_studies),
        "mode": study.get("mode"),
        "interval": interval,
        "range": _chart_range(interval, setup),
        "tradingview_layout_url": _managed_layout_url(setup) if renderer == "managed-layout" else "",
        "side": str(signal.get("side") or "").upper() or "N/A",
        "entry": float(signal.get("entry_price") or signal.get("entry") or 0.0),
        "stop": float(signal.get("stop_price") or signal.get("stop") or 0.0),
        "targets": targets,
        "fibonacci_levels": _fibonacci_levels(signal, targets),
        "target_weights": _coerce_price_list(signal.get("target_weights") or list(PUBLIC_TARGET_WEIGHTS))[: len(targets)],
        "reason": str(signal.get("reason") or "Setup detectado."),
        "source_text": _source_line(exchange_id, market_symbol, interval, tv_symbol=tv_symbol),
        "candles": candles,
        "locale": os.environ.get("SETUP_NOTIFY_TRADINGVIEW_LOCALE", "en"),
        "timezone": os.environ.get("SETUP_NOTIFY_TRADINGVIEW_TIMEZONE", "Etc/UTC"),
        "indicator_checks": _indicator_checks(signal, setup),
        "show_risk_reward_zones": bool(signal.get("show_risk_reward_zones", os.environ.get("SETUP_NOTIFY_TRADINGVIEW_SHOW_RR_ZONES", "true").strip().lower() in {"1", "true", "yes", "sim"})),
        **_signal_time_payload(signal),
    }
    if static_renderer or renderer in {"static", "ccxt", "canvas"}:
        payload["renderer"] = "static-ccxt-fallback"
        return _static_chart_html(payload)
    native_only = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_NATIVE_ONLY", "true").strip().lower() in {"1", "true", "yes", "sim"}
    payload["native_only"] = native_only
    if renderer == "managed-layout":
        payload["renderer"] = "tradingview-managed-layout"
    else:
        payload["renderer"] = "tradingview-widget-native" if native_only else ("tradingview-widget-pine" if pine_studies else "tradingview-widget-native-fallback")
    return _tradingview_widget_html(payload)


def _tradingview_widget_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    title = html.escape(str(payload.get("symbol") or "N/A"))
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>{title}</title>
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#05070a;color:#e8eef5;font-family:Inter,Arial,sans-serif}}
#wrap{{width:100vw;height:100vh;position:relative;background:#05070a}}
#tv_chart{{position:absolute;inset:0 0 36px 0}}
#overlay{{position:absolute;inset:0 0 36px 0;pointer-events:none}}
#meta{{position:absolute;left:24px;top:10px;padding:8px 12px;border-radius:10px;background:rgba(5,7,10,.62);border:1px solid rgba(148,163,184,.22);backdrop-filter:blur(3px)}}
#meta .title{{font-size:20px;font-weight:800;color:#f8fafc}}
#meta .sub{{margin-top:3px;font-size:12px;color:#cbd5e1}}
#levels{{position:absolute;right:28px;top:92px;width:278px;padding:12px;border-radius:14px;background:rgba(5,7,10,.74);border:1px solid rgba(148,163,184,.25);backdrop-filter:blur(4px)}}
.level{{display:flex;justify-content:space-between;gap:12px;margin:6px 0;font-size:13px;color:#e2e8f0}}
.level small{{display:block;font-size:10px;font-weight:600;color:#94a3b8;line-height:1.1}}
.outside{{opacity:.78;color:#94a3b8}}
#footer{{position:absolute;left:0;right:0;bottom:0;height:36px;display:flex;align-items:center;padding:0 22px;background:#05070a;border-top:1px solid #1e293b;color:#f2c94c;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#slow_panel{{display:none}}
.line-label{{position:absolute;right:318px;transform:translateY(-50%);padding:3px 8px;border-radius:7px;background:rgba(5,7,10,.78);font-size:12px;font-weight:800;white-space:nowrap}}
.hline{{position:absolute;left:24px;right:312px;height:0;border-top:2px dashed;opacity:.95}}
</style></head><body><div id='wrap'><div id='tv_chart'></div><div id='overlay'><div id='meta'><div class='title'></div><div class='sub'></div></div><div id='levels'></div></div><canvas id='slow_panel'></canvas><div id='footer'></div></div>
<script src='https://s3.tradingview.com/tv.js'></script>
<script>
const P = {data};
window.P = P;
const nativeOnly = Boolean(P.native_only);
const colors = {{entry:'#22c55e', stop:'#ef4444', target:'#f2c94c'}};
function fmt(v){{v=Number(v||0); if(!v) return 'N/A'; const a=Math.abs(v); const d=a>=1000?2:a>=1?4:a>=.01?5:a>=.0001?6:8; return '$'+v.toFixed(d).replace(/[.]?0+$/,'');}}
function levelData(){{
  return [
    ['ENTRADA', Number(P.entry||0), colors.entry],
    ['STOP', Number(P.stop||0), colors.stop],
    ...((P.targets || []).slice(0,4).map((v,i)=>[`ALVO ${{i+1}}`, Number(v||0), colors.target]))
  ].filter(x => x[1]);
}}
document.querySelector('#meta .title').textContent = `${{P.symbol}} — ${{P.side}}`;
document.querySelector('#meta .sub').textContent = `${{P.setup_label}} · ${{P.indicator_label}} · TF ${{P.interval}} · ${{P.renderer}}`;
document.querySelector('#footer').textContent = String(P.source_text || 'Fonte: TradingView widget');
let tvWidget = null;
function initWidget(){{
  if (!window.TradingView) return setTimeout(initWidget, 300);
  tvWidget = new TradingView.widget({{
    autosize: true,
    symbol: P.tradingview_symbol,
    interval: P.interval,
    timezone: P.timezone || 'Etc/UTC',
    theme: 'dark',
    style: '1',
    locale: P.locale || 'en',
    toolbar_bg: '#121212',
    backgroundColor: 'rgba(18, 18, 18, 1)',
    gridColor: 'rgba(55, 55, 55, 0.45)',
    enable_publishing: false,
    allow_symbol_change: false,
    hide_side_toolbar: true,
    hide_top_toolbar: false,
    hide_legend: true,
    save_image: true,
    calendar: false,
    details: false,
    hideideas: true,
    hide_volume: false,
    withdateranges: true,
    studies_overrides: P.studies_overrides || {{}},
    studies: P.studies || [],
    container_id: 'tv_chart'
  }});
  window.tvWidget = tvWidget;
  if (tvWidget && typeof tvWidget.onChartReady === 'function') {{
    tvWidget.onChartReady(() => {{
      enforceSetupInterval();
      setTimeout(enforceSetupInterval, 600);
      setTimeout(enforceSetupInterval, 1500);
      setTimeout(drawTradingViewLevels, 1800);
    }});
  }}
}}
function enforceSetupInterval() {{
  try {{
    const desired = String(P.interval || '240');
    const chart = tvWidget && ((typeof tvWidget.activeChart === 'function' && tvWidget.activeChart()) || (typeof tvWidget.chart === 'function' && tvWidget.chart()));
    if (chart && typeof chart.setResolution === 'function') chart.setResolution(desired);
  }} catch (err) {{
    console.warn('TradingView interval enforcement unavailable', err);
  }}
}}
initWidget();
function drawTradingViewLevels(){{
  try {{
    const chart = tvWidget && ((typeof tvWidget.activeChart === 'function' && tvWidget.activeChart()) || (typeof tvWidget.chart === 'function' && tvWidget.chart()));
    if (!chart) return false;
    const last = (P.candles || [])[Math.max((P.candles || []).length - 1, 0)] || [];
    const time = Math.floor(Number(last[0] || Date.now()) / 1000);
    for (const [label, price, color] of levelData()) {{
      const opts = {{
        shape: 'horizontal_line',
        text: `${{label}} ${{fmt(price)}}`,
        lock: true,
        disableSelection: true,
        disableSave: true,
        overrides: {{
          linecolor: color,
          linewidth: 2,
          linestyle: 2,
          textcolor: color,
          showLabel: true
        }}
      }};
      if (typeof chart.createShape === 'function') chart.createShape({{time, price}}, opts);
      else if (typeof chart.createMultipointShape === 'function') chart.createMultipointShape([{{time, price}}], opts);
    }}
    return true;
  }} catch (err) {{
    console.warn('TradingView native level drawings unavailable', err);
    return false;
  }}
}}
function candleRange(){{
  const candles = (P.candles || []).slice(-120).map(r => ({{h:Number(r[2]), l:Number(r[3])}})).filter(r => r.h && r.l);
  let minP = Math.min(...candles.map(r => r.l));
  let maxP = Math.max(...candles.map(r => r.h));
  if (!Number.isFinite(minP) || !Number.isFinite(maxP) || minP === maxP) {{ minP = Number(P.entry||1)*.98; maxP = Number(P.entry||1)*1.02; }}
  const pad = (maxP - minP) * 0.04 || maxP * 0.005 || 1;
  return {{min:minP-pad, max:maxP+pad, rawMin:minP, rawMax:maxP}};
}}
function drawLevels(){{
  const overlay = document.getElementById('overlay');
  const levelsBox = document.getElementById('levels');
  levelsBox.innerHTML = '';
  overlay.querySelectorAll('.hline,.line-label').forEach(el => el.remove());
  const range = candleRange();
  for (const [label, price, color] of levelData()) {{
    const row = document.createElement('div'); row.className = 'level';
    const outside = price < range.rawMin || price > range.rawMax;
    row.innerHTML = `<span>${{label}}${{outside ? '<small>fora da janela atual</small>' : ''}}</span><strong style="color:${{color}}">${{fmt(price)}}</strong>`;
    levelsBox.appendChild(row);
    if (outside) {{ row.classList.add('outside'); row.title = 'Nível fora da janela recente dos candles; não desenhado por overlay local para evitar traço falso.'; }}
  }}
}}
setTimeout(drawLevels, 1200);
window.addEventListener('resize', () => {{ drawLevels(); }});
</script></body></html>"""


def _static_chart_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    title = html.escape(str(payload.get("symbol") or "N/A"))
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>{title}</title>
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#0b0f14;color:#e8eef5;font-family:Inter,Arial,sans-serif}}
#wrap{{width:100vw;height:100vh;position:relative;background:linear-gradient(180deg,#0b0f14,#07090d)}}
#chart{{width:100%;height:100%}}
</style></head><body><div id='wrap'><canvas id='chart'></canvas></div>
<script>
const P = {data};
const canvas = document.getElementById('chart');
const dpr = window.devicePixelRatio || 1;
canvas.width = Math.floor(innerWidth * dpr); canvas.height = Math.floor(innerHeight * dpr);
canvas.style.width = innerWidth+'px'; canvas.style.height = innerHeight+'px';
const ctx = canvas.getContext('2d'); ctx.scale(dpr,dpr);
const W=innerWidth,H=innerHeight;
const C={{bg:'#0b0f14',panel:'#101722',grid:'#213044',text:'#e8eef5',muted:'#94a3b8',green:'#22c55e',red:'#ef4444',yellow:'#f2c94c',blue:'#60a5fa',purple:'#a78bfa',orange:'#fb923c',gray:'#64748b'}};
function line(x1,y1,x2,y2,c,w=1,d=[]){{ctx.save();ctx.strokeStyle=c;ctx.lineWidth=w;ctx.setLineDash(d);ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.restore();}}
function txt(s,x,y,c=C.text,fs=15,bold=false,align='left'){{ctx.fillStyle=c;ctx.font=(bold?'700 ':'')+fs+'px Inter,Arial';ctx.textAlign=align;ctx.fillText(s,x,y);}}
function fmt(v){{v=Number(v||0); if(!v) return 'N/A'; const a=Math.abs(v); const d=a>=1000?2:a>=1?4:a>=.01?5:a>=.0001?6:8; return '$'+v.toFixed(d).replace(/[.]?0+$/,'');}}
function ema(values,n){{let k=2/(n+1), out=[]; values.forEach((v,i)=>{{out[i]=i? v*k + out[i-1]*(1-k) : v;}}); return out;}}
function sma(values,n){{return values.map((_,i)=>{{let a=values.slice(Math.max(0,i-n+1),i+1); return a.reduce((x,y)=>x+y,0)/a.length;}});}}
function sd(values,n){{return values.map((_,i)=>{{let a=values.slice(Math.max(0,i-n+1),i+1); let m=a.reduce((x,y)=>x+y,0)/a.length; return Math.sqrt(a.reduce((x,y)=>x+(y-m)*(y-m),0)/a.length);}});}}
function rsi(values,n=14){{let out=Array(values.length).fill(50), gains=[],losses=[]; for(let i=1;i<values.length;i++){{let d=values[i]-values[i-1]; gains.push(Math.max(d,0)); losses.push(Math.max(-d,0)); let gs=gains.slice(-n), ls=losses.slice(-n); let ag=gs.reduce((a,b)=>a+b,0)/n, al=ls.reduce((a,b)=>a+b,0)/n; out[i]=al===0?100:100-(100/(1+ag/al));}} return out;}}
function stoch(candles,n=14){{return candles.map((r,i)=>{{let a=candles.slice(Math.max(0,i-n+1),i+1); let lo=Math.min(...a.map(x=>x[3])), hi=Math.max(...a.map(x=>x[2])); return hi===lo?50:(r[4]-lo)/(hi-lo)*100;}});}}
const candles=P.candles.map(r=>({{t:r[0],o:+r[1],h:+r[2],l:+r[3],c:+r[4],v:+r[5]}}));
const closes=candles.map(x=>x.c), highs=candles.map(x=>x.h), lows=candles.map(x=>x.l), vols=candles.map(x=>x.v);
const pad=42, topY=96, priceH=Math.floor(H*0.60), indTop=topY+priceH+18, indH=H-indTop-84, volH=72;
let prices=[...highs,...lows,Number(P.entry||0),Number(P.stop||0),...(P.targets||[])].filter(Boolean);
let minP=Math.min(...prices), maxP=Math.max(...prices); let margin=(maxP-minP)*0.08 || maxP*0.01 || 1; minP-=margin; maxP+=margin;
function x(i){{return pad + i*((W-pad*2)/(candles.length-1));}}
function y(p){{return topY+priceH-((p-minP)/(maxP-minP))*priceH;}}
ctx.fillStyle=C.bg;ctx.fillRect(0,0,W,H);
txt(`${{P.symbol}} — ${{P.side}}`,42,42,C.text,30,true); txt(`${{P.setup_label}} · ${{P.indicator_label}} · TF ${{P.interval}} · ${{P.exchange_id}}:${{P.market_symbol}}`,42,72,C.muted,17);
ctx.fillStyle='rgba(15,23,34,.94)'; ctx.fillRect(28,topY-14,W-56,priceH+28); ctx.strokeStyle='#223247'; ctx.strokeRect(28,topY-14,W-56,priceH+28);
for(let i=0;i<8;i++){{let yy=topY+i*(priceH/7); line(36,yy,W-36,yy,C.grid,.8); txt((maxP-(i/7)*(maxP-minP)).toPrecision(7),W-42,yy-4,C.muted,12,'right');}}
const mode=P.mode;
if(mode==='bollinger'){{let m=sma(closes,20), s=sd(closes,20); [[m.map((v,i)=>v+2*s[i]),C.purple],[m,C.gray],[m.map((v,i)=>v-2*s[i]),C.purple]].forEach(([arr,col])=>{{ctx.strokeStyle=col;ctx.lineWidth=2;ctx.beginPath();arr.forEach((p,i)=>{{if(i)ctx.lineTo(x(i),y(p));else ctx.moveTo(x(i),y(p));}});ctx.stroke();}}); txt('Bandas de Bollinger',52,topY+26,C.purple,14,true);}}
if(mode==='low-stoch'){{[[8,C.yellow],[21,C.blue],[80,C.purple],[200,C.orange]].forEach(([n,col])=>{{let arr=ema(closes,n); ctx.strokeStyle=col; ctx.lineWidth=n>50?1.2:1.8; ctx.beginPath(); arr.forEach((p,i)=>{{if(i)ctx.lineTo(x(i),y(p)); else ctx.moveTo(x(i),y(p));}}); ctx.stroke(); txt('EMA '+n,52+(n==8?0:n==21?70:n==80?150:230),topY+26,col,13,true);}});}}
if(mode==='grid'){{let arr=sma(closes,50); ctx.strokeStyle=C.yellow; ctx.lineWidth=2; ctx.beginPath(); arr.forEach((p,i)=>{{if(i)ctx.lineTo(x(i),y(p)); else ctx.moveTo(x(i),y(p));}}); ctx.stroke(); txt('SMA 50',52,topY+26,C.yellow,14,true);}}
if(mode==='institutional'){{[[9,C.yellow],[21,C.blue],[50,C.purple]].forEach(([n,col])=>{{let arr=ema(closes,n); ctx.strokeStyle=col; ctx.lineWidth=1.8; ctx.beginPath(); arr.forEach((p,i)=>{{if(i)ctx.lineTo(x(i),y(p)); else ctx.moveTo(x(i),y(p));}}); ctx.stroke(); txt('EMA '+n,52+(n==9?0:n==21?70:150),topY+26,col,13,true);}});}}
candles.forEach((c,i)=>{{let xx=x(i), col=c.c>=c.o?C.green:C.red; line(xx,y(c.h),xx,y(c.l),col,1.2); ctx.fillStyle=col; ctx.fillRect(xx-4,Math.min(y(c.o),y(c.c)),8,Math.max(2,Math.abs(y(c.o)-y(c.c))));}});
function level(label,p,col){{if(!p)return; let yy=y(p); line(40,yy,W-40,yy,col,2,[8,6]); ctx.fillStyle='rgba(0,0,0,.56)'; ctx.fillRect(W-286,yy-23,238,22); txt(label+' '+fmt(p),W-56,yy-7,col,14,true,'right');}}
level('ENTRADA',P.entry,C.green); level('STOP',P.stop,C.red); (P.targets||[]).forEach((t,i)=>level('ALVO '+(i+1),t,C.yellow));
ctx.fillStyle='rgba(15,23,34,.94)'; ctx.fillRect(28,indTop-10,W-56,indH); ctx.strokeStyle='#223247'; ctx.strokeRect(28,indTop-10,W-56,indH);
const r=rsi(closes), st=stoch(candles); function iy(v){{return indTop+indH-26-(v/100)*(indH-54);}}
for(let val of [30,50,70]){{line(40,iy(val),W-40,iy(val),val==50?C.grid:C.gray,.8,[4,4]); txt(String(val),W-42,iy(val)-4,C.muted,12,'right');}}
let mainInd = mode==='low-stoch' ? st : r; ctx.strokeStyle=mode==='low-stoch'?C.orange:C.blue; ctx.lineWidth=2; ctx.beginPath(); mainInd.forEach((v,i)=>{{if(i)ctx.lineTo(x(i),iy(v)); else ctx.moveTo(x(i),iy(v));}}); ctx.stroke(); txt(mode==='low-stoch'?'Stochastic + RSI':'RSI / Momentum',52,indTop+18,mode==='low-stoch'?C.orange:C.blue,14,true);
if(mode==='low-stoch'){{ctx.strokeStyle=C.blue; ctx.lineWidth=1.4; ctx.beginPath(); r.forEach((v,i)=>{{if(i)ctx.lineTo(x(i),iy(v)); else ctx.moveTo(x(i),iy(v));}}); ctx.stroke();}}
if(mode==='institutional'){{let macd=ema(closes,12).map((v,i)=>v-ema(closes,26)[i]); let mn=Math.min(...macd), mx=Math.max(...macd); ctx.strokeStyle=C.green; ctx.lineWidth=1.5; ctx.beginPath(); macd.forEach((v,i)=>{{let yy=indTop+indH-26-((v-mn)/(mx-mn||1))*(indH-54); if(i)ctx.lineTo(x(i),yy); else ctx.moveTo(x(i),yy);}}); ctx.stroke(); txt('MACD',170,indTop+18,C.green,14,true);}}
const maxV=Math.max(...vols); candles.forEach((c,i)=>{{let h=(c.v/maxV)*volH; ctx.fillStyle=c.c>=c.o?'rgba(34,197,94,.55)':'rgba(239,68,68,.55)'; ctx.fillRect(x(i)-3,H-56-h,6,h);}}); txt('Volume',52,H-72,C.muted,13,true);
txt(`TradingView symbol: ${{P.tradingview_symbol}} · Range ${{P.range}}`,42,H-38,C.muted,13); txt(String(P.reason||'').slice(0,150),W-42,H-38,C.muted,13,false,'right');
txt(String(P.source_text||''),42,H-16,C.yellow,14,true);
</script></body></html>"""


def _render_with_playwright(
    html_path: Path,
    output_path: Path,
    wait_ms: int | None = None,
    annotations: bool | None = None,
    renderer: str | None = None,
) -> None:
    wait_ms = wait_ms if wait_ms is not None else int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_WAIT_MS", "30000"))
    timeout = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_TIMEOUT_SECONDS", "90"))
    node_bin = os.environ.get("SETUP_NOTIFY_NODE_BIN", "node")
    package_json = ROOT.parent / "package.json"
    if annotations is None:
        annotations = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_ANNOTATIONS", "true").strip().lower() not in {"0", "false", "no", "nao"}
    estimated_overlay = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_ESTIMATED_OVERLAY", "false").strip().lower() in {"1", "true", "yes", "sim"}
    min_label_gap = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_MIN_LABEL_GAP_PX", "42"))
    scale_label_width = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_SCALE_LABEL_WIDTH_PX", "68"))
    target_label_width = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_TARGET_LABEL_WIDTH_PX", "112"))
    header_offset = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_HEADER_OFFSET_PX", "118"))
    allow_fallback_scale = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_ALLOW_FALLBACK_SCALE", "false").strip().lower() in {"1", "true", "yes", "sim"}
    requested_renderer = str(renderer or "").strip().lower()
    profile_dir = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_PROFILE_DIR", "").strip()
    allow_default_profile = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_ALLOW_DEFAULT_PROFILE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "sim",
    }
    if not profile_dir and requested_renderer == "managed-layout" and allow_default_profile and _default_tradingview_profile_dir().is_dir():
        profile_dir = str(_default_tradingview_profile_dir())
    require_auth = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_REQUIRE_AUTH", "false").strip().lower() in {"1", "true", "yes", "sim"}
    if profile_dir:
        Path(profile_dir).expanduser().mkdir(parents=True, exist_ok=True)
    script = f"""
const {{ createRequire }} = require('module');
const localRequire = createRequire({json.dumps(str(package_json))});
const http = require('http');
const fs = require('fs');
const path = require('path');
const playwrightModule = {json.dumps(os.environ.get('SETUP_NOTIFY_PLAYWRIGHT_NODE_MODULE', ''))};
let chromium;
try {{ chromium = localRequire('@playwright/test').chromium; }}
catch (err) {{
  if (!playwrightModule) throw err;
  chromium = require(playwrightModule).chromium || require(path.join(playwrightModule, 'index.js')).chromium;
}}
const htmlPath = {json.dumps(str(html_path.resolve()))};
const outputPath = {json.dumps(str(output_path))};
const annotations = {json.dumps(annotations)};
const estimatedOverlay = {json.dumps(estimated_overlay)};
const allowFallbackScale = {json.dumps(allow_fallback_scale)};
const profileDir = {json.dumps(str(Path(profile_dir).expanduser()) if profile_dir else '')};
const requireAuth = {json.dumps(require_auth)};
const forceManagedLayout = {json.dumps(requested_renderer == 'managed-layout')};
const requirePineLoad = {json.dumps(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE", "false").strip().lower() in {"1", "true", "yes", "sim"})};
const renderDiagnostics = [];
const overlayConfig = {{
  minLabelGap: {min_label_gap},
  scaleLabelWidth: {scale_label_width},
  targetLabelWidth: {target_label_width},
  headerOffset: {header_offset},
}};
function serveFile(root, filePath, res) {{
  fs.readFile(filePath, (err, data) => {{
    if (err) {{ res.statusCode = 404; res.end('404'); return; }}
    res.setHeader('Content-Type', filePath.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream');
    res.end(data);
  }});
}}
async function startServer() {{
  const root = path.dirname(htmlPath);
  const server = http.createServer((req, res) => {{
    const raw = decodeURIComponent(String(req.url || '/').split('?')[0]);
    const rel = raw === '/' ? path.basename(htmlPath) : raw.replace(/^\\/+/, '');
    const filePath = path.join(root, rel);
    if (!filePath.startsWith(root)) {{ res.statusCode = 403; res.end('403'); return; }}
    serveFile(root, filePath, res);
  }});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {{ server, url: `http://127.0.0.1:${{server.address().port}}/${{path.basename(htmlPath)}}` }};
}}
function fmt(v) {{
  v = Number(v || 0);
  if (!v) return 'N/A';
  const a = Math.abs(v);
  const d = a >= 1000 ? 2 : a >= 1 ? 4 : a >= .01 ? 5 : a >= .0001 ? 6 : 8;
  return '$' + v.toFixed(d).replace(/[.]?0+$/, '');
}}
function buildLevels(P) {{
  const colors = {{ entry:'#00D4FF', stop:'#FF3B5C', target:'#21C55D', fib:'#F59E0B' }};
  const levels = [];
  if (Number(P.entry || 0)) levels.push({{ kind:'entry', label:'Entrada', price:Number(P.entry), color:colors.entry, width:3, dashed:false }});
  if (Number(P.stop || 0)) levels.push({{ kind:'stop', label:'Stop Loss', price:Number(P.stop), color:colors.stop, width:3, dashed:false }});
  (P.targets || []).slice(0, 6).forEach((v, i) => {{
    const price = Number(v || 0);
    if (price) levels.push({{ kind:'target', label:`Alvo ${{i+1}}`, price, color:colors.target, width:2, dashed:i > 0 }});
  }});
  if (String(P.setup || '').startsWith('divergence-and-volume') && Array.isArray(P.fibonacci_levels)) {{
    P.fibonacci_levels.forEach((v, i) => {{
      const price = Number((v && typeof v === 'object') ? v.price : v || 0);
      const label = String((v && typeof v === 'object' && v.label) ? v.label : `Fib ${{i+1}}`);
      if (price) levels.push({{ kind:'fib', label, price, color:colors.fib, width:1, dashed:true }});
    }});
  }}
  return levels;
}}
function spreadLabels(items, minGap, height) {{
  const sorted = [...items].sort((a,b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) {{
    if (sorted[i].labelY - sorted[i-1].labelY < minGap) sorted[i].labelY = sorted[i-1].labelY + minGap;
  }}
  for (let i = sorted.length - 2; i >= 0; i--) {{
    if (sorted[i+1].labelY > height - 12) sorted[i+1].labelY = height - 12;
    if (sorted[i+1].labelY - sorted[i].labelY < minGap) sorted[i].labelY = sorted[i+1].labelY - minGap;
  }}
  for (const item of sorted) item.labelY = Math.max(12, Math.min(height - 12, item.labelY));
  return sorted;
}}
async function applyTradingViewAutoScale(page) {{
  const frames = page.frames().filter(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
  for (const frame of frames) {{
    const applied = await frame.evaluate(() => {{
      const cw = window.chartWidget;
      if (!cw) return 0;
      let count = 0;
      const charts = [];
      try {{ if (typeof cw.activeChart === 'function') charts.push(cw.activeChart()); }} catch (_) {{}}
      try {{ if (typeof cw.chart === 'function') charts.push(cw.chart()); }} catch (_) {{}}
      for (const chart of charts.filter(Boolean)) {{
        try {{
          if (typeof chart.executeActionById === 'function') {{
            for (const action of ['chartAutoScale', 'autoScale', 'paneAutoScale']) {{
              try {{ chart.executeActionById(action); count += 1; break; }} catch (_) {{}}
            }}
          }}
        }} catch (_) {{}}
        try {{
          const panes = typeof chart.getPanes === 'function' ? chart.getPanes() : [];
          for (const pane of panes || []) {{
            const priceScale = typeof pane.getMainSourcePriceScale === 'function' ? pane.getMainSourcePriceScale() : null;
            if (priceScale && typeof priceScale.setAutoScale === 'function') {{ priceScale.setAutoScale(true); count += 1; }}
          }}
        }} catch (_) {{}}
        try {{ if (typeof chart.resetPriceScale === 'function') {{ chart.resetPriceScale(); count += 1; }} }} catch (_) {{}}
      }}
      const attached = cw?._hip3DisclaimerResource?._resource?.resource?._attachedModel || (typeof cw?.model === 'function' ? cw.model() : null);
      const model = attached?.m_model || attached;
      const series = (model && typeof model.mainSeries === 'function' && model.mainSeries()) || model?._mainSeries || (attached && typeof attached.mainSeries === 'function' && attached.mainSeries());
      const priceScale = (series && typeof series.priceScale === 'function' && series.priceScale()) || series?._priceScale;
      if (priceScale) {{
        try {{ if (typeof priceScale.setAutoScale === 'function') {{ priceScale.setAutoScale(true); count += 1; }} }} catch (_) {{}}
        try {{ if (typeof priceScale.setMode === 'function') {{ priceScale.setMode({{ autoScale: true }}); count += 1; }} }} catch (_) {{}}
        try {{
          const prop = priceScale._properties?.autoScale;
          if (prop && typeof prop.setValue === 'function') {{ prop.setValue(true); count += 1; }}
          else if (prop && Object.prototype.hasOwnProperty.call(prop, '_value')) {{ prop._value = true; count += 1; }}
        }} catch (_) {{}}
      }}
      try {{ if (typeof model?.fullUpdate === 'function') model.fullUpdate(); }} catch (_) {{}}
      try {{ if (typeof cw._redraw === 'function') cw._redraw(); }} catch (_) {{}}
      return count;
    }}).catch(() => 0);
    if (applied) {{
      await page.waitForTimeout(900);
      return;
    }}
  }}
}}
async function fitTradingViewSignalPriceRange(page) {{
  const P = await page.evaluate(() => window.P || {{}}).catch(() => ({{}}));
  const prices = buildLevels(P).map(level => Number(level.price)).filter(price => Number.isFinite(price) && price > 0);
  if (prices.length < 2) return false;
  const frames = page.frames().filter(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
  for (const frame of frames) {{
    const applied = await frame.evaluate((prices) => {{
      const cw = window.chartWidget;
      if (!cw) return false;
      const attached = cw._hip3DisclaimerResource?._resource?.resource?._attachedModel || (typeof cw.model === 'function' ? cw.model() : null);
      const model = attached?.m_model || attached;
      const series = (model && typeof model.mainSeries === 'function' && model.mainSeries()) || model?._mainSeries || (attached && typeof attached.mainSeries === 'function' && attached.mainSeries());
      const priceScale = (series && typeof series.priceScale === 'function' && series.priceScale()) || series?._priceScale;
      if (!priceScale || typeof priceScale.setPriceRangeInPrice !== 'function') return false;
      const current = typeof priceScale.priceRangeInPrice === 'function' ? priceScale.priceRangeInPrice() : null;
      const values = prices.slice();
      if (current) {{
        if (Number.isFinite(Number(current.from))) values.push(Number(current.from));
        if (Number.isFinite(Number(current.to))) values.push(Number(current.to));
      }}
      let low = Math.min(...values);
      let high = Math.max(...values);
      if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return false;
      const padding = Math.max((high - low) * 0.08, high * 0.002, 1e-12);
      priceScale.setPriceRangeInPrice({{ from: low - padding, to: high + padding }});
      try {{ if (typeof model?.fullUpdate === 'function') model.fullUpdate(); }} catch (_) {{}}
      try {{ if (typeof cw._redraw === 'function') cw._redraw(); }} catch (_) {{}}
      return true;
    }}, prices).catch(() => false);
    if (applied) {{
      await page.waitForTimeout(900);
      return true;
    }}
  }}
  return false;
}}
async function injectPreciseOverlay(page) {{
  const P = await page.evaluate(() => window.P || P);
  const levels = buildLevels(P);
  if (!levels.length) return;
  const deadline = Date.now() + {wait_ms};
  let frame = null;
  while (Date.now() < deadline) {{
    frame = page.frames().find(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
    if (frame) break;
    await page.waitForTimeout(250);
  }}
  if (!frame) throw new Error('iframe TradingView widgetembed nao encontrado');
  const frameHandle = await frame.frameElement();
  const frameBox = await frameHandle.boundingBox();
  if (!frameBox) throw new Error('bounding box do iframe TradingView indisponivel');
  const data = await frame.evaluate(({{ levels, allowFallbackScale, P }}) => {{
    const cw = window.chartWidget;
    if (!cw) throw new Error('window.chartWidget indisponivel');
    const attached = cw._hip3DisclaimerResource?._resource?.resource?._attachedModel || (typeof cw.model === 'function' ? cw.model() : null);
    const model = attached?.m_model || attached;
    const series = (model && typeof model.mainSeries === 'function' && model.mainSeries()) || model?._mainSeries || (attached && typeof attached.mainSeries === 'function' && attached.mainSeries());
    const priceScale = (series && typeof series.priceScale === 'function' && series.priceScale()) || series?._priceScale;
    if (!series || !priceScale || typeof priceScale.priceToCoordinate !== 'function') {{
      throw new Error('priceToCoordinate real do TradingView indisponivel');
    }}
    let paneEl = document.querySelector('.chart-markup-table.pane');
    if (!paneEl && allowFallbackScale) {{
      const paneWidget = (cw.paneWidgets && cw.paneWidgets()?.[0]) || cw._paneWidgets?.[0];
      paneEl = paneWidget && typeof paneWidget.canvasElement === 'function' ? paneWidget.canvasElement() : null;
    }}
    if (!paneEl) throw new Error('painel principal .chart-markup-table.pane indisponivel');
    const rect = paneEl.getBoundingClientRect();
    const mapped = levels.map(level => {{
      const y = Number(priceScale.priceToCoordinate(Number(level.price), series));
      if (!Number.isFinite(y)) throw new Error(`coordenada invalida para ${{level.label}} ${{level.price}}`);
      return {{ ...level, y, absY: rect.top + y, labelY: rect.top + y, priceText: level.price, outOfView: y < 0 || y > rect.height }};
    }});
    return {{ pane: {{ x: rect.left, y: rect.top, width: rect.width, height: rect.height }}, levels: mapped }};
  }}, {{ levels, allowFallbackScale, P }});
  const invalid = data.levels.filter(l => l.y < -20 || l.y > data.pane.height + 20);
  if (invalid.length && !estimatedOverlay) throw new Error('nivel fora da escala visivel do TradingView apos ajuste de range: ' + invalid.map(l => l.label).join(', '));
  await page.evaluate(({{ frameBox, data, P, cfg }}) => {{
    const legacyLevels = document.getElementById('levels');
    if (legacyLevels) legacyLevels.style.display = 'none';
    const legacyMeta = document.getElementById('meta');
    if (legacyMeta) legacyMeta.style.display = 'none';
    document.getElementById('intuscripto-tradingview-overlay')?.remove();
    document.getElementById('legacy-tradingview-overlay')?.remove();
    const pageWidth = document.documentElement.clientWidth || window.innerWidth;
    const pane = {{
      x: frameBox.x + data.pane.x,
      y: frameBox.y + data.pane.y,
      width: data.pane.width,
      height: data.pane.height,
    }};
    pane.right = pane.x + pane.width;
    pane.bottom = pane.y + pane.height;
    const clampY = y => Math.max(pane.y, Math.min(pane.bottom, y));
    const levels = data.levels.map(level => ({{ ...level, absY: clampY(frameBox.y + data.pane.y + level.y), labelY: clampY(frameBox.y + data.pane.y + level.y), outOfView: Boolean(level.outOfView) }}));
    const root = document.createElement('div');
    root.id = 'intuscripto-tradingview-overlay';
    root.style.position = 'absolute';
    root.style.inset = '0';
    root.style.zIndex = '2147483647';
    root.style.pointerEvents = 'none';
    root.style.fontFamily = 'Arial, sans-serif';
    document.body.appendChild(root);
    const entry = levels.find(l => l.kind === 'entry');
    const stop = levels.find(l => l.kind === 'stop');
    const targets = levels.filter(l => l.kind === 'target');
    const lastTarget = targets[targets.length - 1];
    function addZone(a, b, color, label) {{
      if (!a || !b) return;
      const top = Math.min(a.absY, b.absY), bottom = Math.max(a.absY, b.absY);
      const z = document.createElement('div');
      z.style.position = 'absolute';
      z.style.left = (pane.x + pane.width * .58) + 'px';
      z.style.top = top + 'px';
      z.style.width = (pane.width * .36) + 'px';
      z.style.height = Math.max(10, bottom - top) + 'px';
      z.style.border = '2px solid ' + color;
      z.style.background = color + '24';
      z.style.borderRadius = '3px';
      z.style.boxSizing = 'border-box';
      const t = document.createElement('div');
      t.textContent = label;
      t.style.position = 'absolute';
      t.style.left = '8px';
      t.style.top = '6px';
      t.style.color = color;
      t.style.font = '700 18px Arial, sans-serif';
      t.style.textShadow = '0 2px 5px #000';
      z.appendChild(t);
      root.appendChild(z);
    }}
    if (P.show_risk_reward_zones !== false) {{
      addZone(entry, lastTarget, '#21C55D', 'Ret. / TPs');
      addZone(entry, stop, '#FF3B5C', 'Risco / inv.');
    }}
    const labels = [...levels].sort((a,b) => a.absY - b.absY);
    const priceScaleGap = 4;
    const scaleLeft = pane.right + priceScaleGap;
    const availableScaleWidth = Math.max(38, pageWidth - pane.right - priceScaleGap - 4);
    const scaleWidth = Math.min(cfg.scaleLabelWidth, availableScaleWidth);
    const tagHeight = 26;
    for (const level of labels) {{
      const lineY = Math.round(level.absY);
      const textY = Math.max(pane.y + tagHeight / 2, Math.min(pane.bottom - tagHeight / 2, lineY));
      const line = document.createElement('div');
      line.style.position = 'absolute';
      line.style.left = pane.x + 'px';
      line.style.top = lineY + 'px';
      line.style.width = pane.width + 'px';
      line.style.borderTop = `${{level.width}}px ${{level.dashed ? 'dashed' : 'solid'}} ${{level.color}}`;
      line.style.opacity = '.94';
      line.style.boxShadow = '0 0 8px rgba(0,0,0,.55)';
      root.appendChild(line);
      const lab = document.createElement('div');
      lab.textContent = level.label;
      lab.style.position = 'absolute';
      lab.style.left = (pane.x + 18) + 'px';
      lab.style.top = (textY - tagHeight / 2) + 'px';
      lab.style.width = cfg.targetLabelWidth + 'px';
      lab.style.height = tagHeight + 'px';
      lab.style.display = 'grid';
      lab.style.alignItems = 'center';
      lab.style.padding = '0 8px';
      lab.style.borderRadius = '5px';
      lab.style.boxSizing = 'border-box';
      lab.style.background = 'rgba(5,7,10,.82)';
      lab.style.border = '1px solid ' + level.color;
      lab.style.color = level.color;
      lab.style.font = '800 12px Arial, sans-serif';
      lab.style.textShadow = '0 2px 5px #000';
      root.appendChild(lab);
      const tag = document.createElement('div');
      tag.textContent = fmt(level.priceText);
      tag.style.position = 'absolute';
      tag.style.left = scaleLeft + 'px';
      tag.style.top = (textY - tagHeight / 2) + 'px';
      tag.style.width = scaleWidth + 'px';
      tag.style.height = tagHeight + 'px';
      tag.style.boxSizing = 'border-box';
      tag.style.display = 'grid';
      tag.style.gridTemplateColumns = '1fr';
      tag.style.gap = '6px';
      tag.style.alignItems = 'center';
      tag.style.background = level.color;
      tag.style.color = 'white';
      tag.style.font = '800 12px Arial, sans-serif';
      tag.style.padding = '3px 4px';
      tag.style.borderRadius = '3px';
      tag.style.boxShadow = '0 2px 8px rgba(0,0,0,.45)';
      tag.style.whiteSpace = 'nowrap';
      tag.style.overflow = 'hidden';
      tag.style.textAlign = 'center';
      root.appendChild(tag);
    }}
    const header = document.createElement('div');
    header.style.position = 'absolute';
    header.style.left = (pane.x + 18) + 'px';
    header.style.top = (pane.y + cfg.headerOffset) + 'px';
    header.style.padding = '10px 13px';
    header.style.borderRadius = '10px';
    header.style.background = 'rgba(5,7,10,.78)';
    header.style.border = '1px solid rgba(148,163,184,.35)';
    header.style.color = '#f8fafc';
    header.style.maxWidth = '520px';
    header.style.textShadow = '0 2px 5px #000';
    const reason = String(P.reason || '').toLowerCase();
    const structure = /bos|choch/.test(reason) ? 'BOS/CHoCH' : 'Estrutura tecnica';
    header.innerHTML = `<div style="font:800 18px Arial, sans-serif">${{P.setup_label || P.setup || 'Setup'}}</div><div style="margin-top:4px;font:700 12px Arial, sans-serif;color:#cbd5e1">${{P.indicator_label || ''}}</div><div style="display:inline-block;margin-top:8px;padding:5px 9px;border-radius:999px;background:${{String(P.side).toUpperCase()==='SHORT'?'#FF3B5C':'#00D4FF'}};color:#041016;font:900 12px Arial, sans-serif">${{String(P.side||'').toUpperCase()}} | ${{structure}}</div>`;
    root.appendChild(header);
    function fmt(v) {{ v=Number(v||0); if(!v) return 'N/A'; if(Math.abs(v)>=1) return '$'+v.toFixed(4); if(Math.abs(v)>=.0001) return '$'+v.toFixed(6); return '$'+v.toFixed(8); }}
  }}, {{ frameBox, data, P, cfg: overlayConfig }});
}}
async function assertTradingViewSymbolLoaded(page) {{
  const deadline = Date.now() + Math.max(4000, Math.floor({wait_ms} / 2));
  let lastText = '';
  while (Date.now() < deadline) {{
    const frames = page.frames().filter(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
    for (const frame of frames) {{
      const text = await frame.evaluate(() => document.body ? document.body.innerText : '').catch(() => '');
      lastText = text || lastText;
      if (/this symbol doesn.?t exist|symbol doesn.?t exist|invalid symbol|change symbol/i.test(text || '')) {{
        throw new Error(`simbolo TradingView indisponivel: ${{(await page.evaluate(() => (window.P || {{}}).tradingview_symbol).catch(() => 'N/A'))}}`);
      }}
      const hasPane = await frame.evaluate(() => Boolean(document.querySelector('.chart-markup-table.pane'))).catch(() => false);
      const hasMissingText = /pick.*another.*symbol|you.?ll see the data here/i.test(text || '');
      if (hasPane && !hasMissingText) return;
    }}
    await page.waitForTimeout(300);
  }}
  if (/pick.*another.*symbol|symbol/i.test(lastText || '')) throw new Error('TradingView nao carregou dados do simbolo');
}}
async function applyTradingViewStudyPatches(page, payload) {{
  const patches = Array.isArray(payload.study_patches) ? payload.study_patches : [];
  if (!patches.length) return;
  const frames = page.frames().filter(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
  for (const frame of frames) {{
    const applied = await frame.evaluate((patches) => {{
      const cw = window.chartWidget;
      const attached = cw?._hip3DisclaimerResource?._resource?.resource?._attachedModel || (typeof cw?.model === 'function' ? cw.model() : null);
      const model = attached?.m_model || attached;
      const vals = (model?._studiesWV && typeof model._studiesWV.value === 'function') ? model._studiesWV.value() : [];
      if (!vals.length) return 0;
      const used = new Set();
      let count = 0;
      for (const patch of patches) {{
        const idx = vals.findIndex((st, index) => {{
          if (used.has(index)) return false;
          try {{ return typeof st.name === 'function' && st.name() === patch.name; }} catch (_) {{ return false; }}
        }});
        if (idx < 0) continue;
        used.add(idx);
        const st = vals[idx];
        try {{
          if (patch.inputs && typeof patch.inputs === 'object') {{
            const aliases = {{
              periodK: ['periodK', 'length', 'in_0'],
              smoothK: ['smoothK', 'smooth', 'in_1'],
              periodD: ['periodD', 'smoothD', 'in_2'],
              length: ['length', 'periodK', 'in_0']
            }};
            for (const [key, rawValue] of Object.entries(patch.inputs)) {{
              const value = Number(rawValue);
              if (!Number.isFinite(value)) continue;
              const candidates = aliases[key] || [key];
              for (const candidate of candidates) {{
                const prop = st._properties?.inputs?.[candidate];
                if (prop && typeof prop.setValue === 'function') prop.setValue(value);
                if (st._inputs) st._inputs[candidate] = value;
                if (st._oldStudyInputs) st._oldStudyInputs[candidate] = value;
              }}
            }}
          }}
          const setMutableValue = (prop, value) => {{
            if (!prop) return false;
            if (typeof prop.setValue === 'function') {{ prop.setValue(value); return true; }}
            if (Object.prototype.hasOwnProperty.call(prop, '_value')) {{ prop._value = value; return true; }}
            return false;
          }};
          const styles = st._properties?.styles;
          const styleEntries = styles ? Object.values(styles).filter(style => style && typeof style === 'object' && (style.color || style.linewidth)) : [];
          for (const style of styleEntries) {{
            if (patch.color && style?.color) setMutableValue(style.color, patch.color);
            if (patch.lineWidth && style?.linewidth) setMutableValue(style.linewidth, Number(patch.lineWidth));
          }}
          if (typeof st.invalidateTitleCache === 'function') st.invalidateTitleCache();
          count += 1;
        }} catch (_) {{}}
      }}
      try {{ if (typeof model.fullUpdate === 'function') model.fullUpdate(); }} catch (_) {{}}
      try {{ if (typeof cw._redraw === 'function') cw._redraw(); }} catch (_) {{}}
      return count;
    }}, patches).catch(() => 0);
    if (applied) {{
      await page.waitForTimeout(900);
      return;
    }}
  }}
}}
async function assertTradingViewStudiesLoaded(page, payload) {{
  const validateStudies = {str(os.environ.get('SETUP_NOTIFY_TRADINGVIEW_VALIDATE_STUDIES', 'true').strip().lower() in {'1', 'true', 'yes', 'sim'}).lower()};
  const expected = Array.isArray(payload.expected_studies) ? payload.expected_studies.filter(Boolean) : [];
  if (!validateStudies || payload.pine_studies_configured || !expected.length) return;
  const deadline = Date.now() + Math.max(4000, Math.floor({wait_ms} / 2));
  let loaded = [];
  while (Date.now() < deadline) {{
    const frames = page.frames().filter(f => /widgetembed|tradingview/i.test(f.url()) && f !== page.mainFrame());
    for (const frame of frames) {{
      loaded = await frame.evaluate(() => {{
        const cw = window.chartWidget;
        const attached = cw?._hip3DisclaimerResource?._resource?.resource?._attachedModel || (typeof cw?.model === 'function' ? cw.model() : null);
        const model = attached?.m_model || attached;
        const vals = (model?._studiesWV && typeof model._studiesWV.value === 'function') ? model._studiesWV.value() : [];
        return vals.map(st => {{
          let title = '';
          let name = '';
          try {{ title = typeof st.title === 'function' ? st.title() : String(st._titleInParts || ''); }} catch (_) {{}}
          try {{ name = typeof st.name === 'function' ? st.name() : String(st._studyName || ''); }} catch (_) {{}}
          return title || name || '';
        }}).filter(Boolean);
      }}).catch(() => []);
      if (loaded.length) break;
    }}
    if (loaded.length) break;
    await page.waitForTimeout(300);
  }}
  if (String(payload.setup || payload.setup_key || '').toLowerCase().replace(/_/g, '-') === 'low-stoch-storm') {{
    const wrong = loaded.find(title => /stoch(?:astic)?\\s*rsi/i.test(String(title)));
    if (wrong) throw new Error('indicador TradingView incorreto para Low Stoch Storm: carregou Stoch RSI em vez de Estocástico Lento 14,3,3 | carregado=' + wrong);
  }}
  const remaining = loaded.filter(title => !/^Vol\b|^Volume\b/i.test(String(title)));
  const missing = [];
  for (const wanted of expected) {{
    const idx = remaining.findIndex(title => String(title).toLowerCase().includes(String(wanted).toLowerCase()));
    if (idx >= 0) remaining.splice(idx, 1);
    else missing.push(wanted);
  }}
  if (missing.length) {{
    throw new Error('estudos TradingView divergentes: faltando=' + missing.join(', ') + ' | carregados=' + loaded.join(' | '));
  }}
}}
async function waitForManagedLayout(page) {{
  const deadline = Date.now() + Math.max(12000, {wait_ms});
  let lastText = '';
  while (Date.now() < deadline) {{
    const ready = await page.evaluate(() => {{
      const text = document.body ? document.body.innerText : '';
      const panes = [...document.querySelectorAll('.chart-markup-table.pane')]
        .map(el => el.getBoundingClientRect())
        .filter(r => r.width > 200 && r.height > 80);
      return {{ ok: Boolean(window.TradingViewApi && window.TradingViewApi.activeChart && panes.length), text }};
    }}).catch(() => ({{ ok:false, text:'' }}));
    lastText = ready.text || lastText;
    if (ready.ok) return;
    await page.waitForTimeout(500);
  }}
  throw new Error('layout TradingView completo nao carregou: ' + String(lastText || '').slice(0, 240));
}}
async function assertManagedLayoutIndicators(page, payload) {{
  const text = await page.evaluate(() => document.body ? document.body.innerText : '').catch(() => '');
  if (String(payload.setup || '').toLowerCase().replace(/_/g, '-') === 'low-stoch-storm') {{
    if (/stoch(?:astic)?\\s*rsi/i.test(text)) throw new Error('layout Low Stoch carregou Stoch RSI em vez de Estocástico Lento');
    if (!/(slow\\s+stochastic|estoc[aá]stico\\s+lento|\\bstochastic\\b)/i.test(text)) throw new Error('layout Low Stoch sem Estocástico Lento visível');
    if (!/\\brsi\\b/i.test(text)) throw new Error('layout Low Stoch sem RSI visível');
    if (!/\\bema\\b/i.test(text)) throw new Error('layout Low Stoch sem EMA visível');
  }}
}}
async function setManagedSymbolAndInterval(page, payload) {{
  await page.evaluate((payload) => {{
    window.P = payload;
    const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
    if (!chart) return;
    try {{ if (payload.tradingview_symbol && typeof chart.setSymbol === 'function') chart.setSymbol(String(payload.tradingview_symbol)); }} catch (_) {{}}
    try {{ if (payload.interval && typeof chart.setResolution === 'function') chart.setResolution(String(payload.interval)); }} catch (_) {{}}
  }}, payload).catch(() => {{}});
  await page.waitForTimeout(2500);
}}
async function closeManagedLayoutPanels(page) {{
  const actions = [];
  const closeByAria = async (label) => page.evaluate((label) => {{
    const candidates = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {{
      const r = el.getBoundingClientRect();
      return {{ el, r, aria: el.getAttribute('aria-label') || '', cls: String(el.className || '') }};
    }}).filter(x => x.r.width > 0 && x.r.height > 0 && x.r.x > window.innerWidth - 120 && x.aria === label && /isActive/.test(x.cls));
    if (!candidates[0]) return false;
    candidates[0].el.click();
    return true;
  }}, label).catch(() => false);
  const clickedClose = await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll('button,[role="button"]')).map(el => {{
      const r = el.getBoundingClientRect();
      return {{ el, r, aria: el.getAttribute('aria-label') || '' }};
    }}).filter(x => x.r.width > 0 && x.r.height > 0 && x.aria === 'Close').sort((a, b) => b.r.x - a.r.x);
    if (!btns[0] || btns[0].r.x < window.innerWidth - 420) return false;
    btns[0].el.click();
    return true;
  }}).catch(() => false);
  if (clickedClose) actions.push('close-button');
  await page.waitForTimeout(800);
  if (await closeByAria('Watchlist, details, and news')) actions.push('close-watchlist');
  await page.waitForTimeout(800);
  if (await closeByAria('Pine')) actions.push('close-pine');
  await page.waitForTimeout(800);
  return actions;
}}
async function goToManagedSignalTime(page, payload) {{
  if (!payload.signal_date || !payload.signal_time) return {{ attempted:false }};
  try {{
    const barSpacing = Number(process.env.SETUP_NOTIFY_TRADINGVIEW_BAR_SPACING || 14);
    const beforeZoom = await page.evaluate((barSpacing) => {{
      const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
      const ts = chart && chart.getTimeScale && chart.getTimeScale();
      if (ts && ts.setBarSpacing) ts.setBarSpacing(barSpacing);
      return {{ barSpacing: ts && ts.barSpacing ? ts.barSpacing() : null }};
    }}, barSpacing).catch(() => ({{}}));
    await page.waitForTimeout(900);
    await page.keyboard.press('Alt+G');
    await page.waitForTimeout(900);
    await page.locator('input[placeholder="YYYY-MM-DD"]').first().fill(String(payload.signal_date), {{ timeout: 5000 }});
    await page.locator('input[role="combobox"]').first().fill(String(payload.signal_time), {{ timeout: 5000 }});
    await page.locator('button:has-text("Go to")').last().click({{ timeout: 5000 }});
    await page.waitForTimeout(Number(process.env.SETUP_NOTIFY_TRADINGVIEW_GOTO_WAIT_MS || 8000));
    const visibleRange = await page.evaluate(() => {{
      const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
      return chart && chart.getVisibleRange ? chart.getVisibleRange() : null;
    }}).catch(() => null);
    return {{ attempted:true, ok:true, beforeZoom, visibleRange }};
  }} catch (err) {{
    await page.keyboard.press('Escape').catch(() => {{}});
    return {{ attempted:true, ok:false, error:String(err && err.message || err) }};
  }}
}}
async function fitManagedLayoutSignalPriceRange(page, payload) {{
  const prices = buildLevels(payload).map(level => Number(level.price)).filter(price => Number.isFinite(price) && price > 0);
  if (prices.length < 2) return false;
  const applied = await page.evaluate((prices) => {{
    const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
    const model = chart && typeof chart.chartModel === 'function' ? chart.chartModel() : null;
    const series = model && typeof model.mainSeries === 'function' ? model.mainSeries() : null;
    const priceScale = series && typeof series.priceScale === 'function' ? series.priceScale() : null;
    if (!priceScale || typeof priceScale.setPriceRangeInPrice !== 'function') return false;
    const current = typeof priceScale.priceRangeInPrice === 'function' ? priceScale.priceRangeInPrice() : null;
    const values = prices.slice();
    if (current) {{
      if (Number.isFinite(Number(current.from))) values.push(Number(current.from));
      if (Number.isFinite(Number(current.to))) values.push(Number(current.to));
    }}
    let low = Math.min(...values);
    let high = Math.max(...values);
    if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) return false;
    const padding = Math.max((high - low) * 0.08, high * 0.002, 1e-12);
    priceScale.setPriceRangeInPrice({{ from: low - padding, to: high + padding }});
    try {{ if (typeof model.updateAllPaneViews === 'function') model.updateAllPaneViews(); }} catch (_) {{}}
    return true;
  }}, prices).catch(() => false);
  if (applied) await page.waitForTimeout(900);
  return applied;
}}
async function injectManagedLayoutOverlay(page, payload) {{
  const levels = buildLevels(payload);
  if (!levels.length) return;
  const data = await page.evaluate(({{ levels }}) => {{
    const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
    const model = chart && typeof chart.chartModel === 'function' ? chart.chartModel() : null;
    const series = model && typeof model.mainSeries === 'function' ? model.mainSeries() : null;
    const priceScale = series && typeof series.priceScale === 'function' ? series.priceScale() : null;
    if (!series || !priceScale || typeof priceScale.priceToCoordinate !== 'function') throw new Error('priceToCoordinate real do TradingView indisponivel no layout completo');
    const panes = [...document.querySelectorAll('.chart-markup-table.pane')]
      .filter(el => {{ const r = el.getBoundingClientRect(); return r.width > 200 && r.height > 80; }});
    const paneEl = panes[0];
    if (!paneEl) throw new Error('painel principal do layout TradingView indisponivel');
    const rect = paneEl.getBoundingClientRect();
    const allRects = [...panes, ...document.querySelectorAll('.paneSeparator-ai9MXJ9k')]
      .map(el => el.getBoundingClientRect())
      .filter(r => r.width > 100 && r.height >= 0);
    const minX = Math.max(0, Math.min(...allRects.map(r => r.left)) - 2);
    const minY = Math.max(0, Math.min(...allRects.map(r => r.top)) - 2);
    const maxX = Math.min(window.innerWidth, Math.max(...allRects.map(r => r.right)) + 4);
    const maxY = Math.min(window.innerHeight, Math.max(...panes.map(el => el.getBoundingClientRect().bottom)) + 4);
    const mapped = levels.map(level => {{
      const y = Number(priceScale.priceToCoordinate(Number(level.price), series));
      if (!Number.isFinite(y)) throw new Error(`coordenada invalida para ${{level.label}} ${{level.price}}`);
      return {{ ...level, y, absY: rect.top + y, priceText: level.price, outOfView: y < 0 || y > rect.height }};
    }});
    return {{ pane: {{ x: rect.left, y: rect.top, width: rect.width, height: rect.height, right: rect.right, bottom: rect.bottom }}, levels: mapped, clip: {{ x: minX, y: minY, width: Math.max(300, maxX - minX), height: Math.max(300, maxY - minY) }} }};
  }}, {{ levels }});
  const invalid = data.levels.filter(l => l.y < -20 || l.y > data.pane.height + 20);
  if (invalid.length && !estimatedOverlay) throw new Error('nivel fora da escala visivel do TradingView apos ajuste de range: ' + invalid.map(l => l.label).join(', '));
  await page.evaluate(({{ data, P, cfg }}) => {{
    document.getElementById('intuscripto-tradingview-overlay')?.remove();
    const pane = data.pane;
    const clampY = y => Math.max(pane.y, Math.min(pane.bottom, y));
    const levels = data.levels.map(level => ({{ ...level, absY: clampY(level.absY), outOfView: Boolean(level.outOfView) }}));
    const root = document.createElement('div');
    root.id = 'intuscripto-tradingview-overlay';
    root.style.position = 'absolute';
    root.style.inset = '0';
    root.style.zIndex = '2147483647';
    root.style.pointerEvents = 'none';
    root.style.fontFamily = 'Arial, sans-serif';
    document.body.appendChild(root);
    const entry = levels.find(l => l.kind === 'entry');
    const stop = levels.find(l => l.kind === 'stop');
    const targets = levels.filter(l => l.kind === 'target');
    const lastTarget = targets[targets.length - 1];
    function addZone(a, b, color, label) {{
      if (!a || !b) return;
      const top = Math.min(a.absY, b.absY), bottom = Math.max(a.absY, b.absY);
      const z = document.createElement('div');
      z.style.position = 'absolute';
      z.style.left = (pane.x + pane.width * .58) + 'px';
      z.style.top = top + 'px';
      z.style.width = (pane.width * .34) + 'px';
      z.style.height = Math.max(10, bottom - top) + 'px';
      z.style.border = '2px solid ' + color;
      z.style.background = color + '24';
      z.style.borderRadius = '3px';
      z.style.boxSizing = 'border-box';
      const t = document.createElement('div');
      t.textContent = label;
      t.style.position = 'absolute';
      t.style.left = '8px';
      t.style.top = '6px';
      t.style.color = color;
      t.style.font = '700 18px Arial, sans-serif';
      t.style.textShadow = '0 2px 5px #000';
      z.appendChild(t);
      root.appendChild(z);
    }}
    if (P.show_risk_reward_zones !== false) {{
      addZone(entry, lastTarget, '#21C55D', 'Ret. / TPs');
      addZone(entry, stop, '#FF3B5C', 'Risco / inv.');
    }}
    function fmt(v) {{ v=Number(v||0); if(!v) return 'N/A'; if(Math.abs(v)>=1) return '$'+v.toFixed(4); if(Math.abs(v)>=.0001) return '$'+v.toFixed(6); return '$'+v.toFixed(8); }}
    function addSignalMarker() {{
      let signalX = pane.x + pane.width / 2;
      try {{
        const chart = window.TradingViewApi && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();
        const ts = chart && chart.getTimeScale && chart.getTimeScale();
        const target = Date.parse(String(P.signal_time_utc || '')) / 1000;
        if (ts && Number.isFinite(target) && typeof ts.coordinateToTime === 'function') {{
          let bestX = null, bestDelta = Infinity;
          for (let x = 0; x <= pane.width; x += 4) {{
            const t = Number(ts.coordinateToTime(x));
            if (!Number.isFinite(t)) continue;
            const delta = Math.abs(t - target);
            if (delta < bestDelta) {{ bestDelta = delta; bestX = x; }}
          }}
          if (bestX !== null && bestDelta < 60 * 45) signalX = pane.x + bestX;
        }}
      }} catch (_) {{}}
      const line = document.createElement('div');
      line.style.position = 'absolute';
      line.style.left = Math.round(signalX) + 'px';
      line.style.top = pane.y + 'px';
      line.style.height = pane.height + 'px';
      line.style.borderLeft = '2px solid #F59E0B';
      line.style.boxShadow = '0 0 8px rgba(0,0,0,.65)';
      root.appendChild(line);
      const tag = document.createElement('div');
      tag.textContent = 'SINAL ' + String(P.signal_label || '').replace(' BRT', '');
      tag.style.position = 'absolute';
      tag.style.left = Math.max(pane.x + 10, Math.min(pane.right - 180, signalX + 8)) + 'px';
      tag.style.top = (pane.y + 10) + 'px';
      tag.style.padding = '5px 8px';
      tag.style.borderRadius = '6px';
      tag.style.background = 'rgba(5,7,10,.86)';
      tag.style.border = '1px solid #F59E0B';
      tag.style.color = '#F59E0B';
      tag.style.font = '800 12px Arial, sans-serif';
      tag.style.textShadow = '0 2px 5px #000';
      root.appendChild(tag);
    }}
    if (P.signal_time_utc || P.signal_label) addSignalMarker();
    const checks = Array.isArray(P.indicator_checks) ? P.indicator_checks.filter(Boolean).slice(0, 6) : [];
    if (checks.length) {{
      const box = document.createElement('div');
      box.style.position = 'absolute';
      box.style.left = (pane.x + 18) + 'px';
      box.style.top = (pane.y + 42) + 'px';
      box.style.maxWidth = '460px';
      box.style.display = 'flex';
      box.style.flexWrap = 'wrap';
      box.style.gap = '5px';
      for (const check of checks) {{
        const chip = document.createElement('div');
        chip.textContent = String(check);
        chip.style.padding = '4px 7px';
        chip.style.borderRadius = '999px';
        chip.style.background = 'rgba(15,23,42,.78)';
        chip.style.border = '1px solid rgba(148,163,184,.45)';
        chip.style.color = '#E2E8F0';
        chip.style.font = '800 11px Arial, sans-serif';
        chip.style.textShadow = '0 2px 5px #000';
        box.appendChild(chip);
      }}
      root.appendChild(box);
    }}
    const tagHeight = 26;
    const scaleWidth = Math.min(cfg.scaleLabelWidth, Math.max(42, pane.width * 0.10));
    const scaleLeft = pane.right - scaleWidth - 8;
    for (const level of [...levels].sort((a,b) => a.absY - b.absY)) {{
      const lineY = Math.round(level.absY);
      const textY = Math.max(pane.y + tagHeight / 2, Math.min(pane.bottom - tagHeight / 2, lineY));
      const line = document.createElement('div');
      line.style.position = 'absolute';
      line.style.left = pane.x + 'px';
      line.style.top = lineY + 'px';
      line.style.width = pane.width + 'px';
      line.style.borderTop = `${{level.width}}px ${{level.dashed ? 'dashed' : 'solid'}} ${{level.color}}`;
      line.style.opacity = '.94';
      line.style.boxShadow = '0 0 8px rgba(0,0,0,.55)';
      root.appendChild(line);
      const lab = document.createElement('div');
      lab.textContent = level.label;
      lab.style.position = 'absolute';
      lab.style.left = (pane.x + 18) + 'px';
      lab.style.top = (textY - tagHeight / 2) + 'px';
      lab.style.width = cfg.targetLabelWidth + 'px';
      lab.style.height = tagHeight + 'px';
      lab.style.display = 'grid';
      lab.style.alignItems = 'center';
      lab.style.padding = '0 8px';
      lab.style.borderRadius = '5px';
      lab.style.boxSizing = 'border-box';
      lab.style.background = 'rgba(5,7,10,.82)';
      lab.style.border = '1px solid ' + level.color;
      lab.style.color = level.color;
      lab.style.font = '800 12px Arial, sans-serif';
      lab.style.textShadow = '0 2px 5px #000';
      root.appendChild(lab);
      const tag = document.createElement('div');
      tag.textContent = fmt(level.priceText);
      tag.style.position = 'absolute';
      tag.style.left = scaleLeft + 'px';
      tag.style.top = (textY - tagHeight / 2) + 'px';
      tag.style.width = scaleWidth + 'px';
      tag.style.height = tagHeight + 'px';
      tag.style.boxSizing = 'border-box';
      tag.style.display = 'grid';
      tag.style.alignItems = 'center';
      tag.style.background = level.color;
      tag.style.color = 'white';
      tag.style.font = '800 12px Arial, sans-serif';
      tag.style.padding = '3px 4px';
      tag.style.borderRadius = '3px';
      tag.style.boxShadow = '0 2px 8px rgba(0,0,0,.45)';
      tag.style.whiteSpace = 'nowrap';
      tag.style.overflow = 'hidden';
      tag.style.textAlign = 'center';
      root.appendChild(tag);
    }}
    const header = document.createElement('div');
    header.style.position = 'absolute';
    header.style.left = (pane.x + 18) + 'px';
    header.style.top = (pane.y + cfg.headerOffset) + 'px';
    header.style.padding = '10px 13px';
    header.style.borderRadius = '10px';
    header.style.background = 'rgba(5,7,10,.78)';
    header.style.border = '1px solid rgba(148,163,184,.35)';
    header.style.color = '#f8fafc';
    header.style.maxWidth = '520px';
    header.style.textShadow = '0 2px 5px #000';
    const reason = String(P.reason || '').toLowerCase();
    const structure = /bos|choch/.test(reason) ? 'BOS/CHoCH' : 'Estrutura técnica';
    header.innerHTML = `<div style="font:800 18px Arial, sans-serif">${{P.setup_label || P.setup || 'Setup'}}</div><div style="margin-top:4px;font:700 12px Arial, sans-serif;color:#cbd5e1">${{P.indicator_label || ''}}</div><div style="display:inline-block;margin-top:8px;padding:5px 9px;border-radius:999px;background:${{String(P.side).toUpperCase()==='SHORT'?'#FF3B5C':'#00D4FF'}};color:#041016;font:900 12px Arial, sans-serif">${{String(P.side||'').toUpperCase()}} | ${{structure}}</div>`;
    root.appendChild(header);
    window.__intuscriptoManagedLayoutClip = data.clip;
  }}, {{ data, P: payload, cfg: overlayConfig }});
}}
async function cleanManagedScreenshotChrome(page) {{
  await page.keyboard.press('Escape').catch(() => {{}});
  await page.mouse.move(6, 6).catch(() => {{}});
  await page.evaluate(() => {{
    if (!document.getElementById('intuscripto-managed-clean-screenshot-style')) {{
      const style = document.createElement('style');
      style.id = 'intuscripto-managed-clean-screenshot-style';
      style.textContent = `
        [role="toolbar"],
        [class*="toolbar"],
        [class*="Toolbar"],
        [data-name*="toolbar"] {{ visibility: hidden !important; }}
      `;
      document.head.appendChild(style);
    }}
    const hide = (el) => {{
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('display', 'none', 'important');
    }};
    const pane = document.querySelector('[data-qa-id="pane"]') || document.querySelector('.chart-markup-table.pane');
    const pr = pane ? pane.getBoundingClientRect() : {{ left:0, right:window.innerWidth, top:0, bottom:window.innerHeight }};
    for (const el of document.querySelectorAll('div,section,span,button,[role="button"]')) {{
      if (el.id === 'intuscripto-tradingview-overlay' || el.closest?.('#intuscripto-tradingview-overlay')) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const text = (el.innerText || el.textContent || '').trim();
      const aria = el.getAttribute('aria-label') || '';
      const buttons = el.querySelectorAll?.('button,[role="button"]').length || 0;
      const floatingTop = r.y > pr.top + 10 && r.y < pr.top + 150 && r.x > pr.left + 180 && r.x < pr.right - 180 && r.width > 120 && r.width < 760 && r.height < 90 && buttons >= 2;
      const bottomControls = r.y > pr.bottom - 120 && r.y < pr.bottom + 80 && r.x > pr.left + 100 && r.x < pr.right - 100 && r.width < 900 && r.height < 110 && buttons >= 1;
      const chromeText = /go to|date range|zoom|replay|settings|magnet|lock|hide all drawings/i.test(text + ' ' + aria);
      if ((floatingTop && chromeText) || bottomControls) hide(el);
    }}
  }}).catch(() => {{}});
  await page.waitForTimeout(350);
}}
async function renderManagedLayoutPage(page, payload) {{
  const encodedSymbol = encodeURIComponent(String(payload.tradingview_symbol || payload.symbol || ''));
  const interval = encodeURIComponent(String(payload.interval || '240'));
  const layoutTemplate = String(payload.tradingview_layout_url || '').trim();
  const url = layoutTemplate
    ? layoutTemplate.split('{{symbol}}').join(encodedSymbol).split('{{interval}}').join(interval)
    : `https://www.tradingview.com/chart/?symbol=${{encodedSymbol}}&interval=${{interval}}`;
  await page.goto(url, {{waitUntil:'domcontentloaded', timeout: Math.max(60000, {wait_ms}+30000)}});
  await waitForManagedLayout(page);
  await setManagedSymbolAndInterval(page, payload);
  await waitForManagedLayout(page);
  const panelActions = await closeManagedLayoutPanels(page);
  const goTo = await goToManagedSignalTime(page, payload);
  await waitForManagedLayout(page);
  await assertManagedLayoutIndicators(page, payload);
  await fitManagedLayoutSignalPriceRange(page, payload);
  if (annotations) await injectManagedLayoutOverlay(page, payload);
  await page.evaluate(({{ panelActions, goTo }}) => {{ window.__aspiraManagedLayoutActions = {{ panelActions, goTo }}; }}, {{ panelActions, goTo }}).catch(() => {{}});
  await page.waitForTimeout(500);
}}
(async () => {{
 let server;
 try {{
  const served = await startServer(); server = served.server;
  const viewport = {{width:{int(os.environ.get('SETUP_NOTIFY_TRADINGVIEW_WIDTH','2454'))},height:{int(os.environ.get('SETUP_NOTIFY_TRADINGVIEW_HEIGHT','1280'))}}};
  let browser = null;
  let context = null;
  let page = null;
  if (profileDir) {{
    context = await chromium.launchPersistentContext(profileDir, {{headless:true, viewport, deviceScaleFactor:1, colorScheme:'dark'}});
    page = context.pages()[0] || await context.newPage();
  }} else {{
    browser = await chromium.launch({{headless:true}});
    context = await browser.newContext({{viewport, deviceScaleFactor:1, colorScheme:'dark'}});
    page = await context.newPage();
  }}
  page.on('response', res => {{
    const url = res.url();
    if (/pine-facade|study/i.test(url) && res.status() >= 400) renderDiagnostics.push(`HTTP ${{res.status()}} ${{url}}`);
  }});
  page.on('console', msg => {{
    const text = msg.text();
    if (/Cannot get study|pine facade|StudyInserter|Status 4\\d\\d|Status 5\\d\\d/i.test(text)) renderDiagnostics.push(`${{msg.type()}} ${{text}}`);
  }});
  if (requireAuth) {{
    const authPage = await context.newPage();
    await authPage.goto('https://www.tradingview.com/', {{waitUntil:'domcontentloaded', timeout: Math.max(60000, {wait_ms}+30000)}});
    await authPage.waitForTimeout(2000);
    const loggedIn = await authPage.evaluate(() => !document.querySelector('button[data-name="header-user-menu-sign-in"], [data-name="header-user-menu-sign-in"]'));
    await authPage.close();
    if (!loggedIn) throw new Error('sessao TradingView nao autenticada no perfil persistente');
  }}
  await page.goto(served.url, {{waitUntil:'domcontentloaded', timeout: Math.max(60000, {wait_ms}+30000)}});
  const payload = await page.evaluate(() => window.P || {{}}).catch(() => ({{}}));
  const managedLayout = forceManagedLayout || String(payload.renderer || '').toLowerCase() === 'tradingview-managed-layout';
  if (managedLayout) {{
    if (!profileDir) throw new Error('renderer managed-layout exige SETUP_NOTIFY_TRADINGVIEW_PROFILE_DIR explicito; perfil pessoal padrao nao e usado automaticamente');
    await renderManagedLayoutPage(page, payload);
    await cleanManagedScreenshotChrome(page);
    const clip = await page.evaluate(() => window.__intuscriptoManagedLayoutClip || null).catch(() => null);
    if (clip && Number.isFinite(clip.x) && Number.isFinite(clip.y) && clip.width > 100 && clip.height > 100) {{
      await page.screenshot({{path:outputPath, clip}});
    }} else {{
      await page.screenshot({{path:outputPath}});
    }}
  }} else {{
    await page.waitForTimeout({wait_ms});
    await assertTradingViewSymbolLoaded(page);
    await applyTradingViewStudyPatches(page, payload);
    await assertTradingViewStudiesLoaded(page, payload);
    await applyTradingViewAutoScale(page);
    await fitTradingViewSignalPriceRange(page);
    if (requirePineLoad && payload && payload.pine_studies_configured && renderDiagnostics.length) {{
      throw new Error('Pine configurado não carregou no TradingView widget: ' + renderDiagnostics.slice(0, 5).join(' | '));
    }}
    if (annotations) await injectPreciseOverlay(page);
    await page.waitForTimeout(350);
    await page.screenshot({{path:outputPath}});
  }}
  if (context) await context.close();
  if (browser) await browser.close();
 }} finally {{
  if (server) await new Promise(resolve => server.close(resolve));
 }}
}})().catch(err => {{ console.error(err); process.exit(1); }});
"""
    script_path = output_path.with_suffix(".playwright.js")
    script_path.write_text(script, encoding="utf-8")
    try:
        subprocess.run([node_bin, str(script_path)], cwd=str(ROOT.parent), check=True, timeout=max(timeout, wait_ms // 1000 + 30))
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:
            pass
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"screenshot nao gerado: {output_path}")
    min_bytes = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_MIN_SCREENSHOT_BYTES", "50000"))
    min_width = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_MIN_SCREENSHOT_WIDTH", "900"))
    min_height = int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_MIN_SCREENSHOT_HEIGHT", "500"))
    data = output_path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"screenshot TradingView invalido: PNG esperado em {output_path}")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    size = output_path.stat().st_size
    if size < min_bytes or width < min_width or height < min_height:
        raise RuntimeError(
            f"screenshot TradingView suspeito: size={size} width={width} height={height} path={output_path}"
        )


def render_tradingview_chart(signal: dict[str, Any]) -> Path:
    setup = _setup_key(signal)
    static_renderer = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_STATIC_RENDERER", "false").strip().lower() in {"1", "true", "yes", "sim"}
    renderer = "static" if static_renderer else _requested_renderer(setup)
    require_pine = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE", "false").strip().lower() in {"1", "true", "yes", "sim"}
    pine_enabled = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_PINE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "sim"}
    if pine_enabled and require_pine and not _pine_studies_for_setup(setup):
        raise RuntimeError(f"Pine canônico não configurado para setup {setup}")
    interval = _chart_interval(signal)
    candles, exchange_id, market_symbol = _fetch_ohlcv(signal, interval)
    tv_exchange = _preferred_tradingview_exchange(exchange_id)
    tv_candidates = tradingview_symbol_candidates(str(signal.get("symbol") or market_symbol), setup=setup, exchange=tv_exchange)
    max_attempts = max(1, int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_SYMBOL_MAX_ATTEMPTS", "8")))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    safe_symbol = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(signal.get("symbol") or market_symbol)).strip("-") or "trade"
    output_path = _output_dir() / f"{safe_symbol}_{stamp}.png"
    annotations = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_ANNOTATIONS", "true").strip().lower() not in {"0", "false", "no", "nao"}
    if renderer in {"static", "ccxt", "canvas"}:
        # O renderer estático já desenha entrada/stop/alvos no canvas.
        # A injeção precisa do iframe do widget e quebrava o fluxo limpo estilo Zeus.
        annotations = False
    default_wait_ms = "30000" if renderer not in {"static", "ccxt", "canvas"} and annotations else ("8000" if renderer not in {"static", "ccxt", "canvas"} else "1000")
    errors: list[str] = []
    keep_html = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_KEEP_HTML", "0").strip().lower() in {"1", "true", "yes", "sim"}
    candidate_symbols = tv_candidates[:max_attempts] if renderer not in {"static", "ccxt", "canvas"} else tv_candidates[:1]
    for idx, tv_symbol in enumerate(candidate_symbols, start=1):
        html_path = output_path.with_name(f"{output_path.stem}.tv{idx}.html")
        html_path.write_text(_html_config(signal, candles, exchange_id, market_symbol, tv_symbol=tv_symbol), encoding="utf-8")
        try:
            if output_path.exists():
                output_path.unlink()
            _render_with_playwright(
                html_path,
                output_path,
                wait_ms=int(os.environ.get("SETUP_NOTIFY_TRADINGVIEW_WAIT_MS", default_wait_ms)),
                annotations=annotations,
                renderer=renderer,
            )
            return output_path
        except Exception as exc:
            errors.append(f"{tv_symbol}: {exc}")
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            if renderer in {"static", "ccxt", "canvas"}:
                raise
        finally:
            if not keep_html:
                try:
                    html_path.unlink(missing_ok=True)
                except Exception:
                    pass
    raise RuntimeError("grafico TradingView indisponivel para o simbolo; tentativas=" + " | ".join(errors[:max_attempts]))


# Placeholders de compatibilidade com o playbook legado. O modo widget pode ser
# implementado depois sem alterar o contrato publico `render_tradingview_chart`.
def _render_tradingview_precise_overlay(html_path: Path, output_path: Path, signal: dict[str, Any]) -> Path:
    _render_with_playwright(html_path, output_path)
    return output_path


def _precise_overlay_script() -> str:
    return ""
