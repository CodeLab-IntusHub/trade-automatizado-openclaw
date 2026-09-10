#!/usr/bin/env python3
"""Persist setup analyses/trade entries and render a static ops dashboard."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_ID = "trade-automatizado-openclaw"
HOME = Path.home()
DEFAULT_LOG_PATH = HOME / ".openclaw" / "logs" / SKILL_ID / "setup-live-analyzer.log"
DEFAULT_CCXT_LOG_PATH = HOME / ".openclaw" / "logs" / SKILL_ID / "ccxt-entry-scanner.log"
DEFAULT_STATE_DIR = HOME / ".openclaw" / "state" / SKILL_ID
DEFAULT_WORKSPACE_DIR = HOME / ".openclaw" / "workspace"
DEFAULT_REPORT_DIR = DEFAULT_WORKSPACE_DIR / "reports" / "trade-system"
DEFAULT_STATE_PATH = HOME / ".openclaw" / "state" / SKILL_ID / "trade_dashboard.json"
DEFAULT_HTML_PATH = HOME / ".openclaw" / "canvas" / "trade-dashboard.html"
DEFAULT_SETUP_STATE_PATH = HOME / ".openclaw" / "state" / SKILL_ID / "setup_live_state.json"
DEFAULT_OPENROUTER_CATALOG_PATH = HOME / ".openclaw" / "state" / SKILL_ID / "openrouter_models.json"
DEFAULT_WHATSAPP_SCANNER_LOG_PATH = DEFAULT_STATE_DIR / "aspira-trading-whatsapp-scanner.log"
DEFAULT_WHATSAPP_SCANNER_STATE_PATH = DEFAULT_STATE_DIR / "aspira-trading-whatsapp-scanner-state.json"
DEFAULT_VALIDATED_ENV_PATH = DEFAULT_STATE_DIR / "hyperliquid-whatsapp-validated-v5.env"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models?output_modalities=text"
OPENROUTER_PRICING_URL = "https://openrouter.ai/pricing"
OPENROUTER_CATALOG_TTL_SECONDS = 60 * 60
OPENROUTER_CATALOG_SCHEMA_VERSION = 3
FALLBACK_OPENROUTER_MODELS = [
    {"id": "openrouter/free", "name": "Free Models Router", "provider": "openrouter", "input": 0.0, "output": 0.0, "ctx": 200000, "tools": True, "structured": False, "free": True, "variable_pricing": False, "modalities": "text->text", "note": "fallback free"},
    {"id": "openai/gpt-oss-20b", "name": "OpenAI gpt-oss-20b", "provider": "openai", "input": 0.03, "output": 0.14, "ctx": 131072, "tools": True, "structured": True, "free": False, "variable_pricing": False, "modalities": "text->text", "note": "fallback low cost"},
    {"id": "openai/gpt-5-nano", "name": "OpenAI GPT-5 Nano", "provider": "openai", "input": 0.05, "output": 0.40, "ctx": 400000, "tools": True, "structured": True, "free": False, "variable_pricing": False, "modalities": "text->text", "note": "fallback low cost"},
    {"id": "google/gemini-2.0-flash-001", "name": "Google Gemini 2.0 Flash", "provider": "google", "input": 0.10, "output": 0.40, "ctx": 1048576, "tools": True, "structured": True, "free": False, "variable_pricing": False, "modalities": "text+image->text", "note": "fallback long context"},
    {"id": "x-ai/grok-4.3", "name": "xAI Grok 4.3", "provider": "x-ai", "input": 1.25, "output": 2.50, "ctx": 1000000, "tools": True, "structured": True, "free": False, "variable_pricing": False, "modalities": "text+image->text", "note": "fallback reasoning"},
    {"id": "openai/gpt-chat-latest", "name": "OpenAI GPT Chat Latest", "provider": "openai", "input": 5.00, "output": 30.00, "ctx": 400000, "tools": True, "structured": True, "free": False, "variable_pricing": False, "modalities": "text+image+file->text", "note": "fallback premium"},
]
OPENROUTER_PLANS = [
    {
        "id": "free",
        "name": "Free",
        "platform_fee_pct": 0.0,
        "models": "25+ free models",
        "providers": "4 free providers",
        "rate_limit": "50 req/dia e 20 RPM",
        "token_pricing": "Somente modelos free",
        "byok": "-",
        "support": "Community",
        "note": "Nao atende 24/7 se o consumo passar de 50 chamadas/dia.",
    },
    {
        "id": "paygo",
        "name": "Pay-as-you-go",
        "platform_fee_pct": 5.5,
        "models": "400+ models",
        "providers": "60+ providers",
        "rate_limit": "Sem limite OpenRouter para modelos pagos; modelos free: 1000 req/dia com $10+ creditos",
        "token_pricing": "Preco por modelo, sem minimo",
        "byok": "1M req/mes gratis; 5% depois",
        "support": "Email",
        "note": "Plano recomendado para producao 24/7 com modelo pago barato.",
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "platform_fee_pct": None,
        "models": "400+ models",
        "providers": "60+ providers",
        "rate_limit": "Limites dedicados opcionais",
        "token_pricing": "Compromisso de volume e desconto negociado",
        "byok": "5M req/mes; preco customizado",
        "support": "SLA + Shared Slack",
        "note": "Faz sentido quando latencia, SLA e volume viram requisito.",
    },
]

LOG_PREFIX_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\s+\[(?P<level>[A-Z]+)\])?\s+(?P<body>.*)$"
)
SETUP_ENTRY_RE = re.compile(
    r"setup-live entry \| (?P<setup>[^ ]+) (?P<symbol>[^ ]+) \| "
    r"side=(?P<side>[^ ]+) \| mode=(?P<mode>[^ ]+)"
    r"(?: \| entry=(?P<entry_price>[-+0-9.eE]+) \| stop=(?P<stop_price>[-+0-9.eE]+) "
    r"\| tp=(?P<take_profit>[-+0-9.eE]+) \| targets=(?P<targets_csv>[^|]*))?"
    r" \| reason=(?P<reason>.*)$"
)
SETUP_EXIT_RE = re.compile(
    r"setup-live exit \| (?P<setup>[^ ]+) (?P<symbol>[^ ]+) \| "
    r"reason=(?P<reason>.*?) \| live=(?P<live>[-+0-9.eE]+)"
)
SETUP_SKIP_RE = re.compile(
    r"setup-live skip\s+\|\s+(?P<setup>[^ ]+) (?P<symbol>[^ ]+) \| reason=(?P<reason>.*)$"
)
SETUP_ANALYSIS_RE = re.compile(
    r"setup-live analise \| (?P<setup>[^ ]+) (?P<symbol>[^ ]+) \| "
    r"side=(?P<side>[^ ]+) \| (?P<reason>.*)$"
)
SETUP_ITERATION_RE = re.compile(
    r"setup-live iteracao=(?P<iteration>\d+) \| setups=(?P<setups>.*?) \| "
    r"symbols=(?P<symbols>.*?) \| dry_run=(?P<dry_run>\S+)"
)
SETUP_ACTIVE_RE = re.compile(
    r"^\s+(?P<setup>[^|]+)\|\s*(?P<symbol>[^|]+)\|\s*(?P<side>[^|]+)\|\s*"
    r"mode=(?P<mode>[^|]+)\|\s*margin=(?P<margin>[^|]+)\|\s*"
    r"lev=(?P<leverage>[-+0-9.]+)x\s*\|\s*liq=(?P<liq>[^|]+)\|\s*"
    r"buffer=(?P<buffer>[-+0-9.]+)%\s*\|\s*timeframe=(?P<timeframe>[^|]+)\|\s*"
    r"profile=(?P<profile>[^|]+)\|\s*stop=(?P<stop>[-+0-9.eE]+)\s*\|\s*"
    r"target=(?P<target>[-+0-9.eE]+)"
)
CCXT_ENTRY_RE = re.compile(
    r"entry \| (?P<exchange>[^ ]+) (?P<symbol>[^ ]+) \| setup=(?P<setup>[^ ]+) \| "
    r"side=(?P<side>[^ ]+) \| timeframe=(?P<timeframe>[^ ]+)"
    r"(?: \| entry=(?P<entry_price>[-+0-9.eE]+) \| stop=(?P<stop_price>[-+0-9.eE]+) "
    r"\| tp=(?P<take_profit>[-+0-9.eE]+) \| targets=(?P<targets_csv>[^|]*))?"
    r" \| reason=(?P<reason>.*)$"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_log_ts(raw: str | None) -> str:
    if not raw:
        return _utc_now_iso()
    try:
        return (
            datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except ValueError:
        return _utc_now_iso()


def _iso_from_epoch(raw: Any) -> str:
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return _utc_now_iso()


def _epoch_from_iso(raw: Any) -> float:
    try:
        text = str(raw or "").replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        text = str(raw).strip().rstrip("%")
        if not text or text in {"-", "N/A"}:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _clean_text(raw: Any) -> str:
    return str(raw or "").strip()


def _trade_key(source: str, ts: str, setup: str, symbol: str, side: str) -> str:
    parts = [source, ts, setup, symbol, side]
    return "|".join(part.replace("|", "/").strip().lower() for part in parts)


def _event_exists(events: list[dict[str, Any]], event_type: str, ts: str, description: str) -> bool:
    return any(
        item.get("type") == event_type
        and item.get("ts") == ts
        and item.get("description") == description
        for item in events
        if isinstance(item, dict)
    )


def _extract_target_index(reason: str) -> int:
    match = re.search(r"\bTP\s*(\d+)\b|\bALVO\s*(\d+)\b", reason, flags=re.IGNORECASE)
    if not match:
        return 0
    for group in match.groups():
        if group:
            return int(group)
    return 0


def _reason_kind(reason: str) -> str:
    text = reason.lower()
    if "stop" in text or "sl_" in text or "loss" in text:
        return "loss"
    if "tp" in text or "target" in text or "profit" in text or "atingido" in text or "alvo" in text:
        return "win"
    if "manual" in text or "cancel" in text or "fechad" in text:
        return "unknown"
    return "unknown"


def _normalize_signal_targets(signal: dict[str, Any]) -> list[float]:
    targets = signal.get("targets")
    if not isinstance(targets, list):
        csv_targets = _clean_text(signal.get("targets_csv"))
        targets = csv_targets.split(",") if csv_targets else []
    normalized = [_safe_float(target) for target in targets]
    normalized = [target for target in normalized if target > 0]
    take_profit = _safe_float(signal.get("take_profit"))
    if take_profit > 0 and take_profit not in normalized:
        normalized.append(take_profit)
    return normalized


def _normalize_target_levels(payload: dict[str, Any], targets_hit: int = 0) -> list[dict[str, Any]]:
    raw_levels = payload.get("target_levels")
    levels: list[dict[str, Any]] = []
    if isinstance(raw_levels, list):
        for idx, raw in enumerate(raw_levels, start=1):
            if isinstance(raw, dict):
                price = _safe_float(raw.get("price") or raw.get("target_price") or raw.get("value"))
                label = _clean_text(raw.get("label")) or f"TP{idx}"
                qty = _safe_float(raw.get("qty") or raw.get("quantity") or raw.get("nado_qty") or raw.get("kraken_qty"))
                skipped = _clean_text(raw.get("native_skipped_reason"))
                hit = bool(raw.get("hit")) or idx <= targets_hit
            else:
                price = _safe_float(raw)
                label = f"TP{idx}"
                qty = 0.0
                skipped = ""
                hit = idx <= targets_hit
            if price <= 0:
                continue
            level = {"label": label, "price": price, "hit": hit}
            if qty > 0:
                level["qty"] = qty
            if skipped:
                level["native_skipped_reason"] = skipped
            levels.append(level)
    if not levels:
        for idx, price in enumerate(_normalize_signal_targets(payload), start=1):
            levels.append({"label": f"TP{idx}", "price": price, "hit": idx <= targets_hit})
    return levels


def _target_level_prices(levels: Any) -> list[float]:
    if not isinstance(levels, list):
        return []
    prices: list[float] = []
    for item in levels:
        raw = item.get("price") if isinstance(item, dict) else item
        price = _safe_float(raw)
        if price > 0 and all(abs(price - existing) > 1e-12 for existing in prices):
            prices.append(price)
    return prices


def _trade_take_profit_values(trade: dict[str, Any]) -> list[float]:
    values: list[float] = []

    def add(raw: Any) -> None:
        value = _safe_float(raw)
        if value > 0 and all(abs(value - item) > 1e-12 for item in values):
            values.append(value)

    for target in _target_level_prices(trade.get("target_levels")):
        add(target)
    targets = trade.get("targets")
    if isinstance(targets, list):
        for target in targets:
            add(target)
    add(trade.get("target_price"))
    add(trade.get("take_profit"))
    return values


def _apply_target_hit(trade: dict[str, Any], target_index: int, ts: str, live_price: float = 0.0) -> bool:
    if target_index <= 0:
        return False
    changed = False
    levels = trade.get("target_levels")
    if not isinstance(levels, list):
        levels = _normalize_target_levels(trade)
    while len(levels) < target_index:
        idx = len(levels) + 1
        price = live_price if idx == target_index and live_price > 0 else 0.0
        levels.append({"label": f"TP{idx}", "price": price, "hit": False})
        changed = True
    target = levels[target_index - 1]
    if isinstance(target, dict):
        if not target.get("hit"):
            target["hit"] = True
            changed = True
        if not target.get("hit_at"):
            target["hit_at"] = ts
            changed = True
        if live_price > 0 and _safe_float(target.get("price")) <= 0:
            target["price"] = live_price
            changed = True
    trade["target_levels"] = levels
    prices = _target_level_prices(levels)
    if prices and trade.get("targets") != prices:
        trade["targets"] = prices
        changed = True
    return changed


def _initial_state() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _utc_now_iso(),
        "trades": [],
        "analyses": [],
        "live_exposures": {"updated_at": "", "positions": [], "summary": [], "error": ""},
        "signal_monitoring": _build_signal_monitoring_state(),
        "llm_catalog": _fallback_openrouter_catalog(),
        "summary": {},
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _latest_file(pattern: str, *, root: Path = DEFAULT_REPORT_DIR) -> Path | None:
    try:
        items = [path for path in root.glob(pattern) if path.is_file()]
    except Exception:
        return None
    return max(items, key=lambda path: path.stat().st_mtime, default=None)


def _file_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return values
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _parse_setup_asset_allowlist(raw: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for part in str(raw or "").strip().strip('"').strip("'").split(";"):
        if ":" not in part:
            continue
        setup, assets = part.split(":", 1)
        clean_assets: list[str] = []
        for asset in re.split(r"[|,]", assets):
            asset = re.sub(r"[^A-Z0-9]+", "", asset.upper())
            if asset and asset not in clean_assets:
                clean_assets.append(asset)
        if setup.strip() and clean_assets:
            grouped[setup.strip()] = clean_assets
    return grouped


def _scanner_process_status() -> dict[str, Any]:
    try:
        result = subprocess.run(["pgrep", "-af", "[c]cxt_entry_scanner.py"], check=False, capture_output=True, text=True, timeout=5)
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "pid": "", "count": 0, "error": str(exc)}
    rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    pid = rows[0].split(maxsplit=1)[0] if rows else ""
    return {"running": bool(rows), "pid": pid, "count": len(rows), "error": ""}


def _scanner_log_status(path: Path = DEFAULT_WHATSAPP_SCANNER_LOG_PATH) -> dict[str, Any]:
    status = {"updated_at": "", "age_seconds": None, "last_start": "", "last_done": "", "symbol_count": None, "last_line": ""}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")[-20000:]
        stat = path.stat()
    except Exception:
        return status
    now = time.time()
    status["updated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status["age_seconds"] = max(0, int(now - stat.st_mtime))
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if lines:
        status["last_line"] = lines[-1][-240:]
    for line in reversed(lines):
        if not status["last_done"] and "exchange done" in line:
            status["last_done"] = line[-240:]
        if not status["last_start"] and "scanner iniciado" in line:
            status["last_start"] = line[-240:]
        if status["symbol_count"] is None and "exchange symbols" in line:
            match = re.search(r"count=(\d+)", line)
            if match:
                status["symbol_count"] = int(match.group(1))
        if status["last_done"] and status["last_start"] and status["symbol_count"] is not None:
            break
    return status


def _normalize_change_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset": _clean_text(row.get("asset")),
        "setup": _clean_text(row.get("setup") or row.get("setup_label")),
        "timeframe": _clean_text(row.get("timeframe")),
        "score": _safe_float(row.get("score"), 0.0),
    }


def _normalize_signal_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "called_at_brt": _clean_text(row.get("called_at_brt")),
        "asset": _clean_text(row.get("asset")),
        "setup": _clean_text(row.get("setup")),
        "timeframe": _clean_text(row.get("timeframe")),
        "side": _clean_text(row.get("side")),
        "exit_reason": _clean_text(row.get("exit_reason")),
        "targets_hit": int(_safe_float(row.get("targets_hit"), 0)),
        "pnl_5x_pct": _safe_float(row.get("pnl_5x_pct"), 0.0),
    }


def _build_signal_monitoring_state() -> dict[str, Any]:
    env_values = _read_env_values(DEFAULT_VALIDATED_ENV_PATH)
    process_status = _scanner_process_status()
    log_status = _scanner_log_status()
    current = _read_json_file(DEFAULT_REPORT_DIR / "trade-allowlist-current.json")
    governance = _read_json_file(DEFAULT_REPORT_DIR / "trade-governance-history.json")
    weekly_path = _latest_file("trade-weekly-whatsapp-summary-*.json")
    weekly = _read_json_file(weekly_path) if weekly_path else {}
    allowlist_grouped = current.get("new_allowlist") if isinstance(current.get("new_allowlist"), dict) else {}
    if not allowlist_grouped:
        allowlist_grouped = _parse_setup_asset_allowlist(env_values.get("SETUP_TEST_SETUP_ASSET_ALLOWLIST", ""))
    combos = [
        {"setup": setup, "asset": asset}
        for setup, assets in allowlist_grouped.items()
        for asset in (assets if isinstance(assets, list) else [])
    ]
    changes = weekly.get("allowlist_changes") if isinstance(weekly.get("allowlist_changes"), dict) else {}
    week_summary = (weekly.get("week") or {}).get("summary") if isinstance(weekly.get("week"), dict) else {}
    d30_summary = (weekly.get("d30") or {}).get("summary") if isinstance(weekly.get("d30"), dict) else {}
    week_signals = (weekly.get("week") or {}).get("signals") if isinstance(weekly.get("week"), dict) else []
    week_groups = (weekly.get("week") or {}).get("groups") if isinstance(weekly.get("week"), dict) else []
    applications = governance.get("allowlist_applications") if isinstance(governance.get("allowlist_applications"), list) else []
    scanner_fresh = bool(process_status.get("running")) and _safe_float(log_status.get("age_seconds"), 999999) <= 20 * 60
    return {
        "updated_at": _utc_now_iso(),
        "scanner": {
            **process_status,
            **log_status,
            "fresh": scanner_fresh,
            "interval_seconds": int(_safe_float(env_values.get("SETUP_TEST_INTERVAL_SECONDS"), 0)),
            "setups": env_values.get("SETUP_TEST_SETUPS", ""),
            "symbols_mode": env_values.get("SETUP_TEST_SYMBOLS", ""),
            "whatsapp_enabled": env_values.get("SETUP_NOTIFY_WHATSAPP_ENABLED", "") in {"1", "true", "yes", "sim"},
        },
        "allowlist": {
            "grouped": allowlist_grouped,
            "combos": combos,
            "combo_count": len(combos),
            "asset_count": len({row["asset"] for row in combos}),
            "source_review": _clean_text(current.get("source_review")),
            "applied_at_brt": _clean_text(current.get("generated_at_brt")),
            "added": [_normalize_change_row(row) for row in changes.get("added", []) if isinstance(row, dict)],
            "removed": [_normalize_change_row(row) for row in changes.get("removed", []) if isinstance(row, dict)],
            "stayed_count": int(_safe_float(changes.get("stayed_count"), 0)),
        },
        "results": {
            "generated_at_brt": _clean_text(weekly.get("generated_at_brt")),
            "week": week_summary if isinstance(week_summary, dict) else {},
            "d30": d30_summary if isinstance(d30_summary, dict) else {},
            "interpretation": _clean_text(weekly.get("interpretation")),
            "groups": week_groups if isinstance(week_groups, list) else [],
            "signals": [_normalize_signal_result(row) for row in (week_signals if isinstance(week_signals, list) else [])],
        },
        "history": {
            "backtests": len(governance.get("backtests") or []) if isinstance(governance.get("backtests"), list) else 0,
            "reviews": len(governance.get("allowlist_reviews") or []) if isinstance(governance.get("allowlist_reviews"), list) else 0,
            "weekly_summaries": len(governance.get("weekly_whatsapp_summaries") or []) if isinstance(governance.get("weekly_whatsapp_summaries"), list) else 0,
            "applications": len(applications),
            "last_application": applications[-1] if applications else {},
        },
    }


def _fallback_openrouter_catalog(error: str = "") -> dict[str, Any]:
    return {
        "updated_at": _utc_now_iso(),
        "schema_version": OPENROUTER_CATALOG_SCHEMA_VERSION,
        "source": "fallback",
        "models_url": OPENROUTER_MODELS_URL,
        "pricing_url": OPENROUTER_PRICING_URL,
        "model_count": len(FALLBACK_OPENROUTER_MODELS),
        "models": FALLBACK_OPENROUTER_MODELS,
        "plans": OPENROUTER_PLANS,
        "plans_source": "fallback",
        "plans_updated_at": _utc_now_iso(),
        "plans_error": error,
        "error": error,
    }


def _created_iso(raw: Any) -> str:
    try:
        value = float(raw)
        if value <= 0:
            return ""
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _openrouter_price_per_million(raw: Any) -> float:
    value = _safe_float(raw, -1.0)
    if value < 0:
        return -1.0
    return value * 1_000_000.0


def _openrouter_unit_price(raw: Any) -> float:
    return _safe_float(raw, -1.0)


def _pricing_text_from_html(raw: str) -> str:
    text = re.sub(r"<script[^>]*>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = text.replace("\\u0026", "&").replace("\\n", " ").replace('\\"', '"')
    return re.sub(r"\s+", " ", text).strip()


def _pricing_row_values(text: str, start: str, end: str) -> list[str]:
    match = re.search(re.escape(start) + r"\s+(.*?)\s+" + re.escape(end), text)
    if not match:
        return []
    value = match.group(1).strip()
    if not value:
        return []
    return re.split(r"\s{2,}", value)


def _extract_openrouter_plans_from_pricing_text(text: str) -> list[dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    full_text = normalized
    comparison_start = normalized.find("Free Pay-as-you-go Enterprise Platform Fees")
    if comparison_start >= 0:
        normalized = normalized[comparison_start:]
    plans = [
        {**OPENROUTER_PLANS[0], "source": "openrouter-pricing"},
        {**OPENROUTER_PLANS[1], "source": "openrouter-pricing"},
        {**OPENROUTER_PLANS[2], "source": "openrouter-pricing"},
    ]

    def assign(field: str, values: list[str], offset: int = 0) -> None:
        for idx, value in enumerate(values[: len(plans) - offset], start=offset):
            if value:
                plans[idx][field] = value.strip()

    platform = re.search(r"Platform Fees\s+N/A\s+([0-9.]+%)\s+Bulk discounts available\s+Models", normalized)
    if platform:
        plans[0]["platform_fee_pct"] = 0.0
        plans[1]["platform_fee_pct"] = _safe_float(platform.group(1), 5.5)
        plans[2]["platform_fee_pct"] = None
        plans[0]["platform_fee"] = "N/A"
        plans[1]["platform_fee"] = platform.group(1)
        plans[2]["platform_fee"] = "Bulk discounts available"

    models = re.search(r"Models Explore all models →\s+(.+?)\s+Providers Explore all models →", normalized)
    if models:
        values = re.findall(r"\d+\+ (?:free )?models", models.group(1))
        assign("models", values)
    providers = re.search(r"Providers Explore all models →\s+(.+?)\s+Chat and API Access", normalized)
    if providers:
        values = re.findall(r"\d+\+? (?:free )?providers", providers.group(1))
        assign("providers", values)
    payment = re.search(r"Payment options\s+(.+?)\s+BYOK Limits", normalized)
    if payment:
        values = [item for item in ["", "Credit card, crypto & more", "Invoicing options"] if item or "Credit card, crypto & more" in payment.group(1)]
        plans[1]["payment_options"] = "Credit card, crypto & more" if "Credit card, crypto & more" in payment.group(1) else plans[1].get("payment_options", "")
        plans[2]["payment_options"] = "Invoicing options" if "Invoicing options" in payment.group(1) else plans[2].get("payment_options", "")
    byok = re.search(r"BYOK Limits Learn more →\s+(.+?)\s+Rate limits", normalized)
    if byok:
        chunk = byok.group(1)
        first = re.search(r"1M free reqs/month,\s*5% fee after", chunk)
        second = re.search(r"5M free reqs/month;\s*custom pricing", chunk)
        if first:
            plans[1]["byok"] = first.group(0)
        if second:
            plans[2]["byok"] = second.group(0)
    limits = re.search(r"Rate limits\s+(.+?)\s+Token Pricing", normalized)
    if limits:
        chunk = limits.group(1)
        matched = re.search(r"(50 reqs/day)\s+(High global limits)\s+(Optional dedicated limits)", chunk)
        if matched:
            assign("rate_limit", list(matched.groups()))
    token = re.search(r"Token Pricing\s+(.+?)\s+Support", normalized)
    if token:
        chunk = token.group(1)
        matched = re.search(
            r"(Free models only)\s+(No minimum spend\. Prices based on models)\s+(Volume commitments\. Prices based on models)",
            chunk,
        )
        if matched:
            assign("token_pricing", list(matched.groups()))
    support = re.search(r"Support\s+(.+?)\s+Get Started For Free", normalized)
    if support:
        chunk = support.group(1)
        matched = re.search(r"(Community Support)\s+(Email Support)\s+(Support SLA with Shared Slack Channel)", chunk)
        if matched:
            assign("support", list(matched.groups()))

    if "Free users have a limit of 50 requests per day and 20 requests per minute" in full_text:
        plans[0]["note"] = "Free: 50 requests/dia e 20 RPM; apenas modelos free."
    if "No limits on paid models" in full_text and "1000 request limit on free models" in full_text:
        plans[1]["note"] = "Pay-as-you-go: sem limite OpenRouter em modelos pagos; free ate 1000 req/dia com $10+ creditos."
    if "Support SLA with Shared Slack Channel" in full_text:
        plans[2]["note"] = "Enterprise: volume, SLA, limites dedicados opcionais e preco negociado."
    return plans


def _fetch_openrouter_plans() -> tuple[list[dict[str, Any]], str, str]:
    request = urllib.request.Request(
        OPENROUTER_PRICING_URL,
        headers={"Accept": "text/html", "User-Agent": f"{SKILL_ID}/dashboard"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
        plans = _extract_openrouter_plans_from_pricing_text(_pricing_text_from_html(raw))
        if len(plans) != 3:
            raise ValueError("pricing page sem planos suficientes")
        return plans, "openrouter-pricing", ""
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return OPENROUTER_PLANS, "fallback", str(exc)


def _normalize_openrouter_model(raw: dict[str, Any]) -> dict[str, Any] | None:
    model_id = _clean_text(raw.get("id"))
    if not model_id:
        return None
    pricing = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}
    architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    top_provider = raw.get("top_provider") if isinstance(raw.get("top_provider"), dict) else {}
    supported = raw.get("supported_parameters") if isinstance(raw.get("supported_parameters"), list) else []
    supported_set = {str(item) for item in supported}
    prompt = _openrouter_price_per_million(pricing.get("prompt"))
    completion = _openrouter_price_per_million(pricing.get("completion"))
    request_price = _openrouter_unit_price(pricing.get("request"))
    image_price = _openrouter_unit_price(pricing.get("image"))
    web_search_price = _openrouter_unit_price(pricing.get("web_search"))
    internal_reasoning = _openrouter_price_per_million(pricing.get("internal_reasoning"))
    cache_read = _openrouter_price_per_million(pricing.get("input_cache_read"))
    cache_write = _openrouter_price_per_million(pricing.get("input_cache_write"))
    input_modalities = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
    output_modalities = architecture.get("output_modalities") if isinstance(architecture.get("output_modalities"), list) else []
    modalities = f"{'+'.join(map(str, input_modalities)) or 'text'}->{'+'.join(map(str, output_modalities)) or 'text'}"
    ctx = int(_safe_float(raw.get("context_length") or top_provider.get("context_length")))
    provider = model_id.split("/", 1)[0]
    free = (prompt == 0 and completion == 0) or model_id.endswith(":free")
    variable_pricing = prompt < 0 or completion < 0
    return {
        "id": model_id,
        "name": _clean_text(raw.get("name")) or model_id,
        "provider": provider,
        "input": prompt,
        "output": completion,
        "request": request_price,
        "image": image_price,
        "web_search": web_search_price,
        "internal_reasoning": internal_reasoning,
        "input_cache_read": cache_read,
        "input_cache_write": cache_write,
        "ctx": ctx,
        "tools": "tools" in supported_set or "tool_choice" in supported_set,
        "structured": "structured_outputs" in supported_set or "response_format" in supported_set,
        "reasoning": "reasoning" in supported_set or "include_reasoning" in supported_set,
        "free": free,
        "variable_pricing": variable_pricing,
        "modalities": modalities,
        "created": _created_iso(raw.get("created")),
        "expiration_date": raw.get("expiration_date") or "",
        "note": "free" if free else ("preco variavel" if variable_pricing else "paid"),
    }


def _catalog_is_fresh(payload: dict[str, Any]) -> bool:
    fetched = _epoch_from_iso(payload.get("updated_at"))
    models = payload.get("models")
    sample = models[0] if isinstance(models, list) and models and isinstance(models[0], dict) else {}
    return (
        payload.get("schema_version") == OPENROUTER_CATALOG_SCHEMA_VERSION
        and bool(models)
        and "request" in sample
        and bool(payload.get("plans_source"))
        and (time.time() - fetched) <= OPENROUTER_CATALOG_TTL_SECONDS
    )


def _read_openrouter_cache(path: Path = DEFAULT_OPENROUTER_CATALOG_PATH) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    return payload if isinstance(models, list) and models else None


def _write_openrouter_cache(payload: dict[str, Any], path: Path = DEFAULT_OPENROUTER_CATALOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _fetch_openrouter_catalog() -> dict[str, Any]:
    cached = _read_openrouter_cache()
    if cached and _catalog_is_fresh(cached):
        return {**cached, "source": cached.get("source") or "openrouter-api-cache"}
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={"Accept": "application/json", "User-Agent": f"{SKILL_ID}/dashboard"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw_models = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(raw_models, list):
            raise ValueError("payload sem lista data")
        models = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            model = _normalize_openrouter_model(raw)
            if model is not None:
                models.append(model)
        if not models:
            raise ValueError("catalogo OpenRouter vazio")
        plans, plans_source, plans_error = _fetch_openrouter_plans()
        models.sort(
            key=lambda item: (
                bool(item.get("variable_pricing")),
                not bool(item.get("free")),
                max(_safe_float(item.get("input")), 0.0) + max(_safe_float(item.get("output")), 0.0),
                str(item.get("provider")),
                str(item.get("name")),
            )
        )
        catalog = {
            "updated_at": _utc_now_iso(),
            "schema_version": OPENROUTER_CATALOG_SCHEMA_VERSION,
            "source": "openrouter-api",
            "models_url": OPENROUTER_MODELS_URL,
            "pricing_url": OPENROUTER_PRICING_URL,
            "model_count": len(models),
            "models": models,
            "plans": plans,
            "plans_source": plans_source,
            "plans_updated_at": _utc_now_iso(),
            "plans_error": plans_error,
            "error": "",
        }
        _write_openrouter_cache(catalog)
        return catalog
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        if cached:
            return {**cached, "source": "openrouter-api-cache", "error": f"cache usado: {exc}"}
        return _fallback_openrouter_catalog(str(exc))


def _live_base_symbol(symbol: Any) -> str:
    text = _clean_text(symbol).upper()
    if "/" in text:
        return text.split("/", 1)[0]
    return text.split(":", 1)[0]


def _position_row(position: Any, venue: str) -> dict[str, Any]:
    symbol = _clean_text(getattr(position, "symbol", ""))
    size = _safe_float(getattr(position, "size", 0.0))
    mark_price = _safe_float(getattr(position, "mark_price", 0.0))
    notional = _safe_float(getattr(position, "notional_usd", 0.0)) or abs(size * mark_price)
    row = {
        "venue": venue,
        "symbol": symbol,
        "base": _live_base_symbol(symbol),
        "side": _clean_text(getattr(position, "side", "")).lower(),
        "size": size,
        "mark_price": mark_price,
        "entry_price": _safe_float(getattr(position, "entry_price", 0.0)),
        "notional_usd": notional,
        "signed_notional_usd": size * mark_price,
        "margin_mode": _clean_text(getattr(position, "margin_mode", "")),
        "leverage": _safe_float(getattr(position, "leverage", 0.0)),
        "liquidation_price": _safe_float(getattr(position, "liquidation_price", 0.0)),
        "unrealized_pnl": _safe_float(getattr(position, "unrealized_pnl", 0.0)),
    }
    product_id = _safe_float(getattr(position, "product_id", 0.0))
    if product_id:
        row["product_id"] = int(product_id)
    return row


def _summary_rows_from_live(summary: dict[str, dict[str, float]], drift_bps_limit: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for base in sorted(summary):
        item = summary[base]
        gross = _safe_float(item.get("gross_notional"))
        net = _safe_float(item.get("net_notional"))
        drift_bps = abs(net) / gross * 10000 if gross else 0.0
        if gross <= 0:
            status = "flat"
        elif drift_bps <= drift_bps_limit:
            status = "hedged"
        else:
            status = "unmatched"
        rows.append(
            {
                "base": base,
                "nado_notional": _safe_float(item.get("nado_notional")),
                "kraken_notional": _safe_float(item.get("kraken_notional")),
                "gross_notional": gross,
                "net_notional": net,
                "drift_bps": drift_bps,
                "status": status,
                "nado_qty": _safe_float(item.get("nado_qty")),
                "kraken_qty": _safe_float(item.get("kraken_qty")),
                "nado_mark": _safe_float(item.get("nado_mark")),
                "kraken_mark": _safe_float(item.get("kraken_mark")),
            }
        )
    return rows


class TradeDashboardRecorder:
    def __init__(
        self,
        *,
        state_path: Path | str | None = None,
        html_path: Path | str | None = None,
        setup_state_path: Path | str | None = None,
        max_trades: int = 5000,
        max_analyses: int = 1000,
    ) -> None:
        self.state_path = Path(state_path or os.environ.get("SETUP_DASHBOARD_STATE", DEFAULT_STATE_PATH)).expanduser()
        self.html_path = Path(html_path or os.environ.get("SETUP_DASHBOARD_HTML", DEFAULT_HTML_PATH)).expanduser()
        self.setup_state_path = Path(
            setup_state_path or os.environ.get("SETUP_DASHBOARD_SETUP_STATE", DEFAULT_SETUP_STATE_PATH)
        ).expanduser()
        self.max_trades = max_trades
        self.max_analyses = max_analyses
        self.state = self._load_state()
        self._dirty = False

    def _load_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            payload = _initial_state()
        if not isinstance(payload, dict):
            payload = _initial_state()
        payload.setdefault("version", 1)
        payload.setdefault("updated_at", _utc_now_iso())
        payload.setdefault("trades", [])
        payload.setdefault("analyses", [])
        payload.setdefault("live_exposures", {"updated_at": "", "positions": [], "summary": [], "error": ""})
        payload.setdefault("signal_monitoring", _build_signal_monitoring_state())
        payload.setdefault("llm_catalog", _fallback_openrouter_catalog())
        payload.setdefault("summary", {})
        if not isinstance(payload["trades"], list):
            payload["trades"] = []
        if not isinstance(payload["analyses"], list):
            payload["analyses"] = []
        if not isinstance(payload["live_exposures"], dict):
            payload["live_exposures"] = {"updated_at": "", "positions": [], "summary": [], "error": ""}
        if not isinstance(payload["signal_monitoring"], dict):
            payload["signal_monitoring"] = _build_signal_monitoring_state()
        if not isinstance(payload["llm_catalog"], dict):
            payload["llm_catalog"] = _fallback_openrouter_catalog()
        return payload

    def flush(self) -> None:
        if not self._dirty:
            return
        self.state["updated_at"] = _utc_now_iso()
        self.state["trades"] = self.state["trades"][-self.max_trades :]
        self.state["analyses"] = self.state["analyses"][-self.max_analyses :]
        self.state["signal_monitoring"] = _build_signal_monitoring_state()
        self.state["summary"] = self._build_summary()
        self._write_json()
        self._write_html()
        self._dirty = False

    def _write_json(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    def _write_html(self) -> None:
        self.html_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.html_path.with_suffix(self.html_path.suffix + ".tmp")
        tmp.write_text(self._render_html(), encoding="utf-8")
        tmp.replace(self.html_path)
        self._write_public_data_json()

    def _write_public_data_json(self) -> None:
        data_path = self.html_path.with_name("dashboard-data.json")
        tmp = data_path.with_suffix(data_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(data_path)

    def _trade_by_id(self, trade_id: str) -> dict[str, Any] | None:
        for trade in self.state["trades"]:
            if isinstance(trade, dict) and trade.get("id") == trade_id:
                return trade
        return None

    def _latest_trade(self, setup: str, symbol: str, side: str = "", *, include_closed: bool = False) -> dict[str, Any] | None:
        setup = setup.strip().lower()
        symbol = symbol.strip().upper()
        side = side.strip().lower()
        for trade in reversed(self.state["trades"]):
            if not isinstance(trade, dict):
                continue
            if str(trade.get("setup", "")).lower() != setup:
                continue
            if str(trade.get("symbol", "")).upper() != symbol:
                continue
            if side and str(trade.get("side", "")).lower() != side:
                continue
            if include_closed or trade.get("status") not in {"closed", "stopped", "cancelled"}:
                return trade
        return None

    def _append_trade_event(self, trade: dict[str, Any], event_type: str, ts: str, description: str, **extra: Any) -> bool:
        events = trade.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            trade["events"] = events
        if _event_exists(events, event_type, ts, description):
            return False
        event = {"ts": ts, "type": event_type, "description": description}
        event.update({key: value for key, value in extra.items() if value not in {"", None}})
        events.append(event)
        trade["events"] = events[-50:]
        return True

    def record_entry(self, entry: dict[str, Any], *, flush: bool = True) -> dict[str, Any]:
        ts = _clean_text(entry.get("created_at")) or _utc_now_iso()
        setup = _clean_text(entry.get("setup"))
        symbol = _clean_text(entry.get("symbol")).upper()
        side = _clean_text(entry.get("side")).lower()
        source = _clean_text(entry.get("source")) or "setup-live"
        trade_id = _clean_text(entry.get("id")) or _trade_key(source, ts, setup, symbol, side)
        trade = self._trade_by_id(trade_id)
        targets_hit = int(_safe_float(entry.get("targets_hit")))
        target_levels = _normalize_target_levels(entry, targets_hit=targets_hit)
        target_values = _target_level_prices(target_levels) or _normalize_signal_targets(entry)
        if trade is None and source in {"setup-live", "setup-live-state"}:
            candidate = self._latest_trade(setup, symbol, side)
            if candidate is not None and _clean_text(candidate.get("source")) in {"setup-live", "setup-live-state"}:
                seconds_apart = abs(_epoch_from_iso(candidate.get("created_at")) - _epoch_from_iso(ts))
                if seconds_apart <= 120:
                    trade = candidate
        if trade is None:
            trade = {
                "id": trade_id,
                "source": source,
                "created_at": ts,
                "updated_at": ts,
                "setup": setup,
                "symbol": symbol,
                "side": side,
                "mode": _clean_text(entry.get("mode")),
                "timeframe": _clean_text(entry.get("timeframe")),
                "reason": _clean_text(entry.get("reason")),
                "entry_price": _safe_float(entry.get("entry_price")),
                "stop_price": _safe_float(entry.get("stop_price")),
                "target_price": _safe_float(entry.get("target_price") or entry.get("take_profit")),
                "targets": target_values,
                "target_levels": target_levels,
                "leverage": _safe_float(entry.get("leverage")),
                "risk_profile": _clean_text(entry.get("risk_profile")),
                "status": _clean_text(entry.get("status")) or "open",
                "outcome": _clean_text(entry.get("outcome")) or "open",
                "targets_hit": targets_hit,
                "events": [],
            }
            self.state["trades"].append(trade)
            self._dirty = True
        changed = self._merge_trade_fields(trade, entry)
        if self._append_trade_event(trade, "Entry", ts, _clean_text(entry.get("reason")) or "entry signal"):
            changed = True
        if changed:
            trade["updated_at"] = ts
            self._dirty = True
        if flush:
            self.flush()
        return trade

    def _merge_trade_fields(self, trade: dict[str, Any], entry: dict[str, Any]) -> bool:
        changed = False
        text_fields = ["mode", "timeframe", "reason", "risk_profile", "status", "outcome", "exchange", "margin_mode"]
        for field in text_fields:
            value = _clean_text(entry.get(field))
            if value and trade.get(field) != value:
                trade[field] = value
                changed = True
        numeric_fields = ["entry_price", "stop_price", "target_price", "leverage", "last_price"]
        for field in numeric_fields:
            source_key = "take_profit" if field == "target_price" and entry.get("target_price") is None else field
            value = _safe_float(entry.get(source_key))
            if value > 0 and _safe_float(trade.get(field)) != value:
                trade[field] = value
                changed = True
        targets = _normalize_signal_targets(entry)
        if targets and trade.get("targets") != targets:
            trade["targets"] = targets
            changed = True
        targets_hit = int(_safe_float(entry.get("targets_hit"), -1))
        if targets_hit >= 0 and int(_safe_float(trade.get("targets_hit"))) != targets_hit:
            trade["targets_hit"] = targets_hit
            changed = True
        target_levels = _normalize_target_levels(entry, targets_hit=max(targets_hit, int(_safe_float(trade.get("targets_hit")))))
        if target_levels:
            if trade.get("target_levels") != target_levels:
                trade["target_levels"] = target_levels
                changed = True
            level_prices = _target_level_prices(target_levels)
            if level_prices and trade.get("targets") != level_prices:
                trade["targets"] = level_prices
                changed = True
        return changed

    def record_active_state(self, payload: dict[str, Any], *, flush: bool = True) -> None:
        ts = _clean_text(payload.get("ts")) or _utc_now_iso()
        setup = _clean_text(payload.get("setup"))
        symbol = _clean_text(payload.get("symbol")).upper()
        side = _clean_text(payload.get("side")).lower()
        trade = self._latest_trade(setup, symbol, side)
        if trade is None:
            trade = self.record_entry(
                {
                    "id": f"active|{setup.lower()}|{symbol.lower()}|{side}",
                    "source": "setup-live-state",
                    "created_at": ts,
                    "setup": setup,
                    "symbol": symbol,
                    "side": side,
                    "status": "open",
                    "outcome": "open",
                },
                flush=False,
            )
        update = {
            "mode": _clean_text(payload.get("mode")),
            "margin_mode": _clean_text(payload.get("margin")),
            "timeframe": _clean_text(payload.get("timeframe")),
            "risk_profile": _clean_text(payload.get("profile")),
            "stop_price": _safe_float(payload.get("stop")),
            "target_price": _safe_float(payload.get("target")),
            "leverage": _safe_float(payload.get("leverage")),
            "status": "open",
            "outcome": "win" if trade.get("outcome") == "win" else "open",
        }
        if self._merge_trade_fields(trade, update):
            trade["updated_at"] = ts
            self._dirty = True
        if flush:
            self.flush()

    def record_exit(self, payload: dict[str, Any], *, flush: bool = True) -> None:
        ts = _clean_text(payload.get("ts")) or _utc_now_iso()
        setup = _clean_text(payload.get("setup"))
        symbol = _clean_text(payload.get("symbol")).upper()
        reason = _clean_text(payload.get("reason"))
        live = _safe_float(payload.get("live"))
        trade = self._latest_trade(setup, symbol, include_closed=False)
        if trade is None:
            recent_trade = self._latest_trade(setup, symbol, include_closed=True)
            if (
                recent_trade is not None
                and _clean_text(recent_trade.get("side")).lower() in {"long", "short"}
                and _clean_text(recent_trade.get("source")) in {"setup-live", "setup-live-state"}
                and abs(_epoch_from_iso(ts) - _epoch_from_iso(recent_trade.get("updated_at") or recent_trade.get("created_at"))) <= 36 * 60 * 60
            ):
                trade = recent_trade
            else:
                self.record_analysis(
                    {
                        "ts": ts,
                        "kind": "orphan-exit",
                        "setup": setup,
                        "symbol": symbol,
                        "reason": f"saida sem entrada vinculada: {reason}",
                        "extra": {"live": live},
                    },
                    flush=flush,
                )
                return
        if _clean_text(trade.get("side")).lower() not in {"long", "short"}:
            self.record_analysis(
                {
                    "ts": ts,
                    "kind": "orphan-exit",
                    "setup": setup,
                    "symbol": symbol,
                    "reason": f"saida sem lado operacional vinculado: {reason}",
                    "extra": {"live": live},
                },
                flush=flush,
            )
            return
        kind = _reason_kind(reason)
        if kind == "win":
            target_index = _extract_target_index(reason) or int(_safe_float(trade.get("targets_hit"))) + 1
            trade["targets_hit"] = max(int(_safe_float(trade.get("targets_hit"))), target_index)
            if _apply_target_hit(trade, target_index, ts, live):
                self._dirty = True
            trade["outcome"] = "win"
            target_count = len(trade.get("target_levels") or trade.get("targets") or [])
            if "final" in reason.lower() or (target_count > 0 and trade["targets_hit"] >= target_count):
                trade["status"] = "closed"
                trade["closed_at"] = ts
            else:
                trade["status"] = "open"
        elif kind == "loss":
            trade["outcome"] = "loss"
            trade["status"] = "stopped"
            trade["closed_at"] = ts
        else:
            trade["outcome"] = trade.get("outcome") if trade.get("outcome") in {"win", "loss"} else "unknown"
            trade["status"] = "closed"
            trade["closed_at"] = ts
        if live > 0:
            trade["last_price"] = live
        if self._append_trade_event(trade, "Exit", ts, reason, live_price=live):
            self._dirty = True
        trade["updated_at"] = ts
        self._dirty = True
        if flush:
            self.flush()

    def record_analysis(self, payload: dict[str, Any], *, flush: bool = True) -> None:
        ts = _clean_text(payload.get("ts")) or _utc_now_iso()
        kind = _clean_text(payload.get("kind")) or "analysis"
        setup = _clean_text(payload.get("setup"))
        symbol = _clean_text(payload.get("symbol")).upper()
        reason = _clean_text(payload.get("reason"))
        analysis_id = "|".join([ts, kind, setup.lower(), symbol.lower(), reason[:120]])
        if any(item.get("id") == analysis_id for item in self.state["analyses"] if isinstance(item, dict)):
            return
        item = {
            "id": analysis_id,
            "ts": ts,
            "kind": kind,
            "setup": setup,
            "symbol": symbol,
            "side": _clean_text(payload.get("side")),
            "reason": reason,
        }
        extra = payload.get("extra")
        if isinstance(extra, dict):
            item["extra"] = extra
        self.state["analyses"].append(item)
        self._dirty = True
        if flush:
            self.flush()

    def process_setup_live_line(self, line: str, *, flush: bool = True) -> bool:
        match = LOG_PREFIX_RE.match(line.strip("\n"))
        if not match:
            return False
        ts = _iso_from_log_ts(match.group("ts"))
        body = match.group("body")

        entry = SETUP_ENTRY_RE.search(body)
        if entry:
            payload = entry.groupdict()
            payload["created_at"] = ts
            payload["source"] = "setup-live"
            self.record_entry(payload, flush=flush)
            return True

        exit_match = SETUP_EXIT_RE.search(body)
        if exit_match:
            payload = exit_match.groupdict()
            payload["ts"] = ts
            self.record_exit(payload, flush=flush)
            return True

        skip = SETUP_SKIP_RE.search(body)
        if skip:
            payload = skip.groupdict()
            payload.update({"ts": ts, "kind": "skip"})
            self.record_analysis(payload, flush=flush)
            return True

        analysis = SETUP_ANALYSIS_RE.search(body)
        if analysis:
            payload = analysis.groupdict()
            payload.update({"ts": ts, "kind": "analysis"})
            self.record_analysis(payload, flush=flush)
            return True

        iteration = SETUP_ITERATION_RE.search(body)
        if iteration:
            payload = iteration.groupdict()
            self.record_analysis(
                {
                    "ts": ts,
                    "kind": "scan",
                    "reason": f"iteracao={payload['iteration']} dry_run={payload['dry_run']}",
                    "extra": {
                        "setups": payload["setups"].split(","),
                        "symbols_count": len([item for item in payload["symbols"].split(",") if item]),
                    },
                },
                flush=flush,
            )
            return True

        if body.startswith("setup-live prontidao"):
            self.record_analysis({"ts": ts, "kind": "readiness", "reason": body}, flush=flush)
            return True

        active = SETUP_ACTIVE_RE.match(body)
        if active:
            payload = {key: value.strip() for key, value in active.groupdict().items()}
            payload["ts"] = ts
            self.record_active_state(payload, flush=flush)
            return True

        return False

    def process_ccxt_log_line(self, line: str, *, flush: bool = True) -> bool:
        match = LOG_PREFIX_RE.match(line.strip("\n"))
        if not match:
            return False
        ts = _iso_from_log_ts(match.group("ts"))
        body = match.group("body")
        entry = CCXT_ENTRY_RE.search(body)
        if not entry:
            return False
        payload = entry.groupdict()
        payload.update({"created_at": ts, "source": "ccxt-public-scanner", "status": "signal", "outcome": "open"})
        self.record_entry(payload, flush=False)
        self.record_analysis(
            {
                "ts": ts,
                "kind": "scanner-signal",
                "setup": payload["setup"],
                "symbol": payload["symbol"],
                "side": payload["side"],
                "reason": payload["reason"],
                "extra": {"exchange": payload["exchange"], "timeframe": payload["timeframe"]},
            },
            flush=flush,
        )
        return True

    def record_scanner_signals(self, signals: list[dict[str, Any]], *, flush: bool = True) -> None:
        for signal in signals:
            created_at = _iso_from_epoch(signal.get("created_at") or time.time())
            payload = dict(signal)
            payload.update(
                {
                    "created_at": created_at,
                    "source": "ccxt-public-scanner",
                    "status": "signal",
                    "outcome": "open",
                    "target_price": signal.get("take_profit"),
                }
            )
            self.record_entry(payload, flush=False)
            self.record_analysis(
                {
                    "ts": created_at,
                    "kind": "scanner-signal",
                    "setup": signal.get("setup"),
                    "symbol": signal.get("symbol"),
                    "side": signal.get("side"),
                    "reason": signal.get("reason"),
                    "extra": {"exchange": signal.get("exchange"), "timeframe": signal.get("timeframe")},
                },
                flush=False,
            )
        if flush:
            self.flush()

    def sync_setup_live_state(self, *, flush: bool = True) -> None:
        if not self.setup_state_path.exists():
            self._mark_stale_open_trades(set())
            if flush:
                self.flush()
            return
        try:
            states = json.loads(self.setup_state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(states, list):
            return
        active_keys: set[tuple[str, str, str]] = set()
        for state in states:
            if not isinstance(state, dict):
                continue
            active_keys.add(self._state_key(state.get("setup_key"), state.get("symbol"), state.get("side")))
            self._sync_single_setup_state(state)
        self._mark_stale_open_trades(active_keys)
        if flush:
            self.flush()

    def sync_live_exposures(self, *, flush: bool = True) -> None:
        try:
            from workspace.run import _load_env_file

            _load_env_file()
            from workspace.cli import _collect_live_status, build_engine

            eng = build_engine()
            nado_positions, kraken_positions, exposure_summary = _collect_live_status(eng)
            positions = [
                *[_position_row(position, "nado") for position in nado_positions],
                *[_position_row(position, "kraken") for position in kraken_positions],
            ]
            rows = _summary_rows_from_live(exposure_summary, _safe_float(getattr(eng, "drift_bps", 0.0)))
            self.state["live_exposures"] = {
                "updated_at": _utc_now_iso(),
                "positions": positions,
                "summary": rows,
                "count": len(positions),
                "gross_notional": sum(_safe_float(row.get("gross_notional")) for row in rows),
                "net_notional": sum(_safe_float(row.get("net_notional")) for row in rows),
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            previous = self.state.get("live_exposures") if isinstance(self.state.get("live_exposures"), dict) else {}
            self.state["live_exposures"] = {
                **previous,
                "updated_at": _utc_now_iso(),
                "error": str(exc),
            }
        self._dirty = True
        if flush:
            self.flush()

    def sync_llm_catalog(self, *, flush: bool = True) -> None:
        self.state["llm_catalog"] = _fetch_openrouter_catalog()
        self._dirty = True
        if flush:
            self.flush()

    @staticmethod
    def _state_key(setup: Any, symbol: Any, side: Any = "") -> tuple[str, str, str]:
        return (_clean_text(setup).lower(), _clean_text(symbol).upper(), _clean_text(side).lower())

    def _mark_stale_open_trades(self, active_keys: set[tuple[str, str, str]]) -> None:
        for trade in self.state.get("trades", []):
            if not isinstance(trade, dict):
                continue
            source = _clean_text(trade.get("source"))
            if source not in {"setup-live", "setup-live-state"}:
                continue
            if trade.get("status") not in {"open", "signal"}:
                continue
            key = self._state_key(trade.get("setup"), trade.get("symbol"), trade.get("side"))
            if key in active_keys:
                continue
            trade["status"] = "stale"
            if trade.get("outcome") == "open":
                trade["outcome"] = "unknown"
            self._dirty = True

    def _sync_single_setup_state(self, state: dict[str, Any]) -> None:
        pair_state = state.get("pair_state") if isinstance(state.get("pair_state"), dict) else {}
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        opened_at = _iso_from_epoch(state.get("opened_at_ts") or pair_state.get("opened_at") or time.time())
        effective_venue = _clean_text(state.get("effective_venue") or pair_state.get("effective_venue"))
        entry_price = _safe_float(state.get("reference_entry_price"))
        if effective_venue == "nado":
            entry_price = _safe_float(pair_state.get("nado_entry"), entry_price)
        elif effective_venue == "kraken":
            entry_price = _safe_float(pair_state.get("kraken_entry"), entry_price)
        else:
            entry_price = entry_price or _safe_float(pair_state.get("kraken_entry")) or _safe_float(pair_state.get("nado_entry"))
        targets = []
        target_levels_payload: list[dict[str, Any]] = []
        target_levels = metadata.get("target_levels")
        targets_hit = int(_safe_float(state.get("targets_hit")))
        if isinstance(target_levels, list):
            for idx, level in enumerate(target_levels, start=1):
                if not isinstance(level, dict):
                    continue
                price = _safe_float(level.get("price"))
                if price <= 0:
                    continue
                payload_level = {
                    "label": _clean_text(level.get("label")) or f"TP{idx}",
                    "price": price,
                    "hit": idx <= targets_hit,
                }
                qty = _safe_float(level.get("nado_qty")) or _safe_float(level.get("kraken_qty"))
                if qty > 0:
                    payload_level["qty"] = qty
                skipped = _clean_text(level.get("native_skipped_reason"))
                if skipped:
                    payload_level["native_skipped_reason"] = skipped
                target_levels_payload.append(payload_level)
            targets = _target_level_prices(target_levels_payload)
        trade = self.record_entry(
            {
                "source": "setup-live",
                "created_at": opened_at,
                "setup": state.get("setup_key"),
                "symbol": state.get("symbol"),
                "side": state.get("side"),
                "mode": state.get("execution_mode"),
                "margin_mode": state.get("margin_mode"),
                "timeframe": state.get("timeframe"),
                "risk_profile": state.get("hybrid_profile") or metadata.get("risk_profile"),
                "reason": state.get("entry_reason"),
                "entry_price": entry_price,
                "stop_price": state.get("stop_price"),
                "target_price": state.get("take_profit"),
                "targets": targets,
                "target_levels": target_levels_payload,
                "leverage": state.get("leverage") or metadata.get("leverage"),
                "targets_hit": targets_hit,
                "status": "open",
                "outcome": "win" if targets_hit > 0 else "open",
            },
            flush=False,
        )
        events = metadata.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_ts = _iso_from_epoch(event.get("ts") or state.get("opened_at_ts") or time.time())
                event_type = _clean_text(event.get("type")) or "Event"
                description = _clean_text(event.get("description"))
                if self._append_trade_event(trade, event_type, event_ts, description):
                    self._dirty = True
                kind = _reason_kind(f"{event_type} {description}")
                if kind == "win":
                    trade["outcome"] = "win"
                elif kind == "loss":
                    trade["outcome"] = "loss"
                    trade["status"] = "stopped"
        self._dirty = True

    def rebuild_from_logs(
        self,
        *,
        setup_log: Path | str | None = None,
        ccxt_log: Path | str | None = None,
        reset: bool = True,
        sync_live_exposure: bool = False,
        sync_llm_catalog: bool = True,
    ) -> None:
        if reset:
            self.state = _initial_state()
        setup_path = Path(setup_log or DEFAULT_LOG_PATH).expanduser()
        if setup_path.exists():
            with setup_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    self.process_setup_live_line(line, flush=False)
        ccxt_path = Path(ccxt_log or DEFAULT_CCXT_LOG_PATH).expanduser()
        if ccxt_path.exists():
            with ccxt_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    self.process_ccxt_log_line(line, flush=False)
        self.sync_setup_live_state(flush=False)
        if sync_live_exposure:
            self.sync_live_exposures(flush=False)
        if sync_llm_catalog:
            self.sync_llm_catalog(flush=False)
        self._dirty = True
        self.flush()

    def _build_summary(self) -> dict[str, Any]:
        trades = [trade for trade in self.state.get("trades", []) if isinstance(trade, dict)]
        operational_sources = {"setup-live", "setup-live-state"}
        setup_rows: dict[str, dict[str, Any]] = {}
        total_wins = 0
        total_losses = 0
        open_count = 0
        scanner_signals = 0
        operational_trades = 0
        for trade in trades:
            source = _clean_text(trade.get("source"))
            if source == "ccxt-public-scanner":
                scanner_signals += 1
            if source not in operational_sources:
                continue
            if _clean_text(trade.get("side")).lower() not in {"long", "short"}:
                continue
            operational_trades += 1
            setup = _clean_text(trade.get("setup")) or "unknown"
            row = setup_rows.setdefault(
                setup,
                {
                    "setup": setup,
                    "entries": 0,
                    "signals": 0,
                    "open": 0,
                    "wins": 0,
                    "losses": 0,
                    "unknown": 0,
                    "last_seen": "",
                    "latest_take_profit": 0.0,
                    "current_take_profits": [],
                },
            )
            row["entries"] += 1
            row["signals"] += 1
            row["last_seen"] = max(_clean_text(row.get("last_seen")), _clean_text(trade.get("updated_at") or trade.get("created_at")))
            take_profit_values = _trade_take_profit_values(trade)
            if take_profit_values:
                row["latest_take_profit"] = take_profit_values[-1]
            outcome = _clean_text(trade.get("outcome"))
            status = _clean_text(trade.get("status"))
            if status == "open":
                row["open"] += 1
                open_count += 1
                current_tps = row.setdefault("current_take_profits", [])
                if isinstance(current_tps, list):
                    current_tps.append(
                        {
                            "symbol": _clean_text(trade.get("symbol")),
                            "side": _clean_text(trade.get("side")),
                            "target_price": take_profit_values[-1] if take_profit_values else 0.0,
                            "targets": take_profit_values,
                            "target_levels": trade.get("target_levels") if isinstance(trade.get("target_levels"), list) else [],
                            "targets_hit": int(_safe_float(trade.get("targets_hit"))),
                            "updated_at": _clean_text(trade.get("updated_at") or trade.get("created_at")),
                        }
                    )
            if outcome == "win":
                row["wins"] += 1
                total_wins += 1
            elif outcome == "loss":
                row["losses"] += 1
                total_losses += 1
            elif status not in {"open", "signal"}:
                row["unknown"] += 1
        setup_rank = []
        for row in setup_rows.values():
            resolved = int(row["wins"]) + int(row["losses"])
            row["resolved"] = resolved
            row["win_rate"] = (float(row["wins"]) / resolved * 100.0) if resolved else None
            setup_rank.append(row)
        setup_performance = sorted(
            setup_rank,
            key=lambda item: (
                int(item["entries"]),
                int(item["resolved"]),
                item["win_rate"] if item["win_rate"] is not None else -1.0,
            ),
            reverse=True,
        )
        setup_rank.sort(
            key=lambda item: (
                item["win_rate"] is not None,
                item["win_rate"] or -1.0,
                item["resolved"],
                item["entries"],
            ),
            reverse=True,
        )
        resolved_total = total_wins + total_losses
        live_exposures = self.state.get("live_exposures") if isinstance(self.state.get("live_exposures"), dict) else {}
        live_positions = live_exposures.get("positions") if isinstance(live_exposures.get("positions"), list) else []
        live_summary = live_exposures.get("summary") if isinstance(live_exposures.get("summary"), list) else []
        return {
            "total_trades": len(trades),
            "operational_trades": operational_trades,
            "scanner_signals": scanner_signals,
            "open_trades": open_count,
            "live_exposure_count": len(live_positions),
            "live_exposure_assets": len(live_summary),
            "live_exposure_gross_notional": sum(_safe_float(row.get("gross_notional")) for row in live_summary if isinstance(row, dict)),
            "live_exposure_net_notional": sum(_safe_float(row.get("net_notional")) for row in live_summary if isinstance(row, dict)),
            "wins": total_wins,
            "losses": total_losses,
            "resolved_trades": resolved_total,
            "win_rate": (total_wins / resolved_total * 100.0) if resolved_total else None,
            "best_setups": setup_rank[:10],
            "setup_performance": setup_performance,
        }

    def _render_html(self) -> str:
        return _render_operational_html(self.state)

def _render_operational_html(state: dict[str, Any]) -> str:
    state_json = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    html = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw Trade Ops Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #071015;
      --bg-2: #0c171d;
      --panel: rgba(10, 24, 32, .88);
      --panel-strong: rgba(12, 31, 42, .96);
      --panel-soft: rgba(255, 255, 255, .045);
      --text: #f7fbff;
      --muted: #96aab8;
      --muted-2: #6f8798;
      --border: rgba(154, 216, 255, .16);
      --green: #24c8a8;
      --blue: #4aa3ff;
      --amber: #ffb86b;
      --red: #ff6b7a;
      --purple: #b891ff;
      --shadow: 0 22px 70px rgba(0, 0, 0, .32);
    }
    * { box-sizing: border-box; }
    html { min-width: 320px; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, rgba(20, 36, 44, .74) 0%, rgba(7, 16, 21, 0) 340px),
        linear-gradient(135deg, #061015 0%, #0b151b 52%, #0c1015 100%);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
      overflow-x: hidden;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(255,255,255,.032) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.026) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.58), transparent 72%);
      animation: gridDrift 26s linear infinite;
    }
    main {
      position: relative;
      z-index: 1;
      width: min(1520px, calc(100% - 28px));
      margin: 0 auto;
      padding: 14px 0 36px;
    }
    .ops-header {
      position: relative;
      padding: 10px 0 16px;
      border-bottom: 1px solid rgba(154, 216, 255, .16);
    }
    .ops-header::before {
      display: none;
    }
    .header-grid {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(300px, 440px);
      gap: 18px;
      align-items: center;
    }
    .brand-lockup { align-self: center; }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 30px;
      padding: 0 11px;
      border: 1px solid rgba(36, 200, 168, .38);
      border-radius: 999px;
      background: rgba(4, 17, 23, .68);
      color: #c9fff4;
      font-size: 12px;
      font-weight: 760;
      box-shadow: 0 0 26px rgba(36, 200, 168, .12);
    }
    .eyebrow::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 16px var(--green);
      animation: livePulse 1.8s ease-in-out infinite;
    }
    h1 {
      max-width: 650px;
      margin: 12px 0 0;
      font-size: clamp(30px, 3.7vw, 46px);
      line-height: 1.02;
      font-weight: 860;
      letter-spacing: 0;
    }
    .hero-copy {
      max-width: 610px;
      margin: 10px 0 0;
      color: #c8d9e6;
      font-size: 14px;
      line-height: 1.5;
    }
    .status-board {
      display: grid;
      grid-template-columns: 1.15fr 1fr;
      gap: 10px 12px;
      padding: 12px;
      border: 1px solid rgba(154, 216, 255, .18);
      border-radius: 8px;
      background: rgba(4, 15, 21, .76);
      backdrop-filter: blur(16px);
      box-shadow: 0 14px 42px rgba(0, 0, 0, .24);
    }
    .status-board .status-row:first-child {
      grid-column: 1 / -1;
    }
    .status-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-width: 0;
    }
    .status-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
      text-transform: uppercase;
    }
    .status-value {
      color: #eef8ff;
      font-size: 13px;
      text-align: right;
      overflow-wrap: anywhere;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 30px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(154, 216, 255, .16);
      background: rgba(255, 255, 255, .06);
      color: #d9e9f5;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .status-pill::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 14px currentColor;
    }
    .status-pill.fresh { color: #b9f8cf; background: rgba(34, 197, 94, .14); }
    .status-pill.stale { color: #ffe0ad; background: rgba(245, 158, 11, .16); }
    .status-pill.offline { color: #ffc6c6; background: rgba(239, 68, 68, .15); }
    .quick-tags {
      position: relative;
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 14px;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 11px;
      border: 1px solid rgba(154, 216, 255, .16);
      border-radius: 8px;
      background: rgba(7, 22, 31, .68);
      color: #dbeafe;
      font-size: 12px;
      font-weight: 680;
      backdrop-filter: blur(14px);
    }
    .grid { display: grid; gap: 14px; }
    .kpis {
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      margin: 14px 0;
      position: relative;
      z-index: 3;
    }
    .panel {
      min-width: 0;
      background: linear-gradient(180deg, rgba(10, 28, 39, .86), rgba(7, 18, 27, .76));
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 18px 58px rgba(0, 0, 0, .24);
      backdrop-filter: blur(18px);
      transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
    }
    .panel:hover {
      transform: translateY(-1px);
      border-color: rgba(74, 163, 255, .34);
      box-shadow: 0 22px 70px rgba(0, 0, 0, .32), 0 0 0 1px rgba(74, 163, 255, .07);
    }
    .kpi {
      position: relative;
      min-height: 112px;
      padding: 16px;
      overflow: hidden;
      animation: liftIn .5s ease both;
    }
    .kpi:nth-child(2) { animation-delay: .04s; }
    .kpi:nth-child(3) { animation-delay: .08s; }
    .kpi:nth-child(4) { animation-delay: .12s; }
    .kpi:nth-child(5) { animation-delay: .16s; }
    .kpi:nth-child(6) { animation-delay: .20s; }
    .kpi::after {
      content: "";
      position: absolute;
      inset: auto 12px 0;
      height: 3px;
      border-radius: 8px 8px 0 0;
      background: linear-gradient(90deg, var(--green), var(--blue), var(--amber));
      opacity: .62;
    }
    .kpi .label {
      color: #a9bed0;
      font-size: 11px;
      text-transform: uppercase;
      font-weight: 800;
    }
    .kpi .value {
      margin-top: 7px;
      color: #ffffff;
      font-size: clamp(26px, 3.2vw, 40px);
      line-height: 1;
      font-weight: 860;
      text-shadow: 0 0 26px rgba(74, 163, 255, .14);
    }
    .kpi .note {
      margin-top: 9px;
      color: #8fa7b9;
      font-size: 12px;
      line-height: 1.35;
    }
    .section {
      min-width: 0;
      padding: 18px;
      overflow: visible;
    }
    .section-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    h2 {
      margin: 0;
      color: #f7fbff;
      font-size: 17px;
      line-height: 1.25;
      font-weight: 800;
      letter-spacing: 0;
    }
    .section-note {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .count-pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, .055);
      border: 1px solid rgba(154, 216, 255, .12);
      color: #dbeafe;
      font-size: 12px;
      font-weight: 760;
      white-space: nowrap;
    }
    .view-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 14px;
    }
    .view-tab {
      appearance: none;
      min-height: 38px;
      padding: 0 14px;
      border: 1px solid rgba(154, 216, 255, .16);
      border-radius: 999px;
      background: rgba(5, 15, 23, .72);
      color: #d7e9f6;
      font: inherit;
      font-size: 12px;
      font-weight: 820;
      text-transform: uppercase;
      cursor: pointer;
    }
    .view-tab.active {
      border-color: rgba(36, 200, 168, .44);
      background: rgba(36, 200, 168, .16);
      color: #c9fff4;
    }
    .view-panel { display: none; }
    .view-panel.active { display: block; }
    .active-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      min-width: 0;
    }
    .trade-card {
      position: relative;
      display: grid;
      gap: 12px;
      min-width: 0;
      min-height: 178px;
      padding: 14px;
      border: 1px solid rgba(154, 216, 255, .14);
      border-radius: 8px;
      background: rgba(255, 255, 255, .043);
      overflow: hidden;
    }
    .trade-card::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: var(--blue);
    }
    .trade-card.long::before { background: var(--blue); }
    .trade-card.short::before { background: var(--red); }
    .trade-card.no-side::before { background: var(--amber); }
    .trade-card.live-position {
      border-color: rgba(255, 184, 107, .24);
      background: rgba(255, 184, 107, .055);
    }
    .trade-card.live-position.hedged {
      border-color: rgba(36, 200, 168, .28);
      background: rgba(36, 200, 168, .055);
    }
    .trade-title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      min-width: 0;
    }
    .trade-title > * { min-width: 0; }
    .symbol {
      color: #ffffff;
      font-size: 19px;
      font-weight: 850;
      line-height: 1.1;
    }
    .setup-name {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .trade-metrics {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .metric {
      min-width: 0;
      padding: 8px;
      border-radius: 6px;
      background: rgba(0, 0, 0, .20);
      border: 1px solid rgba(255, 255, 255, .06);
    }
    .metric span {
      display: block;
      color: var(--muted-2);
      font-size: 10px;
      text-transform: uppercase;
      font-weight: 780;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      color: #eaf6ff;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .reason {
      color: #c3d4e1;
      font-size: 12px;
      line-height: 1.45;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .live-position .reason {
      display: block;
      -webkit-line-clamp: unset;
      overflow: visible;
    }
    .analysis-section {
      display: flex;
      flex-direction: column;
      max-height: min(760px, calc(100vh - 96px));
      overflow: hidden;
    }
    .analysis-section .section-head {
      flex: 0 0 auto;
    }
    #recentAnalyses {
      min-height: 0;
      overflow: auto;
      padding-right: 2px;
      scrollbar-width: thin;
    }
    .analysis-list {
      display: grid;
      gap: 10px;
      min-width: 0;
    }
    .analysis-card {
      display: grid;
      gap: 9px;
      min-width: 0;
      padding: 12px;
      border: 1px solid rgba(154, 216, 255, .12);
      border-radius: 8px;
      background: rgba(255, 255, 255, .038);
    }
    .analysis-card-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }
    .analysis-title {
      color: #f7fbff;
      font-size: 13px;
      line-height: 1.3;
      font-weight: 820;
      overflow-wrap: anywhere;
    }
    .analysis-meta,
    .analysis-extra {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }
    .analysis-meta span,
    .analysis-extra span {
      display: inline-flex;
      max-width: 100%;
      min-height: 22px;
      align-items: center;
      padding: 0 7px;
      border-radius: 999px;
      border: 1px solid rgba(154, 216, 255, .10);
      background: rgba(0, 0, 0, .18);
      color: #9fb6c8;
      font-size: 10px;
      font-weight: 740;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .analysis-reason {
      color: #d6e5f1;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .analysis-extra span {
      color: #cbdceb;
      white-space: normal;
    }
    .layout {
      grid-template-columns: minmax(360px, .9fr) minmax(640px, 1.55fr);
      align-items: start;
      margin-top: 14px;
    }
    .priority-layout {
      grid-template-columns: minmax(0, 1.15fr) minmax(420px, .85fr);
      align-items: start;
      margin-bottom: 14px;
    }
    .exposure-layout {
      margin-bottom: 14px;
    }
    .signal-layout {
      grid-template-columns: minmax(360px, .82fr) minmax(620px, 1.18fr);
      align-items: start;
      margin-bottom: 14px;
    }
    .signal-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .signal-card {
      padding: 12px;
      border: 1px solid rgba(154, 216, 255, .11);
      border-radius: 8px;
      background: rgba(255, 255, 255, .04);
    }
    .signal-card .k { color: var(--muted); font-size: 11px; font-weight: 800; text-transform: uppercase; }
    .signal-card .v { margin-top: 5px; font-size: 20px; font-weight: 860; }
    .signal-list { display: grid; gap: 7px; margin-top: 10px; }
    .signal-list-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 9px;
      border-radius: 8px;
      background: rgba(255, 255, 255, .035);
      color: #d9ebf7;
      font-size: 12px;
    }
    .signal-list-row span:last-child { color: var(--muted); text-align: right; }
    .signal-table { max-height: 440px; overflow: auto; }
    .priority-layout .table-wrap {
      max-height: 520px;
      overflow: auto;
    }
    .stack { display: grid; gap: 14px; }
    .bars { display: grid; gap: 10px; }
    .edge-row {
      display: grid;
      grid-template-columns: minmax(118px, 170px) 1fr 82px 118px;
      align-items: center;
      gap: 10px;
      padding: 11px;
      border: 1px solid rgba(154, 216, 255, .10);
      border-radius: 8px;
      background: rgba(255, 255, 255, .035);
      font-size: 12px;
    }
    .bar-label {
      min-width: 0;
      color: #e8f4ff;
      font-weight: 760;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .bar-track {
      height: 12px;
      border-radius: 999px;
      background: rgba(148, 163, 184, .16);
      overflow: hidden;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .05);
    }
    .bar-fill {
      height: 100%;
      min-width: 3%;
      border-radius: 999px;
      background: linear-gradient(90deg, #24c8a8, #4aa3ff 58%, #ffb86b);
      box-shadow: 0 0 18px rgba(36, 200, 168, .22);
      animation: barGrow .72s ease both;
    }
    .bar-value {
      color: #dcebf7;
      text-align: right;
      font-weight: 800;
    }
    .confidence {
      justify-self: end;
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, .08);
      color: var(--muted);
      background: rgba(255, 255, 255, .04);
      font-size: 10px;
      font-weight: 800;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .confidence.strong { color: #b9f8cf; background: rgba(34, 197, 94, .13); }
    .confidence.ok { color: #d7ecff; background: rgba(74, 163, 255, .14); }
    .confidence.low { color: #ffe0ad; background: rgba(245, 158, 11, .14); }
    .edge-meta {
      grid-column: 1 / -1;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .toolbar {
      display: grid;
      gap: 10px;
      padding: 10px;
      margin-bottom: 12px;
      border: 1px solid rgba(154, 216, 255, .12);
      border-radius: 8px;
      background: rgba(255, 255, 255, .035);
    }
    .report-layout {
      grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr);
      align-items: start;
      margin-top: 14px;
    }
    .report-block {
      display: grid;
      gap: 12px;
      min-width: 0;
    }
    .report-copy {
      color: #cbdceb;
      font-size: 13px;
      line-height: 1.55;
    }
    .report-copy h3 {
      margin: 0 0 6px;
      color: #f7fbff;
      font-size: 14px;
      line-height: 1.3;
      font-weight: 840;
    }
    .report-copy p { margin: 0 0 10px; }
    .report-copy ul {
      margin: 0 0 10px;
      padding-left: 18px;
    }
    .report-copy li { margin: 4px 0; }
    .cost-controls {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .cost-result {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .cost-box {
      min-width: 0;
      padding: 12px;
      border: 1px solid rgba(154, 216, 255, .12);
      border-radius: 8px;
      background: rgba(0, 0, 0, .18);
    }
    .cost-box span {
      display: block;
      color: var(--muted-2);
      font-size: 10px;
      font-weight: 820;
      text-transform: uppercase;
    }
    .cost-box strong {
      display: block;
      margin-top: 5px;
      color: #f7fbff;
      font-size: 18px;
      line-height: 1.2;
    }
    .source-links {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .filter-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .filter-group {
      min-width: 0;
      display: grid;
      gap: 6px;
    }
    .filter-label {
      color: var(--muted-2);
      font-size: 10px;
      font-weight: 820;
      text-transform: uppercase;
    }
    .filter-buttons,
    .setup-filter {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }
    .filter-btn {
      appearance: none;
      min-height: 30px;
      padding: 0 9px;
      border: 1px solid rgba(154, 216, 255, .14);
      border-radius: 999px;
      background: rgba(5, 15, 23, .62);
      color: #d7e9f6;
      font: inherit;
      font-size: 11px;
      font-weight: 780;
      text-transform: uppercase;
      cursor: pointer;
      transition: border-color .18s ease, background .18s ease, color .18s ease;
    }
    .filter-btn:hover,
    .filter-btn.active {
      border-color: rgba(36, 200, 168, .44);
      background: rgba(36, 200, 168, .14);
      color: #c9fff4;
    }
    .setup-filter {
      padding-top: 2px;
    }
    input, select {
      width: 100%;
      min-width: 0;
      height: 36px;
      border: 1px solid rgba(154, 216, 255, .18);
      border-radius: 6px;
      background: rgba(5, 15, 23, .76);
      color: #eef7ff;
      padding: 0 10px;
      outline: none;
      font: inherit;
      font-size: 13px;
      transition: border-color .18s ease, box-shadow .18s ease;
    }
    input:focus, select:focus {
      border-color: rgba(74, 163, 255, .64);
      box-shadow: 0 0 0 3px rgba(74, 163, 255, .13);
    }
    .check-row {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      padding: 0 10px;
      border: 1px solid rgba(154, 216, 255, .12);
      border-radius: 6px;
      background: rgba(5, 15, 23, .46);
      color: #d7e9f6;
      font-size: 12px;
      font-weight: 760;
      cursor: pointer;
    }
    .check-row input {
      width: 16px;
      height: 16px;
      accent-color: var(--green);
    }
    .table-wrap {
      width: 100%;
      overflow-x: auto;
      scrollbar-width: thin;
    }
    .history-section {
      display: flex;
      flex-direction: column;
      max-height: min(680px, calc(100vh - 96px));
      overflow: hidden;
    }
    .history-section .section-head,
    .history-section .toolbar,
    .history-section .table-pager {
      flex: 0 0 auto;
    }
    .history-section .toolbar {
      margin-bottom: 10px;
    }
    #recentTrades {
      min-height: 0;
      overflow: hidden;
    }
    .history-section .table-wrap {
      max-height: clamp(300px, 42vh, 440px);
      overflow: auto;
      border: 1px solid rgba(154, 216, 255, .10);
      border-radius: 8px;
      background: rgba(0, 0, 0, .10);
    }
    .history-section table {
      min-width: 920px;
      border-spacing: 0 6px;
    }
    .history-section td {
      padding: 8px;
    }
    .history-section th {
      position: sticky;
      top: 0;
      z-index: 2;
      padding-top: 10px;
      background: rgba(7, 18, 27, .96);
    }
    .table-pager {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .pager-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .pager-btn {
      appearance: none;
      min-height: 32px;
      padding: 0 11px;
      border: 1px solid rgba(154, 216, 255, .16);
      border-radius: 999px;
      background: rgba(5, 15, 23, .72);
      color: #d7e9f6;
      font: inherit;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      cursor: pointer;
    }
    .pager-btn:hover:not(:disabled) {
      border-color: rgba(36, 200, 168, .44);
      background: rgba(36, 200, 168, .14);
      color: #c9fff4;
    }
    .pager-btn:disabled {
      cursor: not-allowed;
      opacity: .45;
    }
    .pager-label {
      color: #dbeafe;
      font-weight: 760;
      white-space: nowrap;
    }
    .target-ladder {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow: hidden;
    }
    .target-chip {
      display: inline-flex;
      align-items: center;
      flex: 0 1 auto;
      min-width: 0;
      min-height: 22px;
      max-width: 100%;
      padding: 3px 7px;
      border-radius: 999px;
      border: 1px solid rgba(154, 216, 255, .13);
      background: rgba(74, 163, 255, .10);
      color: #d7ecff;
      font-size: 10px;
      font-weight: 780;
      line-height: 1.25;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .target-chip.hit {
      border-color: rgba(36, 200, 168, .34);
      background: rgba(36, 200, 168, .16);
      color: #bfffee;
    }
    .target-chip.pending {
      border-color: rgba(255, 184, 107, .28);
      background: rgba(255, 184, 107, .12);
      color: #ffe0ad;
    }
    .target-chip.missing {
      border-color: rgba(148, 163, 184, .16);
      background: rgba(148, 163, 184, .08);
      color: var(--muted);
    }
    .tp-list {
      display: grid;
      gap: 4px;
      color: #dcebf7;
      font-size: 11px;
      line-height: 1.35;
    }
    .tp-list > span {
      display: inline-flex;
      width: fit-content;
      max-width: 100%;
      min-height: 22px;
      align-items: center;
      padding: 0 7px;
      border-radius: 999px;
      border: 1px solid rgba(36, 200, 168, .18);
      background: rgba(36, 200, 168, .10);
      color: #c9fff4;
      overflow-wrap: anywhere;
    }
    table {
      width: 100%;
      min-width: 1080px;
      border-collapse: separate;
      border-spacing: 0 8px;
      table-layout: fixed;
      font-size: 12px;
    }
    th {
      padding: 0 8px 4px;
      color: #8fa7b9;
      text-align: left;
      text-transform: uppercase;
      font-size: 10px;
      font-weight: 820;
      letter-spacing: .04em;
    }
    td {
      padding: 10px 8px;
      background: rgba(255, 255, 255, .04);
      color: #dcebf7;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    tbody tr td:first-child { border-radius: 8px 0 0 8px; }
    tbody tr td:last-child { border-radius: 0 8px 8px 0; }
    tbody tr { transition: transform .16s ease, filter .16s ease; }
    tbody tr:hover { transform: translateX(2px); filter: brightness(1.1); }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, .10);
      background: rgba(59, 130, 246, .16);
      color: #cfe8ff;
      font-size: 11px;
      font-weight: 760;
      white-space: nowrap;
    }
    .pill.win { background: rgba(34, 197, 94, .16); color: #b9f8cf; }
    .pill.loss { background: rgba(239, 68, 68, .16); color: #ffc6c6; }
    .pill.open { background: rgba(74, 163, 255, .18); color: #d7ecff; }
    .pill.long { background: rgba(74, 163, 255, .18); color: #d7ecff; }
    .pill.short { background: rgba(239, 68, 68, .13); color: #ffc6c6; }
    .pill.no-side { background: rgba(245, 158, 11, .14); color: #ffe0ad; }
    .pill.signal { background: rgba(184, 145, 255, .15); color: #e3d6ff; }
    .pill.stale { background: rgba(245, 158, 11, .14); color: #ffe0ad; }
    .pill.hedged { background: rgba(36, 200, 168, .16); color: #bfffee; }
    .pill.unmatched { background: rgba(245, 158, 11, .14); color: #ffe0ad; }
    .pill.skip { background: rgba(245, 158, 11, .18); color: #ffe0ad; }
    .muted { color: var(--muted); }
    .empty {
      color: var(--muted);
      padding: 18px 4px;
      font-size: 13px;
    }
    @keyframes gridDrift {
      from { background-position: 0 0, 0 0; }
      to { background-position: 48px 48px, 48px 48px; }
    }
    @keyframes livePulse {
      0%, 100% { transform: scale(.86); opacity: .68; }
      50% { transform: scale(1.18); opacity: 1; }
    }
    @keyframes signalWash {
      0%, 100% { opacity: .62; }
      50% { opacity: .9; }
    }
    @keyframes liftIn {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes barGrow {
      from { transform: scaleX(.04); transform-origin: left; }
      to { transform: scaleX(1); transform-origin: left; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
      }
    }
    @media (max-width: 1180px) {
      .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 14px 0; }
      .priority-layout,
      .layout,
      .report-layout { grid-template-columns: 1fr; }
      .header-grid { grid-template-columns: 1fr; align-items: start; }
      .status-board { max-width: 520px; }
    }
    @media (max-width: 760px) {
      main { width: min(100% - 20px, 760px); padding-top: 10px; }
      .ops-header { padding: 8px 0 14px; }
      .header-grid { gap: 14px; }
      .status-board { grid-template-columns: 1fr; }
      .quick-tags { margin-top: 16px; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi { min-height: 104px; padding: 14px; }
      .trade-metrics { grid-template-columns: 1fr; }
      .filter-grid { grid-template-columns: 1fr; }
      .cost-controls,
      .cost-result { grid-template-columns: 1fr; }
      .edge-row { grid-template-columns: minmax(110px, 1fr) 1fr 66px; }
      .confidence { grid-column: 1 / -1; justify-self: start; }
      .toolbar { grid-template-columns: 1fr; }
      .section-head { display: grid; }
      .table-pager,
      .pager-actions { justify-content: flex-start; }
      .tp-list > span { width: auto; }
      h1 { font-size: clamp(30px, 10vw, 42px); }
    }
  </style>
</head>
<body>
  <main>
    <section class="ops-header">
      <div class="header-grid">
        <div class="brand-lockup">
          <div class="eyebrow">OpenClaw AI trading ops</div>
          <h1>Painel operacional de trades</h1>
          <p class="hero-copy">Abertas primeiro, winrate com tamanho de amostra, historico filtravel e frescor dos dados sempre visivel.</p>
          <div class="quick-tags">
            <span class="tag">Discord setup-live</span>
            <span class="tag">Kraken scanner</span>
            <span class="tag">Wins e losses</span>
            <span class="tag">TPs atuais</span>
          </div>
        </div>
        <aside class="status-board">
          <div class="status-row">
            <div>
              <div class="status-label">Status dos dados</div>
              <div class="section-note" id="dataAge">calculando...</div>
            </div>
            <div id="statusBadge" class="status-pill">checando</div>
          </div>
          <div class="status-row">
            <span class="status-label">Ultimo sync</span>
            <span class="status-value" id="updatedAt">Atualizando...</span>
          </div>
          <div class="status-row">
            <span class="status-label">Fonte</span>
            <span class="status-value">setup-live / ccxt scanner / nado live</span>
          </div>
          <div class="status-row">
            <span class="status-label">Modo</span>
            <span class="status-value" id="syncMode">HTML embutido</span>
          </div>
        </aside>
      </div>
    </section>

    <nav class="view-tabs" aria-label="Alternar dashboard">
      <button type="button" class="view-tab active" data-view-tab="ops">Operacional</button>
      <button type="button" class="view-tab" data-view-tab="cost">Benchmark custo 24h</button>
    </nav>

    <div class="view-panel active" data-view-panel="ops">
    <section class="grid kpis">
      <div class="panel kpi"><div class="label">Entradas totais</div><div class="value" id="operationalTrades">0</div><div class="note">Setup-live + scanner</div></div>
      <div class="panel kpi"><div class="label">Wins</div><div class="value" id="winsValue">0</div><div class="note">TP/alvo atingido</div></div>
      <div class="panel kpi"><div class="label">Losses</div><div class="value" id="lossesValue">0</div><div class="note">Stop/loss registrado</div></div>
      <div class="panel kpi"><div class="label">Monitoradas</div><div class="value" id="openTrades">0</div><div class="note">Somente live real</div></div>
      <div class="panel kpi"><div class="label">Exposicao live</div><div class="value" id="liveExposureValue">0</div><div class="note" id="liveExposureNote">Nado/Kraken</div></div>
      <div class="panel kpi"><div class="label">Winrate entradas</div><div class="value" id="winRate">-</div><div class="note" id="winLossNote">Sem fechamento</div></div>
      <div class="panel kpi"><div class="label">Scanner</div><div class="value" id="scannerSignals">0</div><div class="note">Sinais publicos ccxt</div></div>
    </section>

    <section class="grid signal-layout">
      <div class="panel section">
        <div class="section-head">
          <div>
            <h2>Monitoramento Hyperliquid</h2>
            <div class="section-note" id="signalScannerFreshness">Scanner, allowlist ativa e resumo 5x dos sinais monitorados.</div>
          </div>
          <div class="count-pill" id="signalScannerStatus">checando</div>
        </div>
        <div id="signalMonitoringPanel"></div>
      </div>
      <div class="panel section">
        <div class="section-head">
          <div>
            <h2>Sinais avaliados</h2>
            <div class="section-note">Resultado por candles reais: alvo final, stop ou timeout. Nao confundir com ordem executada.</div>
          </div>
          <div class="count-pill" id="signalResultCount">0 sinais</div>
        </div>
        <div id="signalResultTable"></div>
      </div>
    </section>

    <section class="grid exposure-layout">
      <div class="panel section">
        <div class="section-head">
          <div>
            <h2>Exposicao real</h2>
            <div class="section-note" id="liveExposureFreshness">Posicoes abertas lidas diretamente da Nado e Kraken.</div>
          </div>
          <div class="count-pill" id="liveExposureCount">0 posicoes</div>
        </div>
        <div id="liveExposurePanel"></div>
      </div>
    </section>

    <section class="grid priority-layout">
      <div class="panel section">
        <div class="section-head">
          <div>
            <h2>Operacoes monitoradas</h2>
            <div class="section-note">Somente posicoes reais abertas em Nado/Kraken. Setups dry-run ficam fora desta lista.</div>
          </div>
          <div class="count-pill" id="activeCount">0 abertas</div>
        </div>
        <div id="activeTrades"></div>
      </div>

      <div class="panel section">
        <div class="section-head">
          <div>
            <h2>Entradas com win/loss</h2>
            <div class="section-note">Fechamentos recentes, com total de wins e losses.</div>
          </div>
          <div class="count-pill" id="resolvedCount">0 resultados</div>
        </div>
        <div id="resolvedTradesPanel"></div>
      </div>
    </section>

    <section class="grid layout">
      <div class="stack">
        <div class="panel section">
          <div class="section-head">
            <div>
              <h2>Entradas totais por setup</h2>
              <div class="section-note">Todas as entradas feitas, com winrate e take profits atuais.</div>
            </div>
          </div>
          <div id="setupPerformance"></div>
        </div>
        <div class="panel section">
          <div class="section-head">
            <div>
              <h2>Melhor winrate por setup</h2>
              <div class="section-note">Winrate ponderado pelo tamanho da amostra fechada.</div>
            </div>
          </div>
          <div id="setupBars" class="bars"></div>
        </div>
      </div>
      <div class="stack">
        <div class="panel section history-section">
          <div class="section-head">
            <div>
              <h2>Todas as entradas</h2>
              <div class="section-note">Historico filtravel em paginas de 100 para manter leitura e atualizacao leves.</div>
            </div>
            <div class="count-pill" id="recentPageBadge">0 entradas</div>
          </div>
          <div class="toolbar">
            <input id="tradeSearch" type="search" placeholder="Filtrar par, setup, motivo">
            <div class="filter-grid">
              <div class="filter-group">
                <div class="filter-label">Fonte</div>
                <div class="filter-buttons">
                  <button type="button" class="filter-btn active" data-filter-type="source" data-filter-value="all">Todas</button>
                  <button type="button" class="filter-btn" data-filter-type="source" data-filter-value="live">Setup-live</button>
                  <button type="button" class="filter-btn" data-filter-type="source" data-filter-value="scanner">Scanner</button>
                </div>
              </div>
              <div class="filter-group">
                <div class="filter-label">Status</div>
                <div class="filter-buttons">
                  <button type="button" class="filter-btn active" data-filter-type="status" data-filter-value="all">Todos</button>
                  <button type="button" class="filter-btn" data-filter-type="status" data-filter-value="open">Abertas</button>
                  <button type="button" class="filter-btn" data-filter-type="status" data-filter-value="win">Wins</button>
                  <button type="button" class="filter-btn" data-filter-type="status" data-filter-value="loss">Losses</button>
                  <button type="button" class="filter-btn" data-filter-type="status" data-filter-value="signal">Sinais</button>
                  <button type="button" class="filter-btn" data-filter-type="status" data-filter-value="unknown">Sem resultado</button>
                </div>
              </div>
              <div class="filter-group">
                <div class="filter-label">Lado</div>
                <div class="filter-buttons">
                  <button type="button" class="filter-btn active" data-filter-type="side" data-filter-value="all">Todos</button>
                  <button type="button" class="filter-btn" data-filter-type="side" data-filter-value="long">Long</button>
                  <button type="button" class="filter-btn" data-filter-type="side" data-filter-value="short">Short</button>
                </div>
              </div>
            </div>
            <div class="filter-group">
              <div class="filter-label">Setups</div>
              <div id="setupFilter" class="setup-filter"></div>
            </div>
            <div class="section-note" id="recentFilterSummary">0 entradas visiveis</div>
          </div>
          <div id="recentTrades"></div>
          <div class="table-pager" id="recentPager"></div>
        </div>
        <div class="panel section analysis-section">
          <div class="section-head">
            <div>
              <h2>Analises recentes</h2>
              <div class="section-note">Conteudo completo de scan, readiness, skips e sinais do scanner.</div>
            </div>
            <div class="count-pill" id="analysisCount">0 analises</div>
          </div>
          <div id="recentAnalyses"></div>
        </div>
      </div>
    </section>
    </div>

    <div class="view-panel" data-view-panel="cost">
      <section class="grid kpis">
        <div class="panel kpi"><div class="label">Winrate operacional</div><div class="value" id="costWinrate">-</div><div class="note" id="costWinrateNote">wins/losses fechados</div></div>
        <div class="panel kpi"><div class="label">Ciclos analisados 24h</div><div class="value" id="costCycles">1,536</div><div class="note">setup-live + scanner</div></div>
        <div class="panel kpi"><div class="label">Custo LLM/dia</div><div class="value" id="costDaily">-</div><div class="note" id="costModelNote">modelo selecionado</div></div>
        <div class="panel kpi"><div class="label">Custo LLM/mes</div><div class="value" id="costMonthly">-</div><div class="note">30 dias + fee conservadora</div></div>
      </section>

      <section class="grid report-layout">
        <div class="panel section">
          <div class="section-head">
            <div>
              <h2>PRD de custo 24h</h2>
              <div class="section-note">Relatorio para decidir se vale rodar a skill 24/7 com ou sem LLM.</div>
            </div>
            <div class="count-pill">benchmark</div>
          </div>
          <div class="report-block report-copy" id="prdReport"></div>
        </div>

        <div class="panel section">
          <div class="section-head">
            <div>
              <h2>Calculadora OpenRouter</h2>
              <div class="section-note">Ajuste ciclos, tokens e infra para simular o custo 24h.</div>
            </div>
          </div>
          <div class="cost-controls">
            <div class="filter-group">
              <div class="filter-label">Modelo</div>
              <select id="costModel"></select>
            </div>
            <div class="filter-group">
              <div class="filter-label">Ciclos/dia</div>
              <input id="costCyclesInput" type="number" min="0" step="1" value="1536">
            </div>
            <div class="filter-group">
              <div class="filter-label">Input tokens/ciclo</div>
              <input id="costInputTokens" type="number" min="0" step="100" value="6000">
            </div>
            <div class="filter-group">
              <div class="filter-label">Output tokens/ciclo</div>
              <input id="costOutputTokens" type="number" min="0" step="50" value="800">
            </div>
          </div>
          <div class="cost-controls">
            <div class="filter-group">
              <div class="filter-label">Infra mensal USD</div>
              <input id="costInfraMonthly" type="number" min="0" step="1" value="0">
            </div>
            <div class="filter-group">
              <div class="filter-label">Fee OpenRouter</div>
              <input id="costFeePct" type="number" min="0" step="0.1" value="5.5">
            </div>
            <div class="filter-group">
              <div class="filter-label">Dias/mes</div>
              <input id="costMonthDays" type="number" min="1" step="1" value="30">
            </div>
            <div class="filter-group">
              <div class="filter-label">Cambio BRL/USD</div>
              <input id="costFx" type="number" min="0" step="0.01" value="5.00">
            </div>
          </div>
          <div class="cost-controls">
            <div class="filter-group">
              <div class="filter-label">Buscar modelo</div>
              <input id="costModelSearch" type="search" placeholder="OpenAI, Claude, Gemini, free, tools">
            </div>
            <div class="filter-group">
              <div class="filter-label">Preco</div>
              <select id="costPriceFilter">
                <option value="all">Todos</option>
                <option value="paid">Pagos</option>
                <option value="free">Free</option>
                <option value="variable">Variavel/auto</option>
              </select>
            </div>
            <div class="filter-group">
              <div class="filter-label">Contexto minimo</div>
              <input id="costMinContextInput" type="number" min="0" step="1000" value="0">
            </div>
            <label class="check-row">
              <input id="costRequireTools" type="checkbox">
              <span>Somente modelos com tools</span>
            </label>
          </div>
          <div class="cost-result">
            <div class="cost-box"><span>OpenRouter/dia</span><strong id="calcDailyUsd">-</strong></div>
            <div class="cost-box"><span>Total/mes USD</span><strong id="calcMonthlyUsd">-</strong></div>
            <div class="cost-box"><span>Total/mes BRL</span><strong id="calcMonthlyBrl">-</strong></div>
          </div>
          <div id="modelBenchmark"></div>
        </div>
      </section>

      <section class="grid exposure-layout">
        <div class="panel section">
          <div class="section-head">
            <div>
              <h2>Benchmark de modelos</h2>
              <div class="section-note" id="openRouterCatalogNote">Precos por 1M tokens coletados da API publica do OpenRouter.</div>
            </div>
            <div class="count-pill" id="costModelCount">0 modelos</div>
          </div>
          <div id="llmPlanTable"></div>
          <div id="costModelTable"></div>
          <div class="source-links">
            <span>Fontes: OpenRouter Pricing, Models API e payload publico `https://openrouter.ai/api/v1/models`.</span>
            <span>Observacao: modelos gratuitos sofrem limite de requisicoes; para producao 24/7 use paid model ou BYOK com limites proprios.</span>
          </div>
        </div>
      </section>
    </div>
  </main>

  <script type="application/json" id="dashboard-data">__DASHBOARD_STATE_JSON__</script>
  <script>
    const REFRESH_MS = 15000;
    const FRESH_MS = 5 * 60 * 1000;
    const STALE_MS = 60 * 60 * 1000;
    const REMOTE_DATA_URLS = [];
    const GITHUB_LIVE_DATA = {
      contentsUrl: '',
      minFetchMs: 55 * 1000,
    };
    let dashboard = JSON.parse(document.getElementById('dashboard-data').textContent);
    let trades = [];
    let analyses = [];
    let summary = {};
    let liveExposures = {};
    let signalMonitoring = {};
    let llmCatalog = {};
    let githubLiveCache = {fetchedAt: 0, payload: null};
    const filters = {source: 'all', status: 'all', side: 'all', setup: ''};
    const RECENT_PAGE_SIZE = 100;
    const RESOLVED_LIMIT = 100;
    let recentPage = 1;
    const FALLBACK_OPENROUTER_MODELS = [
      {id: 'openrouter/free', name: 'Free Models Router', input: 0, output: 0, ctx: 200000, tools: true, note: 'teste; limite free nao cobre 24/7'},
      {id: 'openai/gpt-oss-20b', name: 'OpenAI gpt-oss-20b', input: 0.03, output: 0.14, ctx: 131072, tools: true, note: 'baixo custo, bom para triagem'},
      {id: 'z-ai/glm-4.7-flash', name: 'Z.ai GLM 4.7 Flash', input: 0.06, output: 0.40, ctx: 202752, tools: true, note: 'flash barato com tools'},
      {id: 'openai/gpt-5-nano', name: 'OpenAI GPT-5 Nano', input: 0.05, output: 0.40, ctx: 400000, tools: true, note: 'baixo custo com schema/tools'},
      {id: 'google/gemini-2.0-flash-001', name: 'Google Gemini 2.0 Flash', input: 0.10, output: 0.40, ctx: 1048576, tools: true, note: 'contexto alto'},
      {id: 'x-ai/grok-4.3', name: 'xAI Grok 4.3', input: 1.25, output: 2.50, ctx: 1000000, tools: true, note: 'mais caro; raciocinio amplo'},
      {id: 'openai/gpt-chat-latest', name: 'OpenAI GPT Chat Latest', input: 5.00, output: 30.00, ctx: 400000, tools: true, note: 'premium; usar so para auditoria'}
    ];
    const FALLBACK_OPENROUTER_PLANS = [
      {id: 'free', name: 'Free', platform_fee_pct: 0, models: '25+ free models', providers: '4 free providers', rate_limit: '50 req/dia e 20 RPM', token_pricing: 'Somente modelos free', byok: '-', support: 'Community', note: 'Nao atende 24/7 se passar de 50 chamadas/dia.'},
      {id: 'paygo', name: 'Pay-as-you-go', platform_fee_pct: 5.5, models: '400+ models', providers: '60+ providers', rate_limit: 'Sem limite OpenRouter para modelos pagos; free: 1000 req/dia com $10+ creditos', token_pricing: 'Preco por modelo, sem minimo', byok: '1M req/mes gratis; 5% depois', support: 'Email', note: 'Recomendado para producao 24/7.'},
      {id: 'enterprise', name: 'Enterprise', platform_fee_pct: null, models: '400+ models', providers: '60+ providers', rate_limit: 'Limites dedicados opcionais', token_pricing: 'Volume e desconto negociado', byok: '5M req/mes; customizado', support: 'SLA + Slack', note: 'Para SLA, volume e governanca.'}
    ];
    const RUNTIME_PROFILE = {
      setupLiveCyclesDay: 1440,
      scannerCyclesDay: 96,
      publisherCyclesDay: 1440,
      llmCyclesDay: 1536,
      defaultInputTokens: 6000,
      defaultOutputTokens: 800,
      pricingDate: '2026-05-06 UTC'
    };

    const fmtPct = (value) => value === null || value === undefined ? '-' : `${Number(value).toFixed(1)}%`;
    const fmtPct2 = (value) => value === null || value === undefined ? '-' : `${Number(value).toFixed(2)}%`;
    const fmtNum = (value) => Number(value || 0).toLocaleString('en-US');
    const fmtQty = (value) => Number(value || 0).toLocaleString('en-US', {maximumFractionDigits: 8});
    const fmtUsd = (value) => {
      const n = Number(value || 0);
      const sign = n < 0 ? '-' : '';
      return `${sign}$${Math.abs(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    };
    const fmtBrl = (value) => {
      const n = Number(value || 0);
      return `R$ ${n.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    };
    const fmtPrice = (value) => {
      const n = Number(value || 0);
      if (!n) return '-';
      return n >= 100 ? n.toFixed(2) : n >= 1 ? n.toFixed(4) : n.toPrecision(4);
    };
    const fmtDate = (value) => {
      if (!value) return '-';
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return value;
      return dt.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    };
    const text = (id, value) => {
      const node = document.getElementById(id);
      if (node) node.textContent = value;
    };
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const tradeTargetLevels = (trade) => {
      const levels = [];
      const push = (label, rawPrice, hit=false) => {
        const price = Number(rawPrice || 0);
        if (price > 0 && !levels.some(item => Math.abs(item.price - price) < 1e-12)) {
          levels.push({label, price, hit: Boolean(hit)});
        }
      };
      const targetsHit = Number(trade.targets_hit || 0);
      if (Array.isArray(trade.target_levels)) {
        trade.target_levels.forEach((level, index) => {
          if (level && typeof level === 'object') {
            push(level.label || `TP${index + 1}`, level.price || level.target_price || level.value, level.hit || index < targetsHit);
          } else {
            push(`TP${index + 1}`, level, index < targetsHit);
          }
        });
      }
      if (!levels.length && Array.isArray(trade.targets)) {
        trade.targets.forEach((target, index) => push(`TP${index + 1}`, target, index < targetsHit));
      }
      if (!levels.length) {
        push('TP', trade.target_price || trade.take_profit, targetsHit > 0);
      }
      return levels;
    };
    const tradeTargetValues = (trade) => tradeTargetLevels(trade).map(item => item.price);
    const targetProgressHtml = (trade) => {
      const levels = tradeTargetLevels(trade);
      if (!levels.length) return '<div class="target-ladder"><span class="target-chip missing">sem alvo registrado</span></div>';
      return `<div class="target-ladder">${levels.map(level => {
        const tone = level.hit ? 'hit' : 'pending';
        const marker = level.hit ? 'hit' : 'pendente';
        return `<span class="target-chip ${tone}">${escapeHtml(level.label || 'TP')} ${fmtPrice(level.price)} ${marker}</span>`;
      }).join('')}</div>`;
    };
    const targetSummaryText = (trade) => {
      const levels = tradeTargetLevels(trade);
      if (!levels.length) return 'sem alvo';
      const hit = levels.filter(level => level.hit).length;
      return `${hit}/${levels.length} alvos`;
    };
    const takeProfitText = (trade) => {
      const values = [];
      const push = (raw) => {
        const value = Number(raw || 0);
        if (value > 0 && !values.some(item => Math.abs(item - value) < 1e-12)) values.push(value);
      };
      tradeTargetValues(trade).forEach(push);
      return values.length ? values.map(fmtPrice).join(' / ') : 'sem alvo registrado';
    };
    const sourceKind = (trade) => trade.source === 'ccxt-public-scanner' ? 'scanner' : 'live';
    const sourceLabel = (trade) => sourceKind(trade) === 'scanner' ? 'scanner' : 'setup-live';
    const outcomeText = (trade) => trade.outcome || trade.status || 'unknown';
    const statusValue = (trade) => {
      const outcome = String(trade.outcome || '').toLowerCase();
      const status = String(trade.status || '').toLowerCase();
      if (outcome === 'win' || outcome === 'loss') return outcome;
      if (status === 'signal' || trade.source === 'ccxt-public-scanner') return 'signal';
      if (status === 'open' || outcome === 'open') return 'open';
      if (status === 'stale') return 'unknown';
      return outcome || status || 'unknown';
    };
    const statusLabel = (trade) => {
      const status = statusValue(trade);
      if (status === 'signal') return 'sinal';
      if (status === 'open') return 'aberta';
      if (status === 'win') return 'win';
      if (status === 'loss') return 'loss';
      return 'sem resultado';
    };
    const pillClass = (trade) => {
      const status = statusValue(trade);
      if (status === 'win') return 'win';
      if (status === 'loss') return 'loss';
      if (status === 'open') return 'open';
      if (status === 'signal') return 'signal';
      if ((trade.status || '') === 'stale') return 'stale';
      return '';
    };
    const sideValue = (trade) => {
      const side = String(trade.side || '').toLowerCase();
      return side === 'long' || side === 'short' ? side : 'unknown';
    };
    const sideClass = (trade) => sideValue(trade) === 'unknown' ? 'no-side' : sideValue(trade);
    const sideLabel = (trade) => {
      const side = sideValue(trade);
      if (side === 'unknown') return 'REVISAR LADO';
      return side.toUpperCase();
    };

    function bindData(next) {
      dashboard = next && typeof next === 'object' ? next : {};
      trades = Array.isArray(dashboard.trades) ? dashboard.trades : [];
      analyses = Array.isArray(dashboard.analyses) ? dashboard.analyses : [];
      summary = dashboard.summary || {};
      liveExposures = dashboard.live_exposures && typeof dashboard.live_exposures === 'object' ? dashboard.live_exposures : {};
      signalMonitoring = dashboard.signal_monitoring && typeof dashboard.signal_monitoring === 'object' ? dashboard.signal_monitoring : {};
      llmCatalog = dashboard.llm_catalog && typeof dashboard.llm_catalog === 'object' ? dashboard.llm_catalog : {};
    }

    function ageLabel(ms) {
      if (!Number.isFinite(ms) || ms < 0) return '-';
      const sec = Math.floor(ms / 1000);
      if (sec < 60) return `${sec}s atras`;
      const min = Math.floor(sec / 60);
      if (min < 60) return `${min}min atras`;
      const hrs = Math.floor(min / 60);
      if (hrs < 48) return `${hrs}h atras`;
      return `${Math.floor(hrs / 24)}d atras`;
    }

    function freshness() {
      const dt = new Date(dashboard.updated_at);
      const age = Date.now() - dt.getTime();
      if (Number.isNaN(dt.getTime())) return {label: 'sem data', cls: 'offline', age: '-'};
      if (age <= FRESH_MS) return {label: 'online', cls: 'fresh', age: ageLabel(age)};
      if (age <= STALE_MS) return {label: 'atrasado', cls: 'stale', age: ageLabel(age)};
      return {label: 'sem sync', cls: 'offline', age: ageLabel(age)};
    }

    function updateFreshness() {
      const item = freshness();
      const badge = document.getElementById('statusBadge');
      badge.className = `status-pill ${item.cls}`;
      badge.textContent = item.label;
      text('dataAge', `dados atualizados ${item.age}`);
      text('updatedAt', fmtDate(dashboard.updated_at));
    }

    function sampleClass(resolved) {
      if (resolved >= 20) return ['strong', 'amostra forte'];
      if (resolved >= 8) return ['ok', 'amostra ok'];
      if (resolved > 0) return ['low', 'amostra baixa'];
      return ['none', 'sem fechamento'];
    }

    function setupList() {
      const counts = new Map();
      trades.forEach(trade => {
        const setup = String(trade.setup || '').trim();
        if (!setup) return;
        counts.set(setup, (counts.get(setup) || 0) + 1);
      });
      return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }

    function setActiveButtons() {
      document.querySelectorAll('.filter-btn[data-filter-type]').forEach(button => {
        const type = button.dataset.filterType;
        const value = button.dataset.filterValue || '';
        const active = type === 'setup' ? filters.setup === value : filters[type] === value;
        button.classList.toggle('active', active);
      });
    }

    function renderSetupFilterChips() {
      const root = document.getElementById('setupFilter');
      if (!root) return;
      const chips = [
        `<button type="button" class="filter-btn" data-filter-type="setup" data-filter-value="">Todos</button>`,
        ...setupList().slice(0, 18).map(([setup, count]) =>
          `<button type="button" class="filter-btn" data-filter-type="setup" data-filter-value="${escapeHtml(setup)}">${escapeHtml(setup)} ${fmtNum(count)}</button>`
        ),
      ];
      root.innerHTML = chips.join('');
      root.querySelectorAll('.filter-btn').forEach(button => {
        button.addEventListener('click', () => {
          filters.setup = button.dataset.filterValue || '';
          recentPage = 1;
          setActiveButtons();
          renderRecentTrades();
        });
      });
      setActiveButtons();
    }

    function tradeMatchesFilters(trade, query) {
      const haystack = [
        trade.symbol,
        trade.setup,
        trade.reason,
        sideLabel(trade),
        sourceLabel(trade),
        statusLabel(trade),
        takeProfitText(trade),
      ].join(' ').toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (filters.source !== 'all' && sourceKind(trade) !== filters.source) return false;
      if (filters.status !== 'all' && statusValue(trade) !== filters.status) return false;
      if (filters.side !== 'all' && sideValue(trade) !== filters.side) return false;
      if (filters.setup && String(trade.setup || '') !== filters.setup) return false;
      return true;
    }

    function activeRows() {
      return trades
        .filter(trade => (trade.status === 'open' || trade.status === 'signal') && trade.source !== 'ccxt-public-scanner')
        .sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at)));
    }

    function renderKpis() {
      const wins = Number(summary.wins || 0);
      const losses = Number(summary.losses || 0);
      const resolved = Number(summary.resolved_trades || 0);
      text('operationalTrades', fmtNum(summary.total_trades));
      text('winsValue', fmtNum(wins));
      text('lossesValue', fmtNum(losses));
      text('openTrades', fmtNum(Number(summary.live_exposure_count || livePositionRows().length || 0)));
      text('liveExposureValue', fmtNum(summary.live_exposure_count));
      text('liveExposureNote', `${fmtUsd(summary.live_exposure_gross_notional)} bruto`);
      text('winRate', fmtPct(summary.win_rate));
      text('scannerSignals', fmtNum(summary.scanner_signals));
      text('winLossNote', resolved ? `${fmtNum(resolved)} entradas fechadas` : 'Sem fechamento');
      updateFreshness();
    }

    function shortSignalSetup(setup) {
      const value = String(setup || '');
      const aliases = {
        'institutional-strict': 'Inst',
        'divergence-and-volume-1h': 'DivVol',
        'low-stoch-storm': 'LowStoch',
      };
      return aliases[value] || value || '-';
    }

    function signalExitLabel(reason) {
      const value = String(reason || '').toLowerCase();
      if (value === 'target_final') return 'alvo final';
      if (value === 'stop') return 'stop';
      if (value === 'timeout') return 'timeout';
      return value || '-';
    }

    function renderSignalMonitoring() {
      const scanner = signalMonitoring.scanner || {};
      const allowlist = signalMonitoring.allowlist || {};
      const results = signalMonitoring.results || {};
      const history = signalMonitoring.history || {};
      const week = results.week || {};
      const d30 = results.d30 || {};
      const statusNode = document.getElementById('signalScannerStatus');
      const statusText = scanner.fresh ? 'scanner online' : (scanner.running ? 'scanner atrasado' : 'scanner offline');
      if (statusNode) {
        statusNode.textContent = statusText;
        statusNode.className = `count-pill ${scanner.fresh ? 'win' : scanner.running ? 'signal' : 'loss'}`;
      }
      text('signalScannerFreshness', scanner.updated_at ? `Ultimo scan ${fmtDate(scanner.updated_at)} · ${fmtNum(scanner.symbol_count || 0)} simbolos filtrados` : 'Sem log recente do scanner.');
      const grouped = allowlist.grouped && typeof allowlist.grouped === 'object' ? allowlist.grouped : {};
      const allowRows = Object.entries(grouped).map(([setup, assets]) => {
        const list = Array.isArray(assets) ? assets.join(', ') : String(assets || '-');
        return `<div class="signal-list-row"><strong>${escapeHtml(shortSignalSetup(setup))}</strong><span>${escapeHtml(list)}</span></div>`;
      }).join('') || '<div class="empty">Sem allowlist carregada.</div>';
      const panel = document.getElementById('signalMonitoringPanel');
      if (panel) {
        panel.innerHTML = `
          <div class="signal-cards">
            <div class="signal-card"><div class="k">Semana 5x</div><div class="v ${Number(week.pnl_sum_5x_pct || 0) >= 0 ? 'win' : 'loss'}">${fmtPct2(week.pnl_sum_5x_pct)}</div></div>
            <div class="signal-card"><div class="k">Trades semana</div><div class="v">${fmtNum(week.n || 0)}</div></div>
            <div class="signal-card"><div class="k">30d 5x</div><div class="v ${Number(d30.pnl_sum_5x_pct || 0) >= 0 ? 'win' : 'loss'}">${fmtPct2(d30.pnl_sum_5x_pct)}</div></div>
            <div class="signal-card"><div class="k">Combos ativos</div><div class="v">${fmtNum(allowlist.combo_count || 0)}</div></div>
          </div>
          <div class="signal-list">${allowRows}</div>
          <div class="section-note" style="margin-top:10px">Historico: ${fmtNum(history.backtests || 0)} backtests · ${fmtNum(history.reviews || 0)} revisoes · ${fmtNum(history.applications || 0)} aplicacoes de allowlist. Resumo: ${escapeHtml(results.generated_at_brt || '-')}.</div>`;
      }
      const signals = Array.isArray(results.signals) ? [...results.signals] : [];
      signals.sort((a, b) => String(b.called_at_brt || '').localeCompare(String(a.called_at_brt || '')));
      text('signalResultCount', `${fmtNum(signals.length)} sinais`);
      const rows = signals.slice(0, 40).map(row => {
        const pnl = Number(row.pnl_5x_pct || 0);
        return `<tr>
          <td>${escapeHtml(row.asset || '-')}</td>
          <td>${escapeHtml(shortSignalSetup(row.setup))} ${escapeHtml(String(row.timeframe || '').toUpperCase())}</td>
          <td>${escapeHtml(row.side || '-')}</td>
          <td><span class="pill ${pnl >= 0 ? 'win' : 'loss'}">${fmtPct2(pnl)}</span></td>
          <td>${escapeHtml(signalExitLabel(row.exit_reason))}</td>
          <td>${fmtNum(row.targets_hit || 0)}</td>
          <td>${escapeHtml(row.called_at_brt || '-')}</td>
        </tr>`;
      }).join('');
      const table = document.getElementById('signalResultTable');
      if (table) {
        table.innerHTML = rows ? `<div class="table-wrap signal-table"><table><thead><tr><th>Ativo</th><th>Setup/TF</th><th>Lado</th><th>PnL 5x</th><th>Saida</th><th>Alvos</th><th>Call</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">Sem sinais avaliados na janela.</div>';
      }
    }

    function inputNumber(id, fallback) {
      const node = document.getElementById(id);
      if (!node) return fallback;
      const value = Number(node.value);
      return Number.isFinite(value) ? value : fallback;
    }

    function openRouterModels() {
      const rows = Array.isArray(llmCatalog.models) ? llmCatalog.models : [];
      return rows.length ? rows : FALLBACK_OPENROUTER_MODELS;
    }

    function openRouterPlans() {
      const rows = Array.isArray(llmCatalog.plans) ? llmCatalog.plans : [];
      return rows.length ? rows : FALLBACK_OPENROUTER_PLANS;
    }

    function modelPriceValue(value) {
      const n = Number(value);
      return Number.isFinite(n) && n >= 0 ? n : 0;
    }

    function modelUnitValue(value) {
      const n = Number(value);
      return Number.isFinite(n) && n >= 0 ? n : 0;
    }

    function modelUnitPriceText(value) {
      const n = Number(value);
      if (!Number.isFinite(n) || n < 0) return 'variavel';
      if (n === 0) return 'free';
      return `$${n.toFixed(n < 0.1 ? 3 : 2)}`;
    }

    function modelDirectPriceText(value) {
      const n = Number(value);
      if (!Number.isFinite(n) || n < 0) return '';
      if (n === 0) return '';
      return `$${n.toFixed(n < 0.01 ? 5 : 3)}`;
    }

    function modelExtraPricingText(model) {
      const items = [
        ['req', modelDirectPriceText(model.request)],
        ['img', modelDirectPriceText(model.image)],
        ['search', modelDirectPriceText(model.web_search)],
        ['reason/M', modelUnitPriceText(model.internal_reasoning)],
        ['cache read/M', modelUnitPriceText(model.input_cache_read)],
        ['cache write/M', modelUnitPriceText(model.input_cache_write)],
      ].filter(([, value]) => value && value !== 'free' && value !== 'variavel');
      return items.length ? items.map(([label, value]) => `${label} ${value}`).join(' · ') : '-';
    }

    function modelPlanLabel(model) {
      if (model.variable_pricing) return 'variavel';
      return model.free ? 'free' : 'pago';
    }

    function llmCostText(model, value) {
      return model && model.variable_pricing ? 'variavel' : fmtUsd(value);
    }

    function defaultModelId(models) {
      const preferred = ['openai/gpt-oss-20b', 'openai/gpt-5-nano', 'google/gemini-2.0-flash-001'];
      for (const id of preferred) {
        if (models.some(model => model.id === id)) return id;
      }
      const toolPaid = models.find(model => model.tools && !model.free && !model.variable_pricing);
      return (toolPaid || models[0] || FALLBACK_OPENROUTER_MODELS[0]).id;
    }

    function selectedCostModel(candidateModels) {
      const allModels = openRouterModels();
      const models = Array.isArray(candidateModels) && candidateModels.length ? candidateModels : allModels;
      const select = document.getElementById('costModel');
      const id = select ? select.value : defaultModelId(models);
      return models.find(model => model.id === id)
        || models.find(model => model.id === defaultModelId(models))
        || allModels.find(model => model.id === id)
        || allModels.find(model => model.id === defaultModelId(allModels))
        || allModels[0]
        || FALLBACK_OPENROUTER_MODELS[0];
    }

    function estimateLlmCost(model, cyclesDay, inputTokens, outputTokens, days, feePct, infraMonthly) {
      const requestDaily = cyclesDay * modelUnitValue(model.request);
      const tokenDaily = cyclesDay * ((inputTokens / 1000000) * modelPriceValue(model.input) + (outputTokens / 1000000) * modelPriceValue(model.output));
      const feeMultiplier = 1 + (Math.max(0, feePct) / 100);
      const daily = (tokenDaily + requestDaily) * feeMultiplier;
      const monthly = daily * days + infraMonthly;
      return {daily, monthly, tokenDaily, requestDaily};
    }

    function normalizeModelSearchText(value) {
      return String(value ?? '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\\u0300-\\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
    }

    function compactModelSearchText(value) {
      return normalizeModelSearchText(value).replace(/\\s+/g, '');
    }

    function modelSearchHaystack(model) {
      return [
        model.id,
        model.name,
        model.provider,
        model.note,
        model.modalities,
        model.free ? 'free gratuito' : 'paid pago',
        model.variable_pricing ? 'variable variavel auto router' : '',
        model.tools ? 'tools tool calling ferramentas' : '',
        model.structured ? 'structured outputs json schema estruturado' : '',
        model.reasoning ? 'reasoning raciocinio' : '',
      ].join(' ');
    }

    function modelMatchesSearch(model, query) {
      const normalizedQuery = normalizeModelSearchText(query);
      if (!normalizedQuery) return true;
      const normalizedHaystack = normalizeModelSearchText(modelSearchHaystack(model));
      const compactHaystack = compactModelSearchText(modelSearchHaystack(model));
      const compactQuery = compactModelSearchText(query);
      if (compactQuery && compactHaystack.includes(compactQuery)) return true;
      return normalizedQuery.split(/\\s+/).every(term => normalizedHaystack.includes(term) || compactHaystack.includes(term));
    }

    function costFilterState() {
      return {
        query: document.getElementById('costModelSearch')?.value || '',
        priceFilter: document.getElementById('costPriceFilter')?.value || 'all',
        minContext: inputNumber('costMinContextInput', 0),
        requireTools: Boolean(document.getElementById('costRequireTools')?.checked),
      };
    }

    function modelMatchesCostFilters(model, state=costFilterState()) {
      if (!modelMatchesSearch(model, state.query)) return false;
      if (state.priceFilter === 'paid' && (model.free || model.variable_pricing)) return false;
      if (state.priceFilter === 'free' && !model.free) return false;
      if (state.priceFilter === 'variable' && !model.variable_pricing) return false;
      if (state.requireTools && !model.tools) return false;
      if (state.minContext > 0 && Number(model.ctx || 0) < state.minContext) return false;
      return true;
    }

    function filteredCostModels(models=openRouterModels()) {
      const state = costFilterState();
      return models.filter(model => modelMatchesCostFilters(model, state));
    }

    function modelSelectSignature(models) {
      return `${llmCatalog.updated_at || 'fallback'}:${models.map(model => model.id).join('|')}`;
    }

    function renderModelSelect(models=openRouterModels()) {
      const select = document.getElementById('costModel');
      if (!select) return;
      const signature = modelSelectSignature(models);
      if (select.dataset.signature === signature) return;
      const previous = select.value;
      if (!models.length) {
        select.innerHTML = '<option value="">Nenhum modelo encontrado</option>';
        select.disabled = true;
        select.dataset.signature = signature;
        return;
      }
      select.disabled = false;
      select.innerHTML = models.map(model =>
        `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} · ${escapeHtml(model.id)} · in ${modelUnitPriceText(model.input)}/M · out ${modelUnitPriceText(model.output)}/M</option>`
      ).join('');
      select.value = models.some(model => model.id === previous) ? previous : defaultModelId(models);
      select.dataset.signature = signature;
    }

    function bestOperationalSetup() {
      const rows = Array.isArray(summary.setup_performance) ? summary.setup_performance : [];
      return rows
        .filter(row => row.win_rate != null && Number(row.resolved || 0) > 0)
        .sort((a, b) => Number(b.resolved || 0) - Number(a.resolved || 0) || Number(b.win_rate || 0) - Number(a.win_rate || 0))[0];
    }

    function renderPrdReport(cost) {
      const resolved = Number(summary.resolved_trades || 0);
      const wins = Number(summary.wins || 0);
      const losses = Number(summary.losses || 0);
      const best = bestOperationalSetup();
      const bestLine = best ? `${escapeHtml(best.setup)} com ${fmtPct(best.win_rate)} em ${fmtNum(best.resolved)} fechamentos` : 'sem setup fechado suficiente para ranking confiavel';
      const catalogCount = Number(llmCatalog.model_count || openRouterModels().length || 0);
      const catalogSource = llmCatalog.source || 'fallback';
      document.getElementById('prdReport').innerHTML = `
        <div>
          <h3>Objetivo</h3>
          <p>Criar uma visao de custo para operar a skill 24h por dia, comparando o modo atual sem LLM com cenarios de LLM via OpenRouter para triagem, sumarizacao e avaliacao de setup.</p>
        </div>
        <div>
          <h3>Consumo operacional atual</h3>
          <ul>
            <li>setup-live analyzer: 1 ciclo/minuto, ${fmtNum(RUNTIME_PROFILE.setupLiveCyclesDay)} ciclos/dia.</li>
            <li>scanner CCXT: 1 ciclo/15 minutos, ${fmtNum(RUNTIME_PROFILE.scannerCyclesDay)} ciclos/dia.</li>
            <li>publisher do dashboard: 1 ciclo/minuto, ${fmtNum(RUNTIME_PROFILE.publisherCyclesDay)} ciclos/dia, sem necessidade de LLM.</li>
            <li>estimativa LLM usada no calculo: ${fmtNum(inputNumber('costCyclesInput', RUNTIME_PROFILE.llmCyclesDay))} chamadas/dia.</li>
            <li>catalogo OpenRouter carregado: ${fmtNum(catalogCount)} modelos, fonte ${escapeHtml(catalogSource)}, atualizado ${fmtDate(llmCatalog.updated_at)}.</li>
          </ul>
        </div>
        <div>
          <h3>Resultado operacional</h3>
          <p>Winrate fechado atual: <strong>${fmtPct(summary.win_rate)}</strong>, com ${fmtNum(wins)} wins, ${fmtNum(losses)} losses e ${fmtNum(resolved)} entradas resolvidas. Melhor referencia com amostra: ${bestLine}.</p>
        </div>
        <div>
          <h3>Recomendacao</h3>
          <p>A skill consegue rodar 24/7 sem LLM, porque o core operacional e Python/CCXT/Nado/Kraken. LLM barata deve entrar como camada auxiliar: explicar sinais, classificar setups, gerar relatorios e bloquear operacoes duvidosas. Para execucao real, mantenha guardrails deterministas e use LLM apenas como voto consultivo.</p>
        </div>
        <div>
          <h3>Cenario selecionado</h3>
          <p>Modelo ${escapeHtml(cost.model.name)}: ${llmCostText(cost.model, cost.daily)} por dia e ${llmCostText(cost.model, cost.monthly)} por mes, considerando ${fmtNum(cost.cyclesDay)} chamadas/dia, ${fmtNum(cost.inputTokens)} input tokens/ciclo, ${fmtNum(cost.outputTokens)} output tokens/ciclo, infra mensal de ${fmtUsd(cost.infraMonthly)} e fee conservadora de ${cost.feePct.toFixed(1)}%.</p>
        </div>
        <div>
          <h3>Riscos e aceite</h3>
          <ul>
            <li>Precos de modelos mudam; o dashboard consulta a API publica do OpenRouter e usa cache local de 1 hora.</li>
            <li>Free plan nao cobre o perfil atual de ${fmtNum(inputNumber('costCyclesInput', RUNTIME_PROFILE.llmCyclesDay))} chamadas/dia.</li>
            <li>Aceite: dashboard mostra planos, custo/dia, custo/mes, winrate operacional, modelos comparados, tools e contexto.</li>
          </ul>
        </div>`;
    }

    function planDailyCost(plan, model, baseCost, cyclesDay, days) {
      if (plan.id === 'free') {
        return {
          daily: 0,
          monthly: 0,
          viable: Boolean(model.free) && cyclesDay <= 50,
          note: model.free ? 'limite 50 req/dia' : 'nao inclui modelos pagos',
        };
      }
      if (plan.id === 'enterprise') {
        return {
          daily: null,
          monthly: null,
          viable: true,
          note: 'preco customizado, usar custo do modelo como referencia',
        };
      }
      const fee = Number(plan.platform_fee_pct || 0);
      const estimate = estimateLlmCost(model, cyclesDay, baseCost.inputTokens, baseCost.outputTokens, days, fee, 0);
      const freeModelLimit = model.free && cyclesDay > 1000;
      return {
        daily: estimate.daily,
        monthly: estimate.monthly,
        viable: !freeModelLimit && !model.variable_pricing,
        note: freeModelLimit ? 'free model excede 1000 req/dia' : `fee ${fee.toFixed(1)}%`,
      };
    }

    function renderPlanTable(cost) {
      const plans = openRouterPlans();
      const rows = plans.map(plan => {
        const estimate = planDailyCost(plan, cost.model, cost, cost.cyclesDay, cost.days);
        const fee = plan.platform_fee_pct == null ? 'custom' : `${Number(plan.platform_fee_pct).toFixed(1)}%`;
        const daily = estimate.daily == null ? 'custom' : fmtUsd(estimate.daily);
        const monthly = estimate.monthly == null ? 'custom' : fmtUsd(estimate.monthly);
        return `<tr>
          <td>${escapeHtml(plan.name)}<div class="section-note">${escapeHtml(plan.note || '')}</div></td>
          <td>${escapeHtml(fee)}</td>
          <td>${escapeHtml(plan.models || '-')}<div class="section-note">${escapeHtml(plan.providers || '')}</div></td>
          <td>${escapeHtml(plan.rate_limit || '-')}</td>
          <td>${escapeHtml(plan.byok || '-')}</td>
          <td><span class="pill ${estimate.viable ? 'hedged' : 'stale'}">${estimate.viable ? 'viavel' : 'nao atende'}</span><div class="section-note">${escapeHtml(estimate.note)}</div></td>
          <td>${daily}</td>
          <td>${monthly}</td>
        </tr>`;
      }).join('');
      document.getElementById('llmPlanTable').innerHTML = `<div class="table-wrap"><table><thead><tr>
        <th>Plano</th><th>Fee</th><th>Modelos</th><th>Limite</th><th>BYOK</th><th>24h atual</th><th>Dia</th><th>Mes</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    function renderCostBenchmark() {
      const models = openRouterModels();
      const filteredModels = filteredCostModels(models);
      renderModelSelect(filteredModels);
      const model = selectedCostModel(filteredModels);
      const cyclesDay = inputNumber('costCyclesInput', RUNTIME_PROFILE.llmCyclesDay);
      const inputTokens = inputNumber('costInputTokens', RUNTIME_PROFILE.defaultInputTokens);
      const outputTokens = inputNumber('costOutputTokens', RUNTIME_PROFILE.defaultOutputTokens);
      const infraMonthly = inputNumber('costInfraMonthly', 0);
      const feePct = inputNumber('costFeePct', 5.5);
      const days = inputNumber('costMonthDays', 30);
      const fx = inputNumber('costFx', 5);
      const cost = {model, cyclesDay, inputTokens, outputTokens, infraMonthly, feePct, days, ...estimateLlmCost(model, cyclesDay, inputTokens, outputTokens, days, feePct, infraMonthly)};
      const visibleModels = filteredModels.slice(0, 500);

      text('costWinrate', fmtPct(summary.win_rate));
      text('costWinrateNote', `${fmtNum(summary.wins)} wins / ${fmtNum(summary.losses)} losses / ${fmtNum(summary.resolved_trades)} fechadas`);
      text('costCycles', fmtNum(cyclesDay));
      text('costDaily', llmCostText(model, cost.daily));
      text('costMonthly', llmCostText(model, cost.monthly));
      text('costModelNote', `${model.id}`);
      text('calcDailyUsd', llmCostText(model, cost.daily));
      text('calcMonthlyUsd', llmCostText(model, cost.monthly));
      text('calcMonthlyBrl', model.variable_pricing ? 'variavel' : fmtBrl(cost.monthly * fx));
      text('costModelCount', `${fmtNum(filteredModels.length)} de ${fmtNum(models.length)} modelos`);
      text('openRouterCatalogNote', `Modelos da API OpenRouter e planos da Pricing Page · ${fmtNum(Number(llmCatalog.model_count || models.length))} modelos · modelos ${fmtDate(llmCatalog.updated_at)} · planos ${fmtDate(llmCatalog.plans_updated_at || llmCatalog.updated_at)} · ${escapeHtml(llmCatalog.plans_source || 'fallback')}${llmCatalog.error || llmCatalog.plans_error ? ` · ${escapeHtml(llmCatalog.error || llmCatalog.plans_error)}` : ''}`);

      document.getElementById('modelBenchmark').innerHTML = `<div class="source-links">
        <span>Formula: ciclos/dia * ((input tokens / 1M * preco input) + (output tokens / 1M * preco output) + preco fixo/request) * (1 + fee). Web search, imagem, cache e reasoning interno aparecem em Extras quando o provedor publica esses valores.</span>
        <span>Perfil base atual: setup-live 60s + scanner 900s = ${fmtNum(RUNTIME_PROFILE.llmCyclesDay)} chamadas/dia. Publisher, Discord e monitor live nao precisam de LLM.</span>
        <span>Modelo selecionado: ${escapeHtml(model.name)} (${escapeHtml(model.id)}) · ${escapeHtml(modelPlanLabel(model))} · contexto ${fmtNum(model.ctx)} · tools ${model.tools ? 'sim' : 'nao'} · extras ${escapeHtml(modelExtraPricingText(model))}.</span>
      </div>`;

      renderPlanTable(cost);
      const modelRows = visibleModels.length ? visibleModels.map(row => {
        const rowCost = estimateLlmCost(row, cyclesDay, inputTokens, outputTokens, days, feePct, 0);
        const variable = row.variable_pricing;
        return `<tr>
          <td>${escapeHtml(row.name)}<div class="section-note">${escapeHtml(row.id)}</div></td>
          <td><span class="pill ${row.free ? 'hedged' : variable ? 'stale' : 'open'}">${escapeHtml(modelPlanLabel(row))}</span></td>
          <td>${modelUnitPriceText(row.input)}</td>
          <td>${modelUnitPriceText(row.output)}</td>
          <td>${escapeHtml(modelExtraPricingText(row))}</td>
          <td>${fmtNum(row.ctx)}</td>
          <td><span class="pill ${row.tools ? 'hedged' : 'stale'}">${row.tools ? 'sim' : 'nao'}</span></td>
          <td><span class="pill ${row.structured ? 'hedged' : 'stale'}">${row.structured ? 'sim' : 'nao'}</span></td>
          <td>${variable ? 'variavel' : fmtUsd(rowCost.daily)}</td>
          <td>${variable ? 'variavel' : fmtUsd(rowCost.monthly)}</td>
          <td>${escapeHtml(row.provider || '-')} · ${escapeHtml(row.modalities || '-')} ${row.expiration_date ? `· exp ${escapeHtml(row.expiration_date)}` : ''}</td>
        </tr>`;
      }).join('') : '<tr><td colspan="11">Nenhum modelo encontrado para a busca e filtros atuais.</td></tr>';
      document.getElementById('costModelTable').innerHTML = `<div class="table-wrap"><table><thead><tr>
        <th>Modelo</th><th>Plano</th><th>Input $/1M</th><th>Output $/1M</th><th>Extras</th><th>Contexto</th><th>Tools</th><th>Estruturado</th><th>Dia</th><th>Mes</th><th>Perfil</th>
      </tr></thead><tbody>${modelRows}</tbody></table></div>${filteredModels.length > visibleModels.length ? `<div class="section-note">Mostrando ${fmtNum(visibleModels.length)} primeiros modelos filtrados de ${fmtNum(filteredModels.length)}.</div>` : ''}`;
      renderPrdReport(cost);
    }

    function exposureStatusClass(status) {
      if (status === 'hedged') return 'hedged';
      if (status === 'unmatched') return 'unmatched';
      return 'stale';
    }

    function exposureStatusLabel(status) {
      if (status === 'hedged') return 'hedge ok';
      if (status === 'unmatched') return 'sem hedge';
      if (status === 'stale') return 'stale';
      return status || 'live';
    }

    function exposureTargetClass(status) {
      if (status === 'hedged') return 'hit';
      if (status === 'unmatched') return 'pending';
      return 'missing';
    }

    function livePositionRows() {
      const positions = Array.isArray(liveExposures.positions) ? liveExposures.positions : [];
      const summaries = Array.isArray(liveExposures.summary) ? liveExposures.summary : [];
      const summaryByBase = new Map();
      summaries.forEach(row => {
        const base = String(row.base || '').toUpperCase();
        if (base) summaryByBase.set(base, row);
      });
      return positions
        .map(position => {
          const base = String(position.base || String(position.symbol || '').split('/')[0] || '').toUpperCase();
          return Object.assign({}, position, {exposure: summaryByBase.get(base) || {}, base});
        })
        .sort((a, b) => Number(b.notional_usd || 0) - Number(a.notional_usd || 0));
    }

    function renderLiveExposure() {
      const positions = Array.isArray(liveExposures.positions) ? liveExposures.positions : [];
      const rows = Array.isArray(liveExposures.summary) ? liveExposures.summary : [];
      const error = String(liveExposures.error || '');
      text('liveExposureCount', `${fmtNum(positions.length)} posicoes`);
      text('liveExposureFreshness', liveExposures.updated_at ? `Posicoes live atualizadas ${fmtDate(liveExposures.updated_at)}` : 'Posicoes abertas lidas diretamente da Nado e Kraken.');
      if (error && !positions.length) {
        document.getElementById('liveExposurePanel').innerHTML = `<div class="empty">Exposicao live indisponivel: ${escapeHtml(error)}</div>`;
        return;
      }
      if (!positions.length) {
        document.getElementById('liveExposurePanel').innerHTML = '<div class="empty">Nenhuma exposicao live detectada em Nado/Kraken.</div>';
        return;
      }
      const positionTable = `<div class="table-wrap"><table><thead><tr>
        <th>Corretora</th><th>Par</th><th>Lado</th><th>Qty</th><th>Notional</th><th>Mark</th><th>Entrada</th><th>Liq</th><th>Margem</th>
      </tr></thead><tbody>${positions.map(position => `<tr>
        <td><span class="pill ${position.venue === 'nado' ? 'open' : 'signal'}">${escapeHtml(String(position.venue || '-').toUpperCase())}</span></td>
        <td>${escapeHtml(position.symbol || '-')}</td>
        <td><span class="pill ${String(position.side || '').toLowerCase() === 'short' ? 'short' : 'long'}">${escapeHtml(String(position.side || '-').toUpperCase())}</span></td>
        <td>${Number(position.size || 0).toLocaleString('en-US', {maximumFractionDigits: 8})}</td>
        <td>${fmtUsd(position.notional_usd)}</td>
        <td>${fmtPrice(position.mark_price)}</td>
        <td>${fmtPrice(position.entry_price)}</td>
        <td>${fmtPrice(position.liquidation_price)}</td>
        <td>${escapeHtml(position.margin_mode || '-')}</td>
      </tr>`).join('')}</tbody></table></div>`;
      const summaryTable = rows.length ? `<div class="table-wrap"><table><thead><tr>
        <th>Ativo</th><th>Nado</th><th>Kraken</th><th>Net</th><th>Bruto</th><th>Drift</th><th>Status</th>
      </tr></thead><tbody>${rows.map(row => `<tr>
        <td>${escapeHtml(row.base || '-')}</td>
        <td>${fmtUsd(row.nado_notional)}</td>
        <td>${fmtUsd(row.kraken_notional)}</td>
        <td>${fmtUsd(row.net_notional)}</td>
        <td>${fmtUsd(row.gross_notional)}</td>
        <td>${Number(row.drift_bps || 0).toFixed(2)} bps</td>
        <td><span class="pill ${exposureStatusClass(row.status)}">${escapeHtml(row.status || '-')}</span></td>
      </tr>`).join('')}</tbody></table></div>` : '';
      document.getElementById('liveExposurePanel').innerHTML = `${positionTable}${summaryTable}`;
    }

    function renderSetupBars() {
      const rows = Array.isArray(summary.best_setups) ? summary.best_setups : [];
      const root = document.getElementById('setupBars');
      if (!rows.length) {
        root.innerHTML = '<div class="empty">Sem dados suficientes para ranking.</div>';
        return;
      }
      root.innerHTML = rows.map(row => {
        const rate = row.win_rate == null ? 0 : Number(row.win_rate);
        const label = row.win_rate == null ? 'sem fechamento' : fmtPct(rate);
        const [tone, sample] = sampleClass(Number(row.resolved || 0));
        return `<div class="edge-row">
          <div class="bar-label" title="${escapeHtml(row.setup)}">${escapeHtml(row.setup)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(rate, 3)}%"></div></div>
          <div class="bar-value">${label}</div>
          <div class="confidence ${tone}">${sample}</div>
          <div class="edge-meta">entradas ${fmtNum(row.entries || row.signals)} / wins ${fmtNum(row.wins)} / losses ${fmtNum(row.losses)} / fechadas ${fmtNum(row.resolved)} / abertas ${fmtNum(row.open)}</div>
        </div>`;
      }).join('');
    }

    function setupTpLabel(row) {
      const current = Array.isArray(row.current_take_profits) ? row.current_take_profits : [];
      if (current.length) {
        return `<div class="tp-list">${current.map(item => {
          const ladder = targetProgressHtml(item);
          return `<span>${escapeHtml(item.symbol || '-')} ${escapeHtml(String(item.side || '').toUpperCase())} ${escapeHtml(targetSummaryText(item))}</span>${ladder}`;
        }).join('')}</div>`;
      }
      return row.latest_take_profit ? fmtPrice(row.latest_take_profit) : '-';
    }

    function renderSetupPerformance() {
      const rows = Array.isArray(summary.setup_performance) ? summary.setup_performance : [];
      if (!rows.length) {
        document.getElementById('setupPerformance').innerHTML = '<div class="empty">Sem entradas por setup.</div>';
        return;
      }
      document.getElementById('setupPerformance').innerHTML = `<div class="table-wrap"><table><thead><tr>
        <th>Setup</th><th>Entradas</th><th>Wins</th><th>Losses</th><th>Abertas</th><th>Sem resultado</th><th>Winrate</th><th>TP atual</th>
      </tr></thead><tbody>${rows.map(row => `<tr>
        <td>${escapeHtml(row.setup || '-')}</td>
        <td>${fmtNum(row.entries || row.signals)}</td>
        <td><span class="pill win">${fmtNum(row.wins)}</span></td>
        <td><span class="pill loss">${fmtNum(row.losses)}</span></td>
        <td><span class="pill open">${fmtNum(row.open)}</span></td>
        <td>${fmtNum(row.unknown)}</td>
        <td>${fmtPct(row.win_rate)}</td>
        <td>${setupTpLabel(row)}</td>
      </tr>`).join('')}</tbody></table></div>`;
    }

    function renderSetupTradeCard(trade) {
      return `<article class="trade-card ${sideClass(trade)}">
        <div class="trade-title">
          <div>
            <div class="symbol">${escapeHtml(trade.symbol || '-')}</div>
            <div class="setup-name">${escapeHtml(trade.setup || '-')}</div>
          </div>
          <span class="pill ${sideClass(trade)}">${escapeHtml(sideLabel(trade))}</span>
        </div>
        <div class="trade-metrics">
          <div class="metric"><span>Entrada</span><strong>${fmtPrice(trade.entry_price)}</strong></div>
          <div class="metric"><span>Stop</span><strong>${fmtPrice(trade.stop_price)}</strong></div>
          <div class="metric"><span>Alvos</span><strong>${targetSummaryText(trade)}</strong></div>
        </div>
        ${targetProgressHtml(trade)}
        <div class="reason">${escapeHtml(trade.reason || 'Sem motivo registrado.')}</div>
        <div class="section-note">${escapeHtml(sourceLabel(trade))} · Atualizado ${fmtDate(trade.updated_at || trade.created_at)} · ${escapeHtml(statusLabel(trade))}</div>
      </article>`;
    }

    function renderLivePositionCard(position) {
      const exposure = position.exposure || {};
      const status = String(exposure.status || 'live').toLowerCase();
      const venue = String(position.venue || '-').toUpperCase();
      const drift = Number(exposure.drift_bps || 0);
      const krakenNotional = Number(exposure.kraken_notional || 0);
      const netNotional = Number(exposure.net_notional || position.signed_notional_usd || position.notional_usd || 0);
      const nadoNotional = Number(exposure.nado_notional || 0);
      const unrealized = Number(position.unrealized_pnl || 0);
      const leverage = Number(position.leverage || 0);
      const product = position.product_id ? ` · Produto ${escapeHtml(position.product_id)}` : '';
      const reason = [
        `Leitura real ${escapeHtml(venue)}.`,
        `Net ${fmtUsd(netNotional)}.`,
        `Nado ${fmtUsd(nadoNotional)} / Kraken ${fmtUsd(krakenNotional)}.`,
        `Drift ${drift.toFixed(2)} bps.`
      ].join(' ');
      return `<article class="trade-card live-position ${sideClass(position)} ${exposureStatusClass(status)}">
        <div class="trade-title">
          <div>
            <div class="symbol">${escapeHtml(position.symbol || '-')}</div>
            <div class="setup-name">${escapeHtml(venue)} LIVE · ${escapeHtml(exposureStatusLabel(status))}</div>
          </div>
          <span class="pill ${sideClass(position)}">${escapeHtml(sideLabel(position))}</span>
        </div>
        <div class="trade-metrics">
          <div class="metric"><span>Notional</span><strong>${fmtUsd(position.notional_usd)}</strong></div>
          <div class="metric"><span>Mark</span><strong>${fmtPrice(position.mark_price)}</strong></div>
          <div class="metric"><span>Qty</span><strong>${fmtQty(position.size)}</strong></div>
          <div class="metric"><span>Net</span><strong>${fmtUsd(netNotional)}</strong></div>
          <div class="metric"><span>PnL</span><strong>${fmtUsd(unrealized)}</strong></div>
          <div class="metric"><span>Margem</span><strong>${escapeHtml(position.margin_mode || '-')}</strong></div>
        </div>
        <div class="target-ladder">
          <span class="target-chip ${exposureTargetClass(status)}">status ${escapeHtml(exposureStatusLabel(status))}</span>
          <span class="target-chip pending">drift ${drift.toFixed(2)} bps</span>
          <span class="target-chip missing">Nado ${fmtUsd(nadoNotional)}</span>
          <span class="target-chip missing">Kraken ${fmtUsd(krakenNotional)}</span>
          <span class="target-chip pending">liq ${fmtPrice(position.liquidation_price)}</span>
          <span class="target-chip pending">lev ${leverage ? `${leverage}x` : '-'}</span>
        </div>
        <div class="reason">${escapeHtml(reason)}</div>
        <div class="section-note">${escapeHtml(venue)} real${product} · Atualizado ${fmtDate(liveExposures.updated_at)}</div>
      </article>`;
    }

    function renderActiveTrades() {
      const liveRows = livePositionRows();
      const cards = liveRows.map(renderLivePositionCard);
      text('activeCount', `${fmtNum(liveRows.length)} posicoes reais`);
      if (!cards.length) {
        document.getElementById('activeTrades').innerHTML = '<div class="empty">Nenhuma posicao real aberta em Nado/Kraken agora.</div>';
        return;
      }
      document.getElementById('activeTrades').innerHTML = `<div class="active-grid">${cards.join('')}</div>`;
    }

    function tradeTable(rows, compact=false) {
      if (!rows.length) return '<div class="empty">Nenhum registro encontrado.</div>';
      return `<div class="table-wrap"><table><thead><tr>
        <th>Data</th><th>Fonte</th><th>Setup</th><th>Par</th><th>Lado</th><th>Entrada</th><th>Stop</th><th>Alvos</th><th>Status</th>${compact ? '' : '<th>Motivo</th>'}
      </tr></thead><tbody>${rows.map(trade => `<tr>
        <td>${fmtDate(trade.created_at)}</td>
        <td><span class="pill ${sourceKind(trade) === 'scanner' ? 'signal' : 'open'}">${escapeHtml(sourceLabel(trade))}</span></td>
        <td>${escapeHtml(trade.setup || '-')}</td>
        <td>${escapeHtml(trade.symbol || '-')}</td>
        <td><span class="pill ${sideClass(trade)}">${escapeHtml(sideLabel(trade))}</span></td>
        <td>${fmtPrice(trade.entry_price)}</td>
        <td>${fmtPrice(trade.stop_price)}</td>
        <td>${targetProgressHtml(trade)}</td>
        <td><span class="pill ${pillClass(trade)}">${escapeHtml(statusLabel(trade))}</span></td>
        ${compact ? '' : `<td>${escapeHtml(trade.reason || '')}</td>`}
      </tr>`).join('')}</tbody></table></div>`;
    }

    function renderResolvedTrades() {
      const rows = trades
        .filter(trade => ['win', 'loss'].includes(statusValue(trade)))
        .sort((a, b) => String(b.updated_at || b.closed_at || b.created_at).localeCompare(String(a.updated_at || a.closed_at || a.created_at)));
      const visibleRows = rows.slice(0, RESOLVED_LIMIT);
      const wins = rows.filter(trade => statusValue(trade) === 'win').length;
      const losses = rows.filter(trade => statusValue(trade) === 'loss').length;
      text('resolvedCount', `${fmtNum(rows.length)} resultados · ${fmtNum(wins)} wins / ${fmtNum(losses)} losses`);
      const note = rows.length > visibleRows.length
        ? `<div class="section-note">Mostrando os ${fmtNum(visibleRows.length)} fechamentos mais recentes de ${fmtNum(rows.length)}.</div>`
        : '';
      document.getElementById('resolvedTradesPanel').innerHTML = tradeTable(visibleRows, true) + note;
    }

    function renderRecentPager(totalPages, totalRows, visibleRows, startIndex) {
      const root = document.getElementById('recentPager');
      if (!root) return;
      if (totalRows <= RECENT_PAGE_SIZE) {
        root.innerHTML = totalRows ? `<span>${fmtNum(totalRows)} entradas filtradas.</span>` : '';
        return;
      }
      const endIndex = startIndex + visibleRows.length;
      root.innerHTML = `<span>Mostrando ${fmtNum(startIndex + 1)}-${fmtNum(endIndex)} de ${fmtNum(totalRows)} entradas.</span>
        <div class="pager-actions">
          <button type="button" class="pager-btn" data-page="${recentPage - 1}" ${recentPage <= 1 ? 'disabled' : ''}>Anterior</button>
          <span class="pager-label">Pagina ${fmtNum(recentPage)} / ${fmtNum(totalPages)}</span>
          <button type="button" class="pager-btn" data-page="${recentPage + 1}" ${recentPage >= totalPages ? 'disabled' : ''}>Proxima</button>
        </div>`;
      root.querySelectorAll('.pager-btn').forEach(button => {
        button.addEventListener('click', () => {
          const nextPage = Number(button.dataset.page || recentPage);
          if (!Number.isFinite(nextPage)) return;
          recentPage = Math.min(Math.max(1, nextPage), totalPages);
          renderRecentTrades();
        });
      });
    }

    function renderRecentTrades() {
      const query = document.getElementById('tradeSearch').value.trim().toLowerCase();
      const rows = trades
        .filter(trade => tradeMatchesFilters(trade, query))
        .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      const totalPages = Math.max(1, Math.ceil(rows.length / RECENT_PAGE_SIZE));
      recentPage = Math.min(Math.max(1, recentPage), totalPages);
      const startIndex = (recentPage - 1) * RECENT_PAGE_SIZE;
      const visibleRows = rows.slice(startIndex, startIndex + RECENT_PAGE_SIZE);
      const endIndex = startIndex + visibleRows.length;
      text('recentPageBadge', `${fmtNum(visibleRows.length)} na pagina`);
      text(
        'recentFilterSummary',
        rows.length
          ? `Mostrando ${fmtNum(startIndex + 1)}-${fmtNum(endIndex)} de ${fmtNum(rows.length)} entradas filtradas`
          : '0 entradas filtradas'
      );
      document.getElementById('recentTrades').innerHTML = tradeTable(visibleRows, true);
      renderRecentPager(totalPages, rows.length, visibleRows, startIndex);
    }

    function analysisPillClass(kind) {
      if (kind === 'skip') return 'skip';
      if (kind === 'scanner-signal') return 'signal';
      if (kind === 'readiness') return 'open';
      return '';
    }

    function analysisExtraValue(value) {
      if (value === null || value === undefined || value === '') return '';
      if (Array.isArray(value)) {
        return value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join(', ');
      }
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    }

    function analysisExtraHtml(item) {
      const extra = item.extra && typeof item.extra === 'object' ? item.extra : {};
      const rows = Object.entries(extra)
        .map(([key, value]) => [key, analysisExtraValue(value)])
        .filter(([, value]) => value);
      if (!rows.length) return '';
      return `<div class="analysis-extra">${rows.map(([key, value]) => `<span>${escapeHtml(key)}: ${escapeHtml(value)}</span>`).join('')}</div>`;
    }

    function renderAnalyses() {
      const rows = analyses
        .slice()
        .sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
      const visibleRows = rows.slice(0, 100);
      text('analysisCount', `${fmtNum(visibleRows.length)} de ${fmtNum(rows.length)}`);
      if (!rows.length) {
        text('analysisCount', '0 analises');
        document.getElementById('recentAnalyses').innerHTML = '<div class="empty">Sem analises registradas.</div>';
        return;
      }
      const note = rows.length > visibleRows.length
        ? `<div class="section-note">Mostrando as ${fmtNum(visibleRows.length)} analises mais recentes de ${fmtNum(rows.length)}.</div>`
        : '';
      document.getElementById('recentAnalyses').innerHTML = `<div class="analysis-list">${visibleRows.map(item => {
        const kind = item.kind || 'analise';
        const title = [item.setup || kind, item.symbol || ''].filter(Boolean).join(' / ');
        const side = item.side ? `<span>${escapeHtml(String(item.side).toUpperCase())}</span>` : '';
        return `<article class="analysis-card">
          <div class="analysis-card-head">
            <div>
              <div class="analysis-title">${escapeHtml(title || 'analise')}</div>
              <div class="analysis-meta">
                <span>${fmtDate(item.ts)}</span>
                ${item.setup ? `<span>${escapeHtml(item.setup)}</span>` : ''}
                ${item.symbol ? `<span>${escapeHtml(item.symbol)}</span>` : ''}
                ${side}
              </div>
            </div>
            <span class="pill ${analysisPillClass(kind)}">${escapeHtml(kind)}</span>
          </div>
          <div class="analysis-reason">${escapeHtml(item.reason || 'Sem resumo registrado.')}</div>
          ${analysisExtraHtml(item)}
        </article>`;
      }).join('')}</div>${note}`;
    }

    function renderAll() {
      bindData(dashboard);
      renderKpis();
      renderSignalMonitoring();
      renderLiveExposure();
      renderSetupPerformance();
      renderSetupBars();
      renderActiveTrades();
      renderResolvedTrades();
      renderSetupFilterChips();
      renderRecentTrades();
      renderAnalyses();
      renderCostBenchmark();
    }

    async function fetchDashboardJson(url) {
      const separator = url.includes('?') ? '&' : '?';
      const response = await fetch(`${url}${separator}ts=${Date.now()}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const next = await response.json();
      if (!next || !Array.isArray(next.trades)) throw new Error('invalid payload');
      return next;
    }

    function parseBase64Json(content) {
      const binary = atob(String(content || '').replace(/\\s/g, ''));
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return JSON.parse(new TextDecoder('utf-8').decode(bytes));
    }

    async function fetchGithubLiveData() {
      if (!GITHUB_LIVE_DATA.contentsUrl) throw new Error('github live data disabled');
      const now = Date.now();
      if (githubLiveCache.payload && now - githubLiveCache.fetchedAt < GITHUB_LIVE_DATA.minFetchMs) {
        return githubLiveCache.payload;
      }
      const separator = GITHUB_LIVE_DATA.contentsUrl.includes('?') ? '&' : '?';
      const metaResponse = await fetch(`${GITHUB_LIVE_DATA.contentsUrl}${separator}ts=${Date.now()}`, {
        cache: 'no-store',
        headers: {Accept: 'application/vnd.github+json'},
      });
      if (!metaResponse.ok) throw new Error(`HTTP ${metaResponse.status}`);
      const meta = await metaResponse.json();
      if (!meta.git_url) throw new Error('missing git_url');
      const response = await fetch(`${meta.git_url}?ts=${Date.now()}`, {
        cache: 'no-store',
        headers: {Accept: 'application/vnd.github+json'},
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.json();
      if (blob.encoding !== 'base64' || !blob.content) throw new Error('invalid blob');
      const payload = parseBase64Json(blob.content);
      if (!payload || !Array.isArray(payload.trades)) throw new Error('invalid github payload');
      githubLiveCache = {fetchedAt: now, payload};
      return payload;
    }

    function newerDashboardPayload(current, candidate) {
      const currentTs = Date.parse(current?.updated_at || '');
      const candidateTs = Date.parse(candidate?.updated_at || '');
      if (!Number.isFinite(candidateTs)) return current;
      if (!Number.isFinite(currentTs)) return candidate;
      return candidateTs >= currentTs ? candidate : current;
    }

    async function refreshData() {
      if (!/^https?:$/.test(window.location.protocol)) {
        text('syncMode', 'HTML local auto-reload');
        const updatedAt = Date.parse(dashboard.updated_at || '');
        if (Number.isFinite(updatedAt) && Date.now() - updatedAt > 60000) {
          window.location.reload();
        }
        return;
      }
      try {
        const local = await fetchDashboardJson('dashboard-data.json');
        let next = newerDashboardPayload(dashboard, local);
        let remoteUsed = false;
        try {
          const githubLive = await fetchGithubLiveData();
          const selected = newerDashboardPayload(next, githubLive);
          remoteUsed = selected === githubLive;
          next = selected;
        } catch (_error) {}
        for (const url of REMOTE_DATA_URLS) {
          try {
            const remote = await fetchDashboardJson(url);
            const selected = newerDashboardPayload(next, remote);
            remoteUsed = selected === remote;
            next = selected;
          } catch (_error) {}
        }
        dashboard = next;
        text('syncMode', remoteUsed ? 'JSON remoto live' : 'JSON auto-refresh 15s');
        renderAll();
      } catch (error) {
        try {
          dashboard = newerDashboardPayload(dashboard, await fetchGithubLiveData());
          text('syncMode', 'JSON remoto live');
          renderAll();
          return;
        } catch (_error) {}
        for (const url of REMOTE_DATA_URLS) {
          try {
            dashboard = newerDashboardPayload(dashboard, await fetchDashboardJson(url));
            text('syncMode', 'JSON remoto live');
            renderAll();
            return;
          } catch (_error) {}
        }
        text('syncMode', 'HTML embutido');
        updateFreshness();
      }
    }

    bindData(dashboard);
    renderAll();
    document.getElementById('tradeSearch').addEventListener('input', () => {
      recentPage = 1;
      renderRecentTrades();
    });
    document.querySelectorAll('.view-tab').forEach(button => {
      button.addEventListener('click', () => {
        const key = button.dataset.viewTab || 'ops';
        document.querySelectorAll('.view-tab').forEach(item => item.classList.toggle('active', item === button));
        document.querySelectorAll('.view-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.viewPanel === key));
        if (key === 'cost') renderCostBenchmark();
      });
    });
    ['costModel', 'costCyclesInput', 'costInputTokens', 'costOutputTokens', 'costInfraMonthly', 'costFeePct', 'costMonthDays', 'costFx', 'costModelSearch', 'costPriceFilter', 'costMinContextInput', 'costRequireTools'].forEach(id => {
      const node = document.getElementById(id);
      if (node) node.addEventListener('input', renderCostBenchmark);
      if (node) node.addEventListener('change', renderCostBenchmark);
    });
    document.querySelectorAll('.filter-btn[data-filter-type]:not([data-filter-type="setup"])').forEach(button => {
      button.addEventListener('click', () => {
        const type = button.dataset.filterType;
        if (!type) return;
        filters[type] = button.dataset.filterValue || 'all';
        recentPage = 1;
        setActiveButtons();
        renderRecentTrades();
      });
    });
    refreshData();
    setInterval(refreshData, REFRESH_MS);
    setInterval(updateFreshness, 30000);
  </script>
</body>
</html>
"""
    return html.replace("__DASHBOARD_STATE_JSON__", state_json)


