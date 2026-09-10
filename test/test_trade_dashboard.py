from __future__ import annotations

import json
from datetime import datetime, timezone

from workspace.trade_dashboard import TradeDashboardRecorder, _extract_openrouter_plans_from_pricing_text, _normalize_openrouter_model


def test_dashboard_counts_target_hit_as_operational_win(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )

    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live entry | grid-strict BTC/USDT | "
        "side=long | mode=hedged | reason=EMA9>EMA21",
        flush=False,
    )
    recorder.process_setup_live_line(
        "2026-05-05 12:05:00 [INFO] setup-live exit | grid-strict BTC/USDT | reason=TP1 atingido | live=101.0000",
        flush=False,
    )
    recorder.flush()

    assert recorder.state["summary"]["wins"] == 1
    assert recorder.state["summary"]["losses"] == 0
    assert recorder.state["summary"]["win_rate"] == 100.0
    assert recorder.state["trades"][0]["targets_hit"] == 1
    assert recorder.state["trades"][0]["status"] == "closed"
    assert recorder.state["trades"][0]["target_levels"][0]["hit"] is True
    assert (tmp_path / "dashboard-data.json").exists()
    assert "Painel operacional de trades" in (tmp_path / "dashboard.html").read_text(encoding="utf-8")


def test_setup_live_state_merges_nearby_entry_and_marks_current_open(tmp_path):
    setup_state_path = tmp_path / "setup_live_state.json"
    opened_at = datetime(2026, 5, 5, 12, 0, 1, tzinfo=timezone.utc).timestamp()
    setup_state_path.write_text(
        json.dumps(
            [
                {
                    "setup_key": "low-stoch-storm",
                    "symbol": "LTC/USDT",
                    "timeframe": "4h",
                    "side": "long",
                    "pair_state": {
                        "nado_entry": 56.35,
                        "kraken_entry": 56.35,
                        "opened_at": opened_at,
                        "effective_venue": "hedged",
                    },
                    "reference_entry_price": 56.35,
                    "stop_price": 54.7,
                    "take_profit": 61.2,
                    "targets_hit": 0,
                    "entry_reason": "Low Stoch Storm signal",
                    "execution_mode": "hedged",
                    "effective_venue": "hedged",
                    "margin_mode": "cross",
                    "leverage": 5,
                    "opened_at_ts": opened_at,
                    "metadata": {
                        "target_levels": [{"label": "TP1", "price": 57.9, "nado_qty": 1, "kraken_qty": 1}]
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=setup_state_path,
    )

    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live entry | low-stoch-storm LTC/USDT | "
        "side=long | mode=hedged | reason=Low Stoch Storm signal",
        flush=False,
    )
    recorder.sync_setup_live_state(flush=False)
    recorder.flush()

    assert len(recorder.state["trades"]) == 1
    assert recorder.state["trades"][0]["entry_price"] == 56.35
    assert recorder.state["trades"][0]["status"] == "open"
    assert recorder.state["summary"]["open_trades"] == 1
    setup_row = recorder.state["summary"]["setup_performance"][0]
    assert setup_row["entries"] == 1
    assert setup_row["current_take_profits"][0]["symbol"] == "LTC/USDT"
    assert setup_row["current_take_profits"][0]["targets"] == [57.9, 61.2]
    assert setup_row["current_take_profits"][0]["target_levels"][0]["label"] == "TP1"


def test_setup_live_enriched_entry_preserves_prices_and_targets(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )

    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live entry | grid-strict ETH/USDT | side=short | mode=kraken "
        "| entry=2500 | stop=2575 | tp=2400 | targets=2475,2440,2400 | reason=EMA9<EMA21",
        flush=False,
    )
    recorder.flush()

    trade = recorder.state["trades"][0]
    assert trade["side"] == "short"
    assert trade["entry_price"] == 2500.0
    assert trade["stop_price"] == 2575.0
    assert trade["target_price"] == 2400.0
    assert trade["targets"] == [2475.0, 2440.0, 2400.0]
    assert [level["label"] for level in trade["target_levels"]] == ["TP1", "TP2", "TP3"]


def test_ccxt_enriched_entry_preserves_scanner_targets(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )

    recorder.process_ccxt_log_line(
        "2026-05-05 12:01:00 [INFO] entry | kraken SOL/USDT | setup=grid-strict | side=long | "
        "timeframe=15m | entry=140 | stop=134 | tp=152 | targets=145,149,152 | reason=breakout confirmed",
        flush=False,
    )
    recorder.flush()

    trade = recorder.state["trades"][0]
    assert trade["source"] == "ccxt-public-scanner"
    assert trade["status"] == "signal"
    assert trade["entry_price"] == 140.0
    assert trade["stop_price"] == 134.0
    assert trade["targets"] == [145.0, 149.0, 152.0]
    assert recorder.state["summary"]["scanner_signals"] == 1


def test_repeated_target_exits_keep_original_trade_side(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )

    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live entry | low-stoch-storm PUMP/USDT | "
        "side=long | mode=hedged | reason=Low Stoch Storm signal",
        flush=False,
    )
    recorder.process_setup_live_line(
        "2026-05-05 12:05:00 [INFO] setup-live exit | low-stoch-storm PUMP/USDT | "
        "reason=TP1 atingido | live=0.0019",
        flush=False,
    )
    recorder.process_setup_live_line(
        "2026-05-05 12:10:00 [INFO] setup-live exit | low-stoch-storm PUMP/USDT | "
        "reason=TP2 atingido | live=0.0020",
        flush=False,
    )
    recorder.flush()

    assert len(recorder.state["trades"]) == 1
    trade = recorder.state["trades"][0]
    assert trade["side"] == "long"
    assert trade["targets_hit"] == 2
    assert all(item.get("side") in {"long", "short"} for item in recorder.state["trades"])
    assert recorder.state["summary"]["wins"] == 1


def test_orphan_exit_is_recorded_as_analysis_not_trade(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )

    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live exit | grid-strict BTC/USDT | reason=TP1 atingido | live=101.0000",
        flush=False,
    )
    recorder.flush()

    assert recorder.state["trades"] == []
    assert recorder.state["summary"]["wins"] == 0
    assert recorder.state["summary"]["resolved_trades"] == 0
    assert recorder.state["analyses"][0]["kind"] == "orphan-exit"


