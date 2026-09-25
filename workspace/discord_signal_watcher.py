#!/usr/bin/env python3
"""Forward setup-live dry-run entry signals to the operator's channels.

This watches the analyzer log and sends one notice per "setup-live entry" line
through the same delivery as `setup-live` (the operator's OpenClaw channels).
It does not open, close, or manage trades.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from workspace import cli  # entrega unica, a mesma do setup-live

try:
    from workspace.trade_dashboard import TradeDashboardRecorder
except Exception:  # noqa: BLE001
    TradeDashboardRecorder = None


SKILL_ID = "trade-automatizado-openclaw"
HOME = Path.home()
DEFAULT_LOG = HOME / ".openclaw" / "logs" / SKILL_ID / "setup-live-analyzer.log"
DEFAULT_STATE = HOME / ".openclaw" / "state" / SKILL_ID / "discord_signal_watcher.offset"
LOG_PATH = Path(os.environ.get("SETUP_SIGNAL_WATCH_LOG", DEFAULT_LOG)).expanduser()
STATE_PATH = Path(os.environ.get("SETUP_SIGNAL_WATCH_STATE", DEFAULT_STATE)).expanduser()
TRADE_NOTICE_TZ = ZoneInfo(os.environ.get("SETUP_NOTIFY_TIMEZONE", "America/Sao_Paulo") or "America/Sao_Paulo")
FLUSH_SECONDS = float(os.environ.get("SETUP_SIGNAL_WATCH_FLUSH_SECONDS", "20"))
MAX_BATCH = int(os.environ.get("SETUP_SIGNAL_WATCH_MAX_BATCH", "1"))
LEVERAGE = float(os.environ.get("SETUP_SIGNAL_WATCH_LEVERAGE", os.environ.get("SETUP_TEST_LEVERAGE", "5")))
RISK_PROFILE = os.environ.get("SETUP_SIGNAL_WATCH_RISK_PROFILE", os.environ.get("SETUP_TEST_RISK_PROFILE", "moderate"))

SETUP_LABELS = {
    "grid": "Grid Strategy",
    "grid-strict": "Grid STRICT Strategy",
    "institutional-strict": "Institutional STRICT Strategy",
    "hybrid": "HYBRID Strategy",
    "hybrid-15m": "HYBRID 15m Strategy",
    "delta-neutral": "Delta-Neutral Strategy",
}

SETUP_TIMEFRAMES = {
    "hybrid-15m": "15m",
}

ENTRY_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*setup-live entry \| "
    r"(?P<setup>[^ ]+) (?P<symbol>[^ ]+) \| side=(?P<side>[^ ]+) \| mode=(?P<mode>[^ ]+)"
    r"(?: \| entry=(?P<entry_price>[-+0-9.eE]+) \| stop=(?P<stop_price>[-+0-9.eE]+) "
    r"\| tp=(?P<take_profit>[-+0-9.eE]+) \| targets=(?P<targets_csv>[^|]*))?"
    r" \| reason=(?P<reason>.*)$"
)


def _read_offset(default: int) -> int:
    try:
        return int(STATE_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return default


def _write_offset(offset: int) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(str(offset), encoding="utf-8")


def _notice_brand_label() -> str:
    return os.environ.get("SETUP_NOTIFY_BRAND", "").strip()


def _notice_header_lines(title: str) -> list[str]:
    brand = _notice_brand_label()
    if not brand:
        return [title]
    return [brand, title]


def _format_trade_datetime(raw_ts: str) -> str:
    try:
        dt = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(TRADE_NOTICE_TZ)
    except ValueError:
        dt = datetime.fromtimestamp(time.time(), tz=TRADE_NOTICE_TZ)
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year}, {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} BRT"


def _format_trade_symbol(symbol: str) -> str:
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("/", "")
    if cleaned and not cleaned.endswith(("USDT", "USDC", "USD")):
        cleaned = f"{cleaned}USDT"
    return cleaned or "N/A"


def _side_notice_label(side: str) -> str:
    normalized = str(side or "").lower()
    if normalized == "long":
        return "LONG 🟢"
    if normalized == "short":
        return "SHORT 🔴"
    return normalized.upper() or "N/A"


def _risk_notice_label(profile: str) -> str:
    normalized = str(profile or "").lower()
    return {
        "conservative": "Conservador",
        "moderate": "Moderado",
        "aggressive": "Agressivo",
        "degen": "Agressivo",
    }.get(normalized, normalized.capitalize() if normalized else "Moderado")


def _leverage_notice_label(leverage: float) -> str:
    return f"{leverage:g}x" if leverage > 0 else "N/A"


def _format_notice_price(raw: str | None) -> str:
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return "N/A"
    if value <= 0:
        return "N/A"
    if value >= 100:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _format_notice_targets(entry: dict[str, str]) -> str:
    return " | ".join(_format_notice_targets_block(entry)).replace("→ ", "")


def _format_symbol_pair(symbol: str) -> str:
    cleaned = str(symbol or "").upper().split(":", 1)[0].replace("-", "/")
    if "/" in cleaned:
        base, quote = cleaned.split("/", 1)
        return f"{base}/{quote or 'USDT'}"
    for quote in ("USDT", "USDC", "USD"):
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            return f"{cleaned[:-len(quote)]}/{quote}"
    return f"{cleaned or 'N/A'}/USDT"


def _format_notice_money(raw: str | None) -> str:
    price = _format_notice_price(raw)
    if price == "N/A" or price.startswith("$"):
        return price
    return f"${price}"


def _raw_targets(entry: dict[str, str]) -> list[str]:
    raw_targets = [item.strip() for item in str(entry.get("targets_csv") or "").split(",") if item.strip()]
    if not raw_targets and entry.get("take_profit"):
        raw_targets = [entry["take_profit"]]
    return raw_targets[:4]


def _format_notice_targets_block(entry: dict[str, str]) -> list[str]:
    raw_targets = _raw_targets(entry)
    if not raw_targets:
        return ["→ Alvo 1: N/A"]
    return [f"→ Alvo {idx}: {_format_notice_money(target)}" for idx, target in enumerate(raw_targets, start=1)]


def _watcher_rr(entry: dict[str, str]) -> str:
    try:
        entry_price = float(entry.get("entry_price") or 0.0)
        stop_price = float(entry.get("stop_price") or 0.0)
        targets = [float(target) for target in _raw_targets(entry) if float(target or 0.0) > 0]
    except (TypeError, ValueError):
        return "N/A"
    if not targets:
        return "N/A"
    risk = abs(entry_price - stop_price)
    reward = abs(targets[-1] - entry_price)
    if risk <= 0 or reward <= 0:
        return "N/A"
    return f"{reward / risk:.2f}"


def _format_message(entry: dict[str, str]) -> str:
    setup = entry.get("setup", "")
    symbol_pair = _format_symbol_pair(entry.get("symbol", ""))
    base = symbol_pair.split("/", 1)[0]
    setup_label = SETUP_LABELS.get(setup, setup)
    timeframe = SETUP_TIMEFRAMES.get(setup, "1h")
    side = str(entry.get("side", "")).upper() or "N/A"
    reason = str(entry.get("reason", "Setup detectado pelo robô.")).strip().rstrip(".")
    rr = _watcher_rr(entry)
    # Audiencia e do operador: sem valor padrao.
    audience = os.environ.get("SETUP_NOTIFY_DISCORD_AUDIENCE", "").strip()
    risk_text = os.environ.get(
        "SETUP_NOTIFY_RISK_TEXT",
        "5% da banca destinada a trading futuros com alavancagem máxima de 5x.",
    ).strip()
    disclaimer = os.environ.get(
        "SETUP_NOTIFY_DISCLAIMER",
        "O mercado de criptomoedas é altamente volátil e imprevisível. As análises e operações compartilhadas aqui são baseadas em indicadores técnicos, price action e outros dados de mercado, mas NÃO constituem recomendação de investimento. Cada participante deve realizar sua própria análise e entrar em qualquer operação por conta e risco próprios.",
    ).strip()
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
            f"→ {reason}.",
            f"→ Entrada técnica em {_format_notice_money(entry.get('entry_price'))} com invalidação em {_format_notice_money(entry.get('stop_price'))}.",
            f"→ Relação risco/retorno estimada: {rr}.",
            f"→ Operação {side} segue válida enquanto não perder a invalidação em {_format_notice_money(entry.get('stop_price'))}.",
            "",
            "Leitura técnica:",
            f"A estrutura favorece busca pelos alvos enquanto as condições do setup continuarem sustentando a direção do movimento. Relação risco/retorno estimada: {rr}.",
            "",
            "Trading:",
            f"Operação: {side}",
            f"Entrada: {_format_notice_money(entry.get('entry_price'))}",
            f"Stop: {_format_notice_money(entry.get('stop_price'))}",
            "",
            "Alvos:",
            *_format_notice_targets_block(entry),
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
    return "\n".join(lines)[:3900]


def _entry_chart_payload(entry: dict[str, str]) -> dict[str, object]:
    targets: list[float] = []
    for target in _raw_targets(entry):
        try:
            value = float(target)
        except (TypeError, ValueError):
            continue
        if value > 0:
            targets.append(value)
    return {
        "symbol": _format_symbol_pair(entry.get("symbol", "")),
        "setup": entry.get("setup", ""),
        "setup_key": entry.get("setup", ""),
        "setup_label": SETUP_LABELS.get(entry.get("setup", ""), entry.get("setup", "")),
        "timeframe": SETUP_TIMEFRAMES.get(entry.get("setup", ""), "1h"),
        "side": str(entry.get("side", "")).upper() or "N/A",
        "entry_price": float(entry.get("entry_price") or 0.0),
        "stop_price": float(entry.get("stop_price") or 0.0),
        "targets": targets,
        "reason": str(entry.get("reason") or "Setup detectado pelo watcher."),
    }


def _send(entries: list[dict[str, str]]) -> None:
    """Entrega cada entrada pelo mesmo caminho do `setup-live`.

    Canal, destino, conta, topico e copias extras vem da mesma configuracao
    (`SETUP_NOTIFY_ENTRY_*`); tudo sai pelo OpenClaw do operador.
    """
    for entry in entries:
        sent = cli._send_setup_trade_notice(_format_message(entry), _entry_chart_payload(entry))
        print(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} entrega sinal=1 "
            f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')} "
            f"enviado={','.join(sorted(sent)) or '-'}",
            flush=True,
        )


def _dashboard_enabled() -> bool:
    raw = os.environ.get("SETUP_DASHBOARD_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "nao", "off"}


def _dashboard_rebuild_on_start() -> bool:
    raw = os.environ.get("SETUP_DASHBOARD_REBUILD_ON_START", "true").strip().lower()
    return raw not in {"0", "false", "no", "nao", "off"}


def _build_dashboard_recorder():
    if not _dashboard_enabled() or TradeDashboardRecorder is None:
        return None
    try:
        recorder = TradeDashboardRecorder()
        if _dashboard_rebuild_on_start():
            recorder.rebuild_from_logs(setup_log=LOG_PATH)
        return recorder
    except Exception as exc:  # noqa: BLE001
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} dashboard erro inicial: {exc}", flush=True)
        return None


def _record_dashboard_line(recorder, line: str) -> None:
    if recorder is None:
        return
    try:
        recorder.process_setup_live_line(line)
    except Exception as exc:  # noqa: BLE001
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} dashboard erro: {exc}", flush=True)


def main() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    while not LOG_PATH.exists():
        time.sleep(2)

    dashboard = _build_dashboard_recorder()
    with LOG_PATH.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(_read_offset(handle.tell()))
        batch: list[dict[str, str]] = []
        last_entry_at = 0.0

        while True:
            line = handle.readline()
            if not line:
                if batch and time.time() - last_entry_at >= FLUSH_SECONDS:
                    _send(batch)
                    batch = []
                time.sleep(1)
                continue

            _write_offset(handle.tell())
            stripped = line.strip()
            _record_dashboard_line(dashboard, stripped)
            match = ENTRY_RE.match(stripped)
            if match:
                batch.append(match.groupdict())
                last_entry_at = time.time()
                if len(batch) >= MAX_BATCH:
                    _send(batch)
                    batch = []
                continue

            if batch and ("setup-live iteracao=" in line or "setups live gerenciados:" in line):
                _send(batch)
                batch = []


if __name__ == "__main__":
    main()