_DEFAULT_RECORDER: TradeDashboardRecorder | None = None


def get_default_recorder() -> TradeDashboardRecorder:
    global _DEFAULT_RECORDER
    if _DEFAULT_RECORDER is None:
        _DEFAULT_RECORDER = TradeDashboardRecorder()
    return _DEFAULT_RECORDER


def process_setup_live_log_line(line: str) -> bool:
    return get_default_recorder().process_setup_live_line(line)


def record_scanner_signals(signals: list[dict[str, Any]]) -> None:
    get_default_recorder().record_scanner_signals(signals)


def rebuild_dashboard_from_logs(
    *,
    setup_log: Path | str | None = None,
    ccxt_log: Path | str | None = None,
    state_path: Path | str | None = None,
    html_path: Path | str | None = None,
    setup_state_path: Path | str | None = None,
    sync_live_exposure: bool = False,
) -> TradeDashboardRecorder:
    recorder = TradeDashboardRecorder(state_path=state_path, html_path=html_path, setup_state_path=setup_state_path)
    recorder.rebuild_from_logs(setup_log=setup_log, ccxt_log=ccxt_log, sync_live_exposure=sync_live_exposure)
    return recorder


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the OpenClaw trade ops HTML dashboard.")
    parser.add_argument("command", nargs="?", default="rebuild", choices=["rebuild"])
    parser.add_argument("--setup-log", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--ccxt-log", default=str(DEFAULT_CCXT_LOG_PATH))
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--html", default=str(DEFAULT_HTML_PATH))
    parser.add_argument("--setup-state", default=str(DEFAULT_SETUP_STATE_PATH))
    parser.add_argument("--live-exposure", action="store_true", help="consulta posicoes live Nado/Kraken")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    recorder = rebuild_dashboard_from_logs(
        setup_log=args.setup_log,
        ccxt_log=args.ccxt_log,
        state_path=args.state,
        html_path=args.html,
        setup_state_path=args.setup_state,
        sync_live_exposure=args.live_exposure,
    )
    print(f"state={recorder.state_path}")
    print(f"html={recorder.html_path}")
    print(f"trades={len(recorder.state.get('trades', []))}")
    print(f"analyses={len(recorder.state.get('analyses', []))}")


if __name__ == "__main__":
    main()
