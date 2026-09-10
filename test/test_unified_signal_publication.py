from __future__ import annotations

import importlib
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

scanner = importlib.import_module("workspace.ccxt_entry_scanner")


def _sample_signal() -> dict:
    return {
        "exchange": "hyperliquid",
        "symbol": "WLD/USDC:USDC",
        "setup": "institutional-strict",
        "side": "long",
        "timeframe": "1h",
        "reason": "teste de setup validado",
        "entry_price": 1.2345,
        "stop_price": 1.1111,
        "take_profit": 1.5555,
        "targets": [1.3, 1.4, 1.5, 1.6],
        "leverage": 5,
        "risk_profile": "moderate",
        "created_at": 1784846103.525133,
        "bar_at": "2026-07-25T13:00:00+00:00",
    }


def test_structured_call_is_stable_source_for_both_channels():
    signal = _sample_signal()
    structured = scanner._structured_signal_call(signal)
    discord_message = scanner._format_signal_notice(signal)
    whatsapp_message = scanner._format_whatsapp_from_discord_notice(discord_message)

    assert structured["idempotency_key"] == scanner._signal_idempotency_key(signal)
    assert structured["pair"] == "WLD/USDC"
    assert structured["symbol"] == "WLDUSDC"
    assert structured["setup_slug"] == "institutional-strict"
    assert structured["side"] == "LONG"
    assert structured["raw_payload"] == signal

    assert "WLD" in discord_message
    assert "WLD" in whatsapp_message
    assert "institutional" in discord_message.lower() or "Institutional" in discord_message
    assert "Setup:" in whatsapp_message
    assert "Relação risco/retorno" not in whatsapp_message


def test_signal_idempotency_changes_by_bar_not_channel():
    signal = _sample_signal()
    same_signal = dict(signal)
    next_bar = dict(signal, bar_at="2026-07-25T14:00:00+00:00")

    assert scanner._signal_idempotency_key(signal) == scanner._signal_idempotency_key(same_signal)
    assert scanner._signal_idempotency_key(signal) != scanner._signal_idempotency_key(next_bar)


def test_whatsapp_entry_target_percentages_use_target_price_not_target_index():
    signal = _sample_signal()
    signal.update(
        {
            "symbol": "ETHFI/USDC:USDC",
            "entry_price": 0.43597,
            "stop_price": 0.4272506,
            "targets": [0.4446894, 0.4490491, 0.4534088, 0.4621282],
        }
    )

    discord_message = scanner._format_signal_notice(signal)
    whatsapp_message = scanner._format_whatsapp_from_discord_notice(discord_message)

    assert "Alvo 1: $0.44469 (+2.00%)" in whatsapp_message
    assert "Alvo 2: $0.44905 (+3.00%)" in whatsapp_message
    assert "Alvo 3: $0.45341 (+4.00%)" in whatsapp_message
    assert "Alvo 4: $0.46213 (+6.00%)" in whatsapp_message
    assert "+788" not in whatsapp_message
    assert "+2076" not in whatsapp_message
