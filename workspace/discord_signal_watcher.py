#!/usr/bin/env python3
"""Forward setup-live dry-run entry signals to Discord.

This watches the analyzer log and sends one Discord card per "setup-live entry"
line. It does not open, close, or manage trades.
"""

from __future__ import annotations

import os
import re
import json
import mimetypes
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

try:
    from workspace.trade_dashboard import TradeDashboardRecorder
except Exception:  # noqa: BLE001
    TradeDashboardRecorder = None


SKILL_ID = "trade-automatizado-openclaw"
HOME = Path.home()
DEFAULT_LOG = HOME / ".openclaw" / "logs" / SKILL_ID / "setup-live-analyzer.log"
DEFAULT_STATE = HOME / ".openclaw" / "state" / SKILL_ID / "discord_signal_watcher.offset"
DEFAULT_ENV_FILE = HOME / ".config" / "openclaw" / f"{SKILL_ID}.env"
LOG_PATH = Path(os.environ.get("SETUP_SIGNAL_WATCH_LOG", DEFAULT_LOG)).expanduser()
STATE_PATH = Path(os.environ.get("SETUP_SIGNAL_WATCH_STATE", DEFAULT_STATE)).expanduser()
TARGET = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "").strip()
DISCORD_ACCOUNT = os.environ.get("SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT", "default").strip()
OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "openclaw")
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


def _discord_message_prefix() -> str:
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_MENTION", "").strip()
    if raw.lower() in {"0", "false", "no", "nao", "off", "none"}:
        return ""
    if raw.lower() in {"1", "true", "yes", "sim", "everyone"}:
        return "@everyone"
    return raw


def _discord_allowed_mentions(text: str) -> dict:
    clean = str(text or "")
    roles = list(dict.fromkeys(re.findall(r"<@&(\d+)>", clean)))[:25]
    parse = ["everyone"] if clean.strip().startswith("@everyone") else []
    payload: dict[str, object] = {"parse": parse}
    if roles:
        payload["roles"] = roles
    return payload


def _discord_box_enabled() -> bool:
    raw = os.environ.get("SETUP_NOTIFY_DISCORD_BOX", "true").strip().lower()
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
    if prefix:
        clean_message = f"{prefix}\n{clean_message}"
    return _box_discord_message(clean_message)


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
    audience = os.environ.get("SETUP_NOTIFY_DISCORD_AUDIENCE", "@intus Club Member").strip()
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
        return ""
    return ""


def _discord_channel_id(target: str) -> str:
    if target.startswith("channel:"):
        return target.split(":", 1)[1].strip()
    if target.isdigit():
        return target
    return ""


def _setup_chart_enabled() -> bool:
    raw = os.environ.get("SETUP_NOTIFY_TRADINGVIEW_IMAGE", os.environ.get("SETUP_NOTIFY_CHART_ENABLED", "true")).strip().lower()
    return raw not in {"0", "false", "no", "nao", "off", "none"}


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


def _tradingview_attachment(entry: dict[str, str]) -> Path | None:
    if not _setup_chart_enabled():
        return None
    try:
        from workspace.tradingview_chart import render_tradingview_chart

        return render_tradingview_chart(_entry_chart_payload(entry))
    except Exception as exc:  # noqa: BLE001
        print(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} grafico TradingView/static falhou "
            f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')} erro={exc}",
            flush=True,
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
    if clean_prefix and not clean_message.startswith(clean_prefix):
        clean_message = f"{clean_prefix}\n{clean_message}" if clean_message else clean_prefix
    if len(clean_message) <= 2000:
        return clean_message
    for marker in ("\nDisclaimer:", "\nGerenciamento de risco:"):
        head = clean_message.split(marker, 1)[0].rstrip()
        if head and len(head) <= 1980:
            return f"{head}\n\nTexto encurtado para caber em uma única mensagem do Discord."
    return clean_message[:1970].rstrip() + "\n…"


def _build_discord_embed(message: str, entry: dict[str, str], image_path: Path | None = None) -> dict[str, object]:
    lines = [line.rstrip() for line in str(message or "").splitlines()]
    title = next((line for line in lines if line.strip()), "🚨 NOVA OPERAÇÃO 🚨")
    body = "\n".join(line for line in lines[1:] if line.strip())[:4096]
    side = str(entry.get("side") or "").upper()
    embed: dict[str, object] = {
        "title": title[:256],
        "description": body or "\u200b",
        "color": 0x2ECC71 if side == "LONG" else 0xE74C3C if side == "SHORT" else 0xF1C40F,
    }
    author = os.environ.get("SETUP_NOTIFY_DISCORD_EMBED_AUTHOR", os.environ.get("SETUP_NOTIFY_BRAND", "")).strip()
    if author:
        embed["author"] = {"name": author}
    if image_path is not None and image_path.is_file():
        embed["image"] = {"url": f"attachment://{image_path.name}"}
    return embed


def _send_discord_direct(target: str, message: str, entry: dict[str, str], image_path: Path | None = None) -> bool:
    token = _discord_bot_token()
    channel_id = _discord_channel_id(target)
    if not token or not channel_id:
        return False
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
    timeout = int(os.environ.get("SETUP_NOTIFY_TIMEOUT_SECONDS", "15"))
    for attempt in range(2):
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            data=data,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": content_type,
                "User-Agent": "trader-low_stoch-setup-watcher",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                elapsed = time.monotonic() - started
                message_id = ""
                try:
                    message_id = str(json.loads(body).get("id") or "")
                except Exception:
                    pass
                print(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord direct status={response.status} sinal=1 "
                    f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')} "
                    f"message_id={message_id or '-'} elapsed={elapsed:.1f}s",
                    flush=True,
                )
                return 200 <= int(response.status) < 300
        except urllib.error.HTTPError as exc:
            detail = exc.read(300).decode("utf-8", errors="replace")
            if exc.code == 429 and attempt == 0:
                try:
                    retry_after = float(json.loads(detail).get("retry_after", 1.0))
                except Exception:
                    retry_after = 1.0
                time.sleep(min(max(retry_after, 0.3), float(timeout)))
                continue
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord direct erro sinal=1 "
                f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')} status={exc.code} detail={detail}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord direct erro sinal=1 "
                f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')} erro={exc}",
                flush=True,
            )
        return False
    return False


def _send(entries: list[dict[str, str]]) -> None:
    if not TARGET or not entries:
        return
    target = TARGET if TARGET.startswith(("channel:", "user:")) else f"channel:{TARGET}"
    for entry in entries:
        raw_message = _format_message(entry)
        image_path = _tradingview_attachment(entry)
        if _send_discord_direct(target, raw_message, entry, image_path):
            continue
        message = _with_discord_message_prefix(raw_message)
        fallback_openclaw = os.environ.get("SETUP_NOTIFY_FALLBACK_OPENCLAW", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "sim",
        }
        if not fallback_openclaw:
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord skip fallback_openclaw=0 sinal=1 "
                f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')}",
                flush=True,
            )
            continue
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
        if image_path is not None and image_path.is_file():
            cmd.extend(["--media", str(image_path)])
        if DISCORD_ACCOUNT:
            cmd.extend(["--account", DISCORD_ACCOUNT])
        try:
            result = subprocess.run(cmd, check=False, timeout=75)
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord rc={result.returncode} sinal=1 "
                f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')}",
                flush=True,
            )
        except subprocess.TimeoutExpired:
            print(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} discord timeout sinal=1 "
                f"symbol={entry.get('symbol', '')} setup={entry.get('setup', '')}",
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