def test_model_search_filters_selector_and_supports_fuzzy_terms(tmp_path):
    recorder = TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )
    recorder.record_analysis({"ts": "2026-05-05T12:00:00Z", "kind": "scan", "reason": "smoke"}, flush=False)
    recorder.flush()
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")

    assert "function normalizeModelSearchText" in html
    assert "function modelMatchesSearch" in html
    assert "renderModelSelect(filteredModels)" in html
    assert "Nenhum modelo encontrado para a busca e filtros atuais." in html


def test_openrouter_pricing_parser_extracts_plan_values():
    text = (
        "Free Pay-as-you-go Enterprise Platform Fees N/A 5.5% Bulk discounts available "
        "Models Explore all models → 25+ free models 400+ models 400+ models "
        "Providers Explore all models → 4 free providers 60+ providers 60+ providers "
        "Chat and API Access Try chat now → Payment options Credit card, crypto & more Invoicing options "
        "BYOK Limits Learn more → 1M free reqs/month, 5% fee after 5M free reqs/month; custom pricing "
        "Rate limits 50 reqs/day High global limits Optional dedicated limits "
        "Token Pricing Free models only No minimum spend. Prices based on models Volume commitments. Prices based on models "
        "Support Community Support Email Support Support SLA with Shared Slack Channel Get Started For Free "
        "Free users have a limit of 50 requests per day and 20 requests per minute (rpm) "
        "No limits on paid models 1000 request limit on free models with 20 RPM"
    )

    plans = _extract_openrouter_plans_from_pricing_text(text)

    assert plans[0]["platform_fee"] == "N/A"
    assert plans[0]["providers"] == "4 free providers"
    assert plans[1]["platform_fee_pct"] == 5.5
    assert plans[1]["rate_limit"] == "High global limits"
    assert plans[1]["token_pricing"] == "No minimum spend. Prices based on models"
    assert plans[2]["byok"] == "5M free reqs/month; custom pricing"


def test_openrouter_model_normalizer_keeps_extra_pricing_fields():
    model = _normalize_openrouter_model(
        {
            "id": "provider/model",
            "name": "Provider Model",
            "pricing": {
                "prompt": "0.0000001",
                "completion": "0.0000002",
                "request": "0.001",
                "web_search": "0.01",
                "internal_reasoning": "0.0000003",
                "input_cache_read": "0.00000004",
                "input_cache_write": "0.00000005",
            },
            "context_length": 128000,
            "supported_parameters": ["tools", "response_format"],
        }
    )

    assert model is not None
    assert round(model["input"], 4) == 0.1
    assert round(model["output"], 4) == 0.2
    assert model["request"] == 0.001
    assert model["web_search"] == 0.01
    assert round(model["internal_reasoning"], 4) == 0.3
    assert round(model["input_cache_read"], 4) == 0.04
    assert round(model["input_cache_write"], 4) == 0.05
