from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import workspace.cli as cli
import workspace.run as run_wrapper
from workspace.config import ConfigError
import workspace.core.setups as setups_module
from workspace.core.delta_neutral import DeltaNeutralEngine, PairState
from workspace.core.live_setups import ManagedSetupState, evaluate_setup_entry, evaluate_setup_exit
from workspace.core.scenarios import FUNDING_ADVERSE, KRAKEN_SELF_FILL_RISK
from workspace.core.setups import (
    BacktestResult,
    DEFAULT_FUNDING_ARB_REAL_DAYS,
    DEFAULT_FUNDING_ARB_REAL_SYMBOLS,
    DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS,
    DEFAULT_TRIANGLE_REAL_DAYS,
    DEFAULT_TRIANGLE_REAL_SYMBOLS,
    DEFAULT_LOW_STOCH_REAL_DAYS,
    DEFAULT_LOW_STOCH_REAL_SYMBOLS,
    HYBRID_PROFILE_MAP,
    SETUP_CATALOG,
    CalibrationCandidateResult,
    FundingArbConfig,
    TriangleBreakoutConfig,
    _HybridRiskState,
    _hybrid_directional_return,
    _select_best_calibration_candidate,
    calibrate_funding_real,
    calibrate_triangle_real,
    calculate_triangle_breakout_signal,
    generate_operational_dataset,
    get_setup_execution_config,
    get_funding_arb_config,
    get_triangle_breakout_config,
    normalize_hybrid_profile,
    normalize_timeframe,
    parse_setup_selection,
    prepare_market_dataset,
    rank_backtest_results,
    run_funding_real_backtests,
    run_hybrid_real_backtests,
    run_operational_backtests,
    run_low_stoch_real_backtests,
)
from workspace.core.simulation import PROFILE_MAP, build_scenario_matrix, parse_profiles, summarize_simulation
from workspace.kraken.kraken_integration import KrakenPosition, KrakenTrader
from workspace.nado.decision import CryptoDecisionEngine
try:
    from workspace.nado.nado_integration import NadoTrader
except ImportError:  # SDK `nado-protocol` e opcional: so a venue Nado depende dele
    NadoTrader = None

requires_nado_sdk = pytest.mark.skipif(
    NadoTrader is None,
    reason="SDK nado-protocol ausente; a venue Nado e opcional",
)


def _target_stop_state(side: str, *, mode: str, venue: str = "nado") -> ManagedSetupState:
    entry = 100.0
    stop = 90.0 if side == "long" else 110.0
    targets = [110.0, 120.0, 130.0] if side == "long" else [90.0, 80.0, 70.0]
    pair_state = PairState(
        symbol="BTC/USDT",
        nado_product_id=1,
        kraken_symbol="BTC/USD:USD",
        nado_side=side if venue in {"nado", "hedged"} else "",
        kraken_side=side if venue == "kraken" else "",
        requested_notional_usd=100.0,
        effective_notional_usd=100.0,
        nado_qty=1.0 if venue in {"nado", "hedged"} else 0.0,
        kraken_qty=1.0 if venue in {"kraken", "hedged"} else 0.0,
        nado_entry=entry if venue in {"nado", "hedged"} else 0.0,
        kraken_entry=entry if venue in {"kraken", "hedged"} else 0.0,
        execution_mode=cli.EXECUTION_MODE_NADO_ONLY if venue == "nado" else cli.EXECUTION_MODE_KRAKEN_ONLY,
        effective_venue=venue,
        nado_stop_price=stop if venue in {"nado", "hedged"} else 0.0,
        kraken_stop_price=stop if venue in {"kraken", "hedged"} else 0.0,
    )
    return ManagedSetupState(
        setup_key="low-stoch-storm",
        symbol="BTC/USDT",
        timeframe="15m",
        side=side,
        pair_state=pair_state,
        reference_entry_price=entry,
        stop_price=stop,
        take_profit=targets[-1],
        execution_mode=pair_state.execution_mode,
        effective_venue=venue,
        metadata={
            "target_stop_mode": mode,
            "target_levels": [{"label": f"TP{idx}", "price": price} for idx, price in enumerate(targets, start=1)],
            "events": [],
        },
    )


def test_target_stop_mode_aliases_and_disabled_mode():
    assert cli._normalize_target_stop_mode("desligado") == cli.TARGET_STOP_MODE_OFF
    assert cli._normalize_target_stop_mode("entrada-no-tp1") == cli.TARGET_STOP_MODE_BREAKEVEN_ON_TP1
    assert cli._normalize_target_stop_mode("escada") == cli.TARGET_STOP_MODE_LADDER

    state = _target_stop_state("long", mode="desligado")
    move = cli._apply_target_stop_mode(state, previous_targets_hit=0, targets_hit=1)

    assert move is None
    assert state.stop_price == pytest.approx(90.0)
    assert state.pair_state.nado_stop_price == pytest.approx(90.0)


def test_target_stop_mode_breakeven_moves_only_to_entry_after_tp1():
    state = _target_stop_state("long", mode="entrada-no-tp1")

    first_move = cli._apply_target_stop_mode(state, previous_targets_hit=0, targets_hit=1)
    second_move = cli._apply_target_stop_mode(state, previous_targets_hit=1, targets_hit=2)

    assert first_move == {"old_stop": 90.0, "new_stop": 100.0, "mode": cli.TARGET_STOP_MODE_BREAKEVEN_ON_TP1}
    assert second_move is None
    assert state.stop_price == pytest.approx(100.0)
    assert state.pair_state.nado_stop_price == pytest.approx(100.0)
    assert state.metadata["target_stop_last_move"]["native_stop_replaced"] is False


def test_target_stop_mode_ladder_moves_long_and_short_stops():
    long_state = _target_stop_state("long", mode="escada")
    short_state = _target_stop_state("short", mode="escada")

    cli._apply_target_stop_mode(long_state, previous_targets_hit=0, targets_hit=1)
    cli._apply_target_stop_mode(long_state, previous_targets_hit=1, targets_hit=2)
    cli._apply_target_stop_mode(short_state, previous_targets_hit=0, targets_hit=1)
    cli._apply_target_stop_mode(short_state, previous_targets_hit=1, targets_hit=2)

    assert long_state.stop_price == pytest.approx(110.0)
    assert long_state.pair_state.nado_stop_price == pytest.approx(110.0)
    assert short_state.stop_price == pytest.approx(90.0)
    assert short_state.pair_state.nado_stop_price == pytest.approx(90.0)
    assert [event["type"] for event in long_state.metadata["events"]] == ["Stop Move", "Stop Move"]


def test_target_stop_mode_replaces_native_stop_when_ref_is_tracked():
    state = _target_stop_state("long", mode="entrada-no-tp1")
    state.metadata["native_orders"] = {"nado": {"venue_id": "hyperliquid", "sl": {"digest": "old-stop"}}}

    class FakeNado:
        def __init__(self):
            self.calls = []

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def replace_stop_loss(self, **kwargs):
            self.calls.append(kwargs)
            return {"cancelled": True, "order": SimpleNamespace(data=SimpleNamespace(digest="new-stop"))}

    fake_nado = FakeNado()
    eng = SimpleNamespace(nado=fake_nado, dex_id="hyperliquid", protective_stop_trigger_slippage_pct=0.02)

    move = cli._apply_target_stop_mode(state, previous_targets_hit=0, targets_hit=1, eng=eng)

    assert move == {"old_stop": 90.0, "new_stop": 100.0, "mode": cli.TARGET_STOP_MODE_BREAKEVEN_ON_TP1}
    assert fake_nado.calls[0]["previous_order_ref"]["digest"] == "old-stop"
    assert fake_nado.calls[0]["trigger_price"] == pytest.approx(100.0)
    assert state.metadata["target_stop_last_move"]["native_stop_replaced"] is True
    assert state.metadata["target_stop_native_replacement"] == "replace_stop_loss"
    new_ref = state.metadata["native_orders"]["nado"]["sl"]
    assert new_ref["digest"] == "new-stop"
    assert new_ref["venue_id"] == "hyperliquid"


def test_reconcile_native_fill_before_solo_partial_updates_quantity():
    state = _target_stop_state("long", mode="desligado")
    state.pair_state.nado_qty = 1.0
    state.pair_state.effective_notional_usd = 100.0

    class FakeNado:
        def get_perp_position_size(self, product_id):
            return 0.4

    eng = SimpleNamespace(nado=FakeNado(), dex_id="hyperliquid")

    result = cli._reconcile_native_fills_before_partial(eng, state)

    assert result["changed"] is True
    assert state.pair_state.nado_qty == pytest.approx(0.4)
    assert state.pair_state.effective_notional_usd == pytest.approx(40.0)
    assert state.metadata["native_fill_reconciliations"][0]["changes"][0]["closed_qty"] == pytest.approx(0.6)
    assert state.metadata["events"][-1]["type"] == "Native Fill Sync"


def test_solo_partial_does_not_duplicate_native_fill():
    state = _target_stop_state("long", mode="desligado")
    state.pair_state.nado_qty = 0.7

    class FakeNado:
        def __init__(self):
            self.orders = []

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"id": "market"}

    fake_nado = FakeNado()
    eng = SimpleNamespace(nado=fake_nado, slippage_bps=50)
    exit_signal = SimpleNamespace(metadata={"nado_qty": 0.3})

    assert cli._partial_close_solo_setup(eng, state, exit_signal, reconciled_closed_qty=0.3) is True
    assert fake_nado.orders == []

    cli._apply_solo_partial_close_to_state(state, exit_signal)
    assert state.pair_state.nado_qty == pytest.approx(0.7)


def test_doctor_is_venue_aware_for_hyperliquid(monkeypatch):
    monkeypatch.setenv("QC_SECRETS_PROXY", "1")
    monkeypatch.setenv("DELTA_NEUTRAL_NO_BOOTSTRAP", "1")
    monkeypatch.setenv("DEX_ID", "hyperliquid")
    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "0x1234567890abcdef1234567890abcdef12345678")
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    for name in ("NADO_OWNER_PRIVATE_KEY", "NADO_PRIVATE_KEY", "PRIVATE_KEY", "NADO_LINKED_SIGNER_PRIVATE_KEY"):
        monkeypatch.delenv(name, raising=False)

    report = run_wrapper.doctor()
    check_names = {item["name"] for item in report["checks"]}

    assert "hyperliquid_credentials" in check_names
    assert "hyperliquid_vault_optional" in check_names
    assert "nado_credentials" not in check_names
    assert report["venues"]["capabilities"]["dex"]["native_sl"] is True
    assert report["venues"]["capabilities"]["cex"]["reduce_only"] is True


def test_pair_state_from_legacy_payload():
    state = PairState.from_dict(
        {
            "symbol": "ETH/USDT",
            "nado_product_id": 4,
            "kraken_symbol": "ETH/USD:USD",
            "nado_side": "long",
            "kraken_side": "short",
            "notional_usd": 20.0,
            "nado_qty": 0.01,
            "kraken_qty": 0.01,
            "nado_entry": 2500.0,
            "kraken_entry": 2501.0,
        }
    )
    assert state.requested_notional_usd == 20.0
    assert state.effective_notional_usd == 20.0
    assert state.notional_usd == 20.0
    assert state.nado_subaccount_name == ""
    assert state.kraken_api_fingerprint == ""
    assert state.nado_stop_price == 0.0
    assert state.kraken_take_profit_price == 0.0
    assert state.nado_close_side == ""


def test_kraken_conflicts_filter_opposite_side_orders():
    trader = object.__new__(KrakenTrader)
    trader.get_open_orders = lambda symbol=None: [  # type: ignore[method-assign]
        {"id": "buy-1", "side": "buy", "type": "limit", "status": "open"},
        {"id": "sell-1", "side": "sell", "type": "limit", "status": "open"},
        {"id": "done-1", "side": "buy", "type": "limit", "status": "closed"},
    ]

    sell_conflicts = trader.get_market_order_conflicts("BTC/USD:USD", is_buy=False)
    buy_conflicts = trader.get_market_order_conflicts("BTC/USD:USD", is_buy=True)

    assert [c.order_id for c in sell_conflicts] == ["buy-1"]
    assert [c.order_id for c in buy_conflicts] == ["sell-1"]


def test_kraken_parse_position_fills_mark_and_pnl_from_ticker():
    trader = object.__new__(KrakenTrader)
    trader.get_market_mid_price = lambda symbol: 79000.0  # type: ignore[method-assign]

    parsed = trader._parse_position(  # type: ignore[attr-defined]
        {
            "symbol": "BTC/USD:USD",
            "side": "long",
            "contracts": 0.0026,
            "entryPrice": 78613.0,
            "markPrice": None,
            "unrealizedPnl": None,
            "leverage": None,
            "info": {
                "side": "long",
                "symbol": "PF_XBTUSD",
                "price": "78613.0",
                "size": "0.0026",
            },
        },
        "BTC/USD:USD",
    )

    assert parsed.side == "long"
    assert abs(parsed.size - 0.0026) < 1e-12
    assert parsed.mark_price == 79000.0
    assert round(parsed.unrealized_pnl, 6) == round(0.0026 * (79000.0 - 78613.0), 6)
    assert parsed.leverage == 1.0


def test_kraken_account_context_balance_params():
    trader = object.__new__(KrakenTrader)
    trader.venue = "futures"
    trader.account = "margin"
    trader.account_symbol = "BTC/USDT"
    trader.client = type("DummyClient", (), {"markets": {"BTC/USD:USD": {}}})()
    trader.normalize_symbol = lambda symbol: "BTC/USD:USD"  # type: ignore[method-assign]

    params = trader._build_balance_params()  # type: ignore[attr-defined]
    assert params == {"account": "margin", "symbol": "BTC/USD:USD"}

    trader.account = "flex"
    trader.account_symbol = None
    params = trader._build_balance_params()  # type: ignore[attr-defined]
    assert params == {"account": "flex"}


def test_kraken_trading_safety_flags_when_flag_false():
    trader = object.__new__(KrakenTrader)
    trader.venue = "futures"
    trader.detect_master_api_key = lambda: None  # type: ignore[method-assign]
    trader.require_subaccount = True
    trader.declared_is_subaccount = False

    safety = trader.get_trading_safety(require_subaccount=True, declared_is_subaccount=False)
    assert safety["safe"] is False
    assert "KRAKEN_API_IS_SUBACCOUNT=false" in safety["reason"]


def test_kraken_trading_safety_flags_master_keys():
    trader = object.__new__(KrakenTrader)
    trader.venue = "futures"
    trader.detect_master_api_key = lambda: True  # type: ignore[method-assign]
    trader.require_subaccount = True
    trader.declared_is_subaccount = True

    safety = trader.get_trading_safety(require_subaccount=True, declared_is_subaccount=True)
    assert safety["safe"] is False
    assert "conta master" in safety["reason"]


def test_kraken_trading_safety_flags_when_metadata_unknown():
    trader = object.__new__(KrakenTrader)
    trader.venue = "futures"
    trader.require_subaccount = True
    trader.declared_is_subaccount = True
    trader.detect_master_api_key = lambda: None  # type: ignore[method-assign]

    safety = trader.get_trading_safety(require_subaccount=True, declared_is_subaccount=True)
    assert safety["safe"] is False
    assert "Nao foi possivel validar a metadata" in safety["reason"]


@requires_nado_sdk
def test_nado_trade_ready_reports_when_linked_signer_missing():
    trader = object.__new__(NadoTrader)
    trader.trade_auth_error = "NADO_LINKED_SIGNER_PRIVATE_KEY ausente"
    trader._refresh_trade_auth_state = lambda: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="LINKED_SIGNER"):
        trader.assert_trade_ready()
    assert trader.is_trade_ready() is False
    assert "LINKED_SIGNER" in trader.trade_auth_error


@requires_nado_sdk
def test_nado_trade_ready_detects_linked_signer_mismatch():
    trader = object.__new__(NadoTrader)
    trader.require_linked_signer = True
    trader.linked_signer_private_key = "configured"
    trader.linked_signer_address = "0x1111111111111111111111111111111111111111"
    trader.linked_signer_query_error = None
    trader.subaccount_name = "default_1"
    trader._fetch_onchain_linked_signer = lambda: "0x2222222222222222222222222222222222222222"  # type: ignore[method-assign]

    trader._refresh_trade_auth_state()
    assert trader.trade_auth_error is not None
    assert "nao bate" in trader.trade_auth_error


@requires_nado_sdk
def test_nado_isolated_margin_uses_x6_appendix_units():
    from nado_protocol.utils.expiration import OrderType
    from nado_protocol.utils.order import order_is_isolated, order_isolated_margin

    trader = object.__new__(NadoTrader)
    trader.owner = "0x1111111111111111111111111111111111111111"
    trader.subaccount_name = "default_1"
    trader._get_size_increment_x18 = lambda _product_id: int(1e18)  # type: ignore[method-assign]
    trader._get_price_increment_x18 = lambda _product_id: int(1e14)  # type: ignore[method-assign]

    order = trader._build_order(  # type: ignore[attr-defined]
        price=1.462985,
        quantity=17.0,
        is_buy=True,
        product_id=58,
        order_type=OrderType.FOK,
        margin_mode="isolated",
        isolated_margin_usd=4.974149,
    )

    assert order_is_isolated(order.appendix) is True
    assert order_isolated_margin(order.appendix) == 4_974_149


def test_plan_live_hedges_targets_kraken_for_manual_nado_short():
    class FakeNado:
        def get_all_positions(self):
            return [
                SimpleNamespace(
                    symbol="BTC/USDT",
                    side="short",
                    size=-0.00005,
                    mark_price=78832.0,
                    notional_usd=3.94,
                    margin_mode="isolated",
                )
            ]

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def get_market_mid_price(self, product_id):
            return 78832.0

    class FakeKraken:
        def get_all_positions(self):
            return []

        def round_quantity_to_increment(self, symbol, quantity):
            return quantity

        def get_market_mid_price(self, symbol):
            return 78910.0

        def get_market_order_conflicts(self, symbol, is_buy):
            return []

    engine = SimpleNamespace(
        nado=FakeNado(),
        kraken=FakeKraken(),
        drift_bps=50,
        _nado_symbol_map={"BTC/USDT": 2},
        _kraken_symbol_map={"BTC/USDT": "BTC/USD:USD"},
        common_symbols=lambda: ["BTC/USDT"],
    )

    actions = cli._plan_live_hedges(engine, symbol="all", target_exchange="auto")

    assert len(actions) == 1
    action = actions[0]
    assert action.symbol == "BTC/USDT"
    assert action.target_exchange == "kraken"
    assert action.source_exchange == "nado"
    assert action.is_buy is True
    assert round(action.net_notional_usd, 6) == round(-0.00005 * 78832.0, 6)
    assert round(action.order_qty, 12) == round(abs(action.net_notional_usd) / 78910.0, 12)


def test_plan_live_hedges_targets_nado_for_manual_kraken_long():
    class FakeNado:
        def get_all_positions(self):
            return []

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def get_market_mid_price(self, product_id):
            return 2390.0

    class FakeKraken:
        def get_all_positions(self):
            return [
                KrakenPosition(
                    symbol="ETH/USD:USD",
                    side="long",
                    size=0.01,
                    entry_price=2388.0,
                    mark_price=2390.0,
                    unrealized_pnl=0.02,
                    leverage=1.0,
                )
            ]

        def round_quantity_to_increment(self, symbol, quantity):
            return quantity

        def get_market_mid_price(self, symbol):
            return 2390.0

        def get_market_order_conflicts(self, symbol, is_buy):
            return []

    engine = SimpleNamespace(
        nado=FakeNado(),
        kraken=FakeKraken(),
        drift_bps=50,
        _nado_symbol_map={"ETH/USDT": 4},
        _kraken_symbol_map={"ETH/USDT": "ETH/USD:USD"},
        common_symbols=lambda: ["ETH/USDT"],
    )

    actions = cli._plan_live_hedges(engine, symbol="all", target_exchange="auto")

    assert len(actions) == 1
    action = actions[0]
    assert action.symbol == "ETH/USDT"
    assert action.target_exchange == "nado"
    assert action.source_exchange == "kraken"
    assert action.is_buy is False
    assert abs(action.order_qty - 0.01) < 1e-12
    assert action.net_notional_usd == pytest.approx(23.9)


def test_execute_live_hedges_respects_dry_run():
    calls = {"kraken": 0}

    class FakeNado:
        def assert_trade_ready(self):
            return None

        def place_market_order(self, **kwargs):
            raise AssertionError("dry-run should not touch Nado")

    class FakeKraken:
        def validate_entry_subaccount_rule(self, **kwargs):
            calls["kraken"] += 1

        def place_market_order(self, **kwargs):
            raise AssertionError("dry-run should not touch Kraken")

    engine = SimpleNamespace(
        nado=FakeNado(),
        kraken=FakeKraken(),
        slippage_bps=100,
        kraken_require_subaccount=True,
        kraken_api_is_subaccount=False,
    )
    actions = [
        cli.LiveHedgeAction(
            symbol="BTC/USDT",
            base="BTC",
            source_exchange="nado",
            target_exchange="kraken",
            nado_qty=-0.00005,
            kraken_qty=0.0,
            net_qty=-0.00005,
            order_qty=0.00005,
            order_notional_usd=3.94,
            is_buy=True,
            drift_bps=10000.0,
            kraken_symbol="BTC/USD:USD",
        )
    ]

    executed, blocked = cli._execute_live_hedges(engine, actions, dry_run=True)

    assert executed == 0
    assert blocked == 0
    assert calls["kraken"] == 0


def test_simulation_profiles_and_summary():
    profiles = parse_profiles("1x,3x")
    assert [profile.name for profile in profiles] == ["1x", "3x"]

    rows = build_scenario_matrix(
        setup="funding",
        profile=PROFILE_MAP["3x"],
        funding_rate=0.0006,
        has_self_fill_risk=True,
        drift_bps=50,
        max_pair_loss_pct=0.03,
    )
    by_label = {row.response_label: row for row in rows}

    assert by_label[FUNDING_ADVERSE].risco == "alto"
    assert by_label[FUNDING_ADVERSE].ordem_real_permitida is False
    assert by_label[KRAKEN_SELF_FILL_RISK].risco == "alto"
    assert by_label[KRAKEN_SELF_FILL_RISK].ordem_real_permitida is False

    summary = summarize_simulation(
        symbol="BTC/USDT",
        setup="funding",
        profile=PROFILE_MAP["3x"],
        rows=rows,
    )
    assert summary.symbol == "BTC/USDT"
    assert summary.profile == "3x"
    assert summary.risco == "alto"
    assert summary.ordem_real_permitida is False


def test_setup_catalog_and_parser():
    removed = {
        "triangle-breakout",
        "institutional",
        "momentum",
        "momentum-strict",
        "bollinger-mean-reversion-strict",
    }
    assert not (removed & set(SETUP_CATALOG))
    assert "grid-strict" in SETUP_CATALOG
    assert "institutional-strict" in SETUP_CATALOG
    assert "delta-neutral" in SETUP_CATALOG
    assert "hybrid" in SETUP_CATALOG
    assert "hybrid-15m" in SETUP_CATALOG
    assert "bollinger-mean-reversion" in SETUP_CATALOG
    assert "funding-arb" in SETUP_CATALOG
    assert "low-stoch-storm" in SETUP_CATALOG
    assert "divergence-and-volume-4h" in SETUP_CATALOG
    assert SETUP_CATALOG["hybrid"].timeframe == "4h"
    assert SETUP_CATALOG["hybrid-15m"].timeframe == "15m"
    assert SETUP_CATALOG["bollinger-mean-reversion"].timeframe == "15m"
    assert parse_setup_selection("all") == list(setups_module.ACTIVE_SETUP_KEYS)
    assert parse_setup_selection("grid_strict,institutional_strict") == [
        "grid-strict",
        "institutional-strict",
    ]
    with pytest.raises(ValueError):
        parse_setup_selection("hybrid")
    with pytest.raises(ValueError):
        parse_setup_selection("hybrid15")
    assert parse_setup_selection("bollinger,funding,low_stoch,divergence-and-volume-4h") == [
        "bollinger-mean-reversion",
        "funding-arb",
        "low-stoch-storm",
        "divergence-and-volume-4h",
    ]
    for removed_key in removed:
        with pytest.raises(ValueError):
            parse_setup_selection(removed_key)
    assert normalize_timeframe("15") == "15m"
    assert normalize_timeframe("60m") == "1h"
    assert normalize_timeframe("4h") == "4h"
    assert normalize_hybrid_profile("conservador") == "conservative"
    assert normalize_hybrid_profile("moderado") == "moderate"
    assert normalize_hybrid_profile("degen") == "degen"


def test_triangle_and_funding_configs_support_env_overrides(monkeypatch):
    monkeypatch.setenv("TRIANGLE_PIVOT_WINDOW", "4")
    monkeypatch.setenv("TRIANGLE_CONTRACTION_MAX_RATIO", "0.86")
    monkeypatch.setenv("TRIANGLE_VOLUME_MULTIPLIER", "1.8")
    monkeypatch.setenv("TRIANGLE_BREAKOUT_BUFFER_ATR_MULT", "0.35")
    monkeypatch.setenv("TRIANGLE_FLAT_THRESHOLD_ATR_MULT", "0.07")
    monkeypatch.setenv("TRIANGLE_SLOPE_THRESHOLD_ATR_MULT", "0.03")
    monkeypatch.setenv("TRIANGLE_STOP_ATR_MULT", "1.2")
    monkeypatch.setenv("FUNDING_ARB_MIN_RATE", "0.00020")
    monkeypatch.setenv("FUNDING_ARB_EXIT_RATE", "0.00005")
    monkeypatch.setenv("FUNDING_ARB_MAX_HOLD_HOURS", "24")
    monkeypatch.setenv("FUNDING_ARB_MAX_SPREAD_BPS", "21")

    triangle = get_triangle_breakout_config()
    funding = get_funding_arb_config()

    assert triangle == TriangleBreakoutConfig(
        pivot_window=4,
        contraction_max_ratio=0.86,
        volume_multiplier=1.8,
        breakout_buffer_atr_mult=0.35,
        flat_threshold_atr_mult=0.07,
        slope_threshold_atr_mult=0.03,
        stop_atr_mult=1.2,
    )
    assert funding == FundingArbConfig(
        min_rate=0.00020,
        exit_rate=0.00005,
        max_hold_intervals=3,
        max_spread_bps=21.0,
    )


def test_cli_env_compatibility_helpers(monkeypatch):
    monkeypatch.setenv("CERTAINTY", "0.75 # decimal")
    assert cli._load_certainty_env() == 75
    monkeypatch.setenv("CERTAINTY", "75%")
    assert cli._load_certainty_env() == 75
    # Esta assercao dizia `== ""`: ou seja, consagrava o defeito. Vazio
    # significa **sem filtro de direcao** (`decision.py:497`), entao aceitar
    # que `true` -- que nao e direcao nenhuma -- resolva para vazio e afirmar
    # que a restricao do operador deve sumir em silencio. Ver
    # `test_filtros_de_entrada.py`.
    monkeypatch.setenv("UNIQUE_TREND", "true")
    with pytest.raises(ConfigError):
        cli._load_unique_trend_env()
    monkeypatch.delenv("UNIQUE_TREND", raising=False)
    assert cli._load_unique_trend_env() == ""
    monkeypatch.setenv("UNIQUE_TREND", "short")
    assert cli._load_unique_trend_env() == "SHORT"
    monkeypatch.delenv("NADO_OWNER_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("NADO_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("PRIVATE_KEY", "legacy-key")
    assert cli._load_nado_owner_private_key() == "legacy-key"
    assert run_wrapper._clean_env_value("mainnet # testnet | mainnet") == "mainnet"


def test_decision_engine_accepts_env_exchange_aliases():
    engine = CryptoDecisionEngine({"EXCHANGES": "nado,kraken", "SYMBOLS": ["ETH/USDT"]})
    assert engine.exchanges_config == ["krakenfutures"]
    assert "krakenfutures" in engine.exchanges


def test_operational_backtests_return_rankable_results():
    dataset, results = run_operational_backtests(
        setup_keys=["grid-strict", "grid"],
        days=10,
        initial_price=30000.0,
        seed=7,
    )

    assert len(dataset) == 240
    assert dataset.attrs["timeframe"] == "1h"
    assert set(results) == {"grid-strict", "grid"}
    ranking = rank_backtest_results(results)
    assert len(ranking) == 2
    assert ranking[0].total_pnl >= ranking[1].total_pnl


def test_generate_operational_dataset_supports_4h():
    dataset = generate_operational_dataset(days=10, initial_price=30000.0, seed=11, timeframe="4h")
    assert len(dataset) == 60
    assert dataset.attrs["timeframe"] == "4h"
    assert {"ema50", "ema200", "stoch_k", "atr14", "volume_sma20"}.issubset(dataset.columns)


def _build_triangle_dataset():
    rows = []
    for idx in range(32):
        ts = pd.Timestamp("2026-01-01") + pd.Timedelta(hours=idx)
        upper = 110 - (idx * 0.35)
        lower = 90 + (idx * 0.25)
        close = (upper + lower) / 2
        high = close + 1.0
        low = close - 1.0
        if idx in {5, 11, 17, 23, 28}:
            high = upper + 0.8
            close = upper - 0.6
        if idx in {7, 13, 19, 25, 29}:
            low = lower - 0.8
            close = lower + 0.6
        volume = 100.0
        if idx == 31:
            close = upper + 3.2
            high = close + 0.7
            low = lower + 0.4
            volume = 300.0
        rows.append({"timestamp": ts, "open": close, "high": high, "low": low, "close": close, "volume": volume})
    df = prepare_market_dataset(pd.DataFrame(rows))
    df["atr14"] = df["atr14"].bfill().ffill()
    df["volume_sma20"] = df["volume_sma20"].bfill().ffill()
    df.loc[df.index[-1], "atr14"] = 2.0
    df.loc[df.index[-1], "volume_sma20"] = 100.0
    return df


def test_resolve_symbols_accepts_csv_and_all():
    engine = SimpleNamespace(common_symbols=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"])

    assert cli._resolve_symbols(engine, "all") == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    assert cli._resolve_symbols(engine, "ETH/USDT,SOL/USDT,XRP/USDT") == ["ETH/USDT", "SOL/USDT", "XRP/USDT"]
    assert cli._resolve_symbols(engine, "eth/usdt, SOL/USDT,ETH/USDT") == ["ETH/USDT", "SOL/USDT"]


def test_resolve_margin_for_execution_mode_uses_venue_overrides():
    assert cli._resolve_margin_for_execution_mode(cli.EXECUTION_MODE_HEDGED, None, 30.0, 20.0) == pytest.approx(20.0)
    assert cli._resolve_margin_for_execution_mode(cli.EXECUTION_MODE_HEDGED, 15.0, 30.0, 20.0) == pytest.approx(15.0)
    assert cli._resolve_margin_for_execution_mode(cli.EXECUTION_MODE_NADO_ONLY, None, 30.0, 20.0) == pytest.approx(30.0)
    assert cli._resolve_margin_for_execution_mode(cli.EXECUTION_MODE_KRAKEN_ONLY, None, 30.0, 20.0) == pytest.approx(20.0)


def test_account_margin_budget_accepts_any_positive_slot_count():
    reserve, budget, per_slot = cli._resolve_account_margin_budget(
        equity_usd=1000.0,
        reserve_usd=0.0,
        reserve_pct=20.0,
        slots=5,
    )

    assert reserve == pytest.approx(200.0)
    assert budget == pytest.approx(800.0)
    assert per_slot == pytest.approx(160.0)


def test_apply_solo_partial_close_to_state_updates_remaining_nado_exposure():
    state = ManagedSetupState(
        setup_key="bollinger-mean-reversion",
        symbol="MON/USDT",
        timeframe="15m",
        side="short",
        effective_venue="nado",
        pair_state=PairState(
            symbol="MON/USDT",
            nado_product_id=20,
            kraken_symbol="",
            nado_side="short",
            kraken_side="",
            requested_notional_usd=24.0,
            effective_notional_usd=24.6204,
            nado_qty=900.0,
            kraken_qty=0.0,
            nado_entry=0.027356,
            kraken_entry=0.0,
        ),
    )
    signal = SimpleNamespace(metadata={"nado_qty": 300.0})

    cli._apply_solo_partial_close_to_state(state, signal)

    assert state.pair_state.nado_qty == pytest.approx(600.0)
    assert state.pair_state.effective_notional_usd == pytest.approx(600.0 * 0.027356)


def test_assess_setup_entry_readiness_blocks_when_balance_and_health_are_low(monkeypatch):
    class FakeHealth:
        def __init__(self, health):
            self.health = int(health * 1e18)

    class FakeEngineClient:
        def get_subaccount_info(self, _subaccount_hex):
            return SimpleNamespace(healths=[FakeHealth(1.25), FakeHealth(12.0)])

    fake_nado = SimpleNamespace(
        subaccount_hex="0xsub",
        client=SimpleNamespace(context=SimpleNamespace(engine_client=FakeEngineClient())),
        get_isolation_context=lambda: {"trade_ready": False, "trade_auth_error": "linked signer ausente"},
        get_usdt0_balance=lambda: 4.5,
    )
    fake_kraken = SimpleNamespace(
        get_trading_safety=lambda **_: {"safe": False, "label": "unsafe", "reason": "master detectada"},
        get_accounts_overview=lambda: {
            "selected": {"account": "flex"},
            "accounts": [{"name": "flex", "available_margin": 19.0}],
        },
    )
    engine = SimpleNamespace(nado=fake_nado, kraken=fake_kraken, volume_per_leg=100.0)

    monkeypatch.delenv("SETUP_ENTRY_MIN_NADO_BALANCE_RATIO", raising=False)
    monkeypatch.delenv("SETUP_ENTRY_MIN_KRAKEN_MARGIN_RATIO", raising=False)
    monkeypatch.delenv("SETUP_ENTRY_MIN_NADO_INITIAL_HEALTH", raising=False)

    snapshot = cli._assess_setup_entry_readiness(
        engine,
        managed_states=[object(), object(), object()],
        requested_notional_usd=100.0,
    )

    assert snapshot["can_open"] is False
    assert "saldo Nado insuficiente ($4.50 < $5.00)" in snapshot["blockers"]
    assert "health inicial da Nado insuficiente (1.25 < 2.00)" in snapshot["blockers"]
    assert "margem Kraken insuficiente ($19.00 < $20.00)" in snapshot["blockers"]
    assert "linked signer ausente" in snapshot["warnings"]
    assert "master detectada" in snapshot["warnings"]


def test_preflight_symbol_entry_blocks_when_nado_rounds_to_zero():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"ARB/USDT": 33}

        def _get_size_increment_x18(self, _product_id):
            return int(100 * 1e18)

        def get_market_mid_price(self, _pid):
            return 1.25

        def round_quantity_to_increment(self, _pid, qty):
            step = 100.0
            units = int(qty / step)
            return float(units * step)

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(
                market=lambda _symbol: {
                    "precision": {"amount": 1.0},
                    "limits": {"amount": {"min": 1.0}},
                }
            )

        def get_symbol_to_product_map(self, product_filter=None):
            return {"ARB/USDT": "ARB/USD:USD"}

        def get_market_mid_price(self, _symbol):
            return 1.24

        def round_quantity_to_increment(self, _symbol, qty):
            step = 1.0
            units = int(qty / step)
            rounded = float(units * step)
            return rounded if rounded >= 1.0 else 0.0

    engine = DeltaNeutralEngine(nado=FakeNado(), kraken=FakeKraken(), volume_per_leg_usd=100.0)

    can_execute, reason = cli._preflight_symbol_entry(
        engine,
        symbol="ARB/USDT",
        requested_notional_usd=100.0,
    )

    assert can_execute is False
    assert reason == "nocional abaixo do minimo executavel | Nado ~$125.00 | Kraken ~$1.24 | comum ~$125.00"


def test_single_venue_order_plan_waits_for_exchange_liquidation_after_entry():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"SOL/USDT": 5}

        def _get_size_increment_x18(self, _product_id):
            return int(0.1 * 1e18)

        def get_market_mid_price(self, _pid):
            return 100.0

        def round_quantity_to_increment(self, _pid, qty):
            return float(int(qty * 10) / 10)

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(
                market=lambda _symbol: {
                    "precision": {"amount": 0.1},
                    "limits": {"amount": {"min": 0.1}},
                }
            )

        def get_symbol_to_product_map(self, product_filter=None):
            return {"SOL/USDT": "SOL/USD:USD"}

        def get_market_mid_price(self, _symbol):
            return 100.0

        def round_quantity_to_increment(self, _symbol, qty):
            return float(int(qty * 10) / 10)

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=50.0)
    signal = SimpleNamespace(side="long", stop_price=91.0, take_profit=112.0)

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="hybrid-15m",
        symbol="SOL/USDT",
        venue="kraken",
        signal=signal,
        notional_usd=50.0,
        margin_mode="isolated",
        leverage=10.0,
        min_liquidation_buffer_pct=20.0,
    )

    assert plan.can_execute is True
    assert plan.blocked_reason == ""
    assert plan.liquidation_price == 0.0
    assert plan.liquidation_buffer_pct == 999.0


def test_single_venue_order_plan_blocks_invalid_nado_sentinel_price():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"AXS/USDT": 66}

        def _get_size_increment_x18(self, _product_id):
            return int(1e18)

        def get_market_mid_price(self, _pid):
            return 8.507059173023462e19

        def round_quantity_to_increment(self, _pid, _qty):
            raise AssertionError("nao deve arredondar quantidade com preco invalido")

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(
                market=lambda _symbol: {
                    "precision": {"amount": 1.0},
                    "limits": {"amount": {"min": 1.0}},
                }
            )

        def get_symbol_to_product_map(self, product_filter=None):
            return {"AXS/USDT": "AXS/USD:USD"}

        def get_market_mid_price(self, _symbol):
            return 1.45

        def round_quantity_to_increment(self, _symbol, qty):
            return float(int(qty))

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=25.0)
    signal = SimpleNamespace(side="long", stop_price=1.38, take_profit=1.58)

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="grid",
        symbol="AXS/USDT",
        venue="nado",
        signal=signal,
        notional_usd=25.0,
        margin_mode="isolated",
        leverage=5.0,
        min_liquidation_buffer_pct=15.0,
    )

    assert plan.can_execute is False
    assert plan.quantity == 0.0
    assert "preco invalido em nado" in plan.blocked_reason


def test_plan_notice_stop_price_prefers_rebased_setup_stop_over_global_preset():
    plan = cli.SetupOrderPlan(
        setup_key="institutional-strict",
        symbol="CFG/USDT",
        execution_mode=cli.EXECUTION_MODE_KRAKEN_ONLY,
        venue="kraken",
        margin_mode="isolated",
        leverage=5.0,
        requested_notional_usd=10.0,
        effective_notional_usd=10.0,
        requested_margin_usd=2.0,
        sizing_source="notional",
        quantity=100.0,
        entry_price=100.0,
        stop_price=80.0,
        take_profit=106.0,
        liquidation_price=0.0,
        liquidation_buffer_pct=999.0,
        can_execute=True,
    )
    signal = SimpleNamespace(side="long", reference_entry_price=90.0, stop_price=88.2)

    stop_price = cli._plan_notice_stop_price(
        plan=plan,
        signal=signal,
        entry_price=plan.entry_price,
        side=signal.side,
        stop_loss_pct=0.20,
    )

    assert stop_price == pytest.approx(98.0)


def test_single_venue_order_plan_allows_nado_partial_tp_below_native_minimum():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"AAVE/USDT": 26}

        def _get_size_increment_x18(self, _product_id):
            return int(0.01 * 1e18)

        def get_market_mid_price(self, _pid):
            return 100.0

        def round_quantity_to_increment(self, _pid, qty):
            return float(int(qty * 100) / 100)

        def get_min_order_notional_usd(self, _pid):
            return 100.0

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(
                market=lambda _symbol: {
                    "precision": {"amount": 0.01},
                    "limits": {"amount": {"min": 0.01}},
                }
            )

        def get_symbol_to_product_map(self, product_filter=None):
            return {"AAVE/USDT": "AAVE/USD:USD"}

        def get_market_mid_price(self, _symbol):
            return 100.0

        def round_quantity_to_increment(self, _symbol, qty):
            return float(int(qty * 100) / 100)

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=125.0)
    signal = SimpleNamespace(
        side="long",
        stop_price=95.0,
        take_profit=115.0,
        take_profit_targets=[105.0, 110.0, 115.0],
        target_weights=[1 / 3, 1 / 3, 1 / 3],
    )

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="institutional-strict",
        symbol="AAVE/USDT",
        venue="nado",
        signal=signal,
        notional_usd=125.0,
        margin_mode="isolated",
        leverage=5.0,
        min_liquidation_buffer_pct=15.0,
    )

    assert plan.can_execute is True
    assert plan.blocked_reason == ""
    assert plan.effective_notional_usd == pytest.approx(125.0)


def test_single_venue_order_plan_uses_margin_times_leverage_for_notional():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"AAVE/USDT": 26}

        def _get_size_increment_x18(self, _product_id):
            return int(0.01 * 1e18)

        def get_market_mid_price(self, _pid):
            return 100.0

        def round_quantity_to_increment(self, _pid, qty):
            return float(int(qty * 100) / 100)

        def get_min_order_notional_usd(self, _pid):
            return 100.0

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(market=lambda _symbol: {"limits": {"amount": {"min": 0.01}}})

        def get_symbol_to_product_map(self, product_filter=None):
            return {"AAVE/USDT": "AAVE/USD:USD"}

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=25.0)
    signal = SimpleNamespace(side="long", stop_price=95.0, take_profit=115.0, take_profit_targets=[], target_weights=[])

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="institutional-strict",
        symbol="AAVE/USDT",
        venue="nado",
        signal=signal,
        notional_usd=None,
        margin_usd=20.0,
        margin_mode="isolated",
        leverage=5.0,
        min_liquidation_buffer_pct=15.0,
    )

    assert plan.can_execute is True
    assert plan.requested_margin_usd == pytest.approx(20.0)
    assert plan.requested_notional_usd == pytest.approx(100.0)
    assert plan.effective_notional_usd == pytest.approx(100.0)
    assert plan.sizing_source == "margin_x_leverage"


def test_single_venue_order_plan_blocks_only_below_asset_entry_minimum():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"AAVE/USDT": 26}

        def _get_size_increment_x18(self, _product_id):
            return int(0.01 * 1e18)

        def get_market_mid_price(self, _pid):
            return 100.0

        def round_quantity_to_increment(self, _pid, qty):
            return float(int(qty * 100) / 100)

        def get_min_order_notional_usd(self, _pid):
            return 100.0

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(market=lambda _symbol: {"limits": {"amount": {"min": 0.01}}})

        def get_symbol_to_product_map(self, product_filter=None):
            return {"AAVE/USDT": "AAVE/USD:USD"}

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=25.0)
    signal = SimpleNamespace(side="long", stop_price=95.0, take_profit=115.0, take_profit_targets=[], target_weights=[])

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="institutional-strict",
        symbol="AAVE/USDT",
        venue="nado",
        signal=signal,
        notional_usd=None,
        margin_usd=5.0,
        margin_mode="isolated",
        leverage=5.0,
        min_liquidation_buffer_pct=15.0,
    )

    assert plan.can_execute is False
    assert "notional abaixo do minimo do ativo" in plan.blocked_reason
    assert "$25.00 < $100.00" in plan.blocked_reason


def test_single_venue_order_plan_allows_explicit_nado_min_notional_override(monkeypatch):
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"AAVE/USDT": 26}

        def _get_size_increment_x18(self, _product_id):
            return int(0.01 * 1e18)

        def get_market_mid_price(self, _pid):
            return 100.0

        def round_quantity_to_increment(self, _pid, qty):
            return float(int(qty * 100) / 100)

        def get_min_order_notional_usd(self, _pid):
            return 100.0

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.client = SimpleNamespace(market=lambda _symbol: {"limits": {"amount": {"min": 0.01}}})

        def get_symbol_to_product_map(self, product_filter=None):
            return {"AAVE/USDT": "AAVE/USD:USD"}

    monkeypatch.setenv("NADO_MIN_ORDER_NOTIONAL_USD", "10")
    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=25.0)
    signal = SimpleNamespace(side="long", stop_price=95.0, take_profit=115.0, take_profit_targets=[], target_weights=[])

    plan = cli._build_single_venue_order_plan(
        engine,
        setup_key="institutional-strict",
        symbol="AAVE/USDT",
        venue="nado",
        signal=signal,
        notional_usd=None,
        margin_usd=5.0,
        margin_mode="isolated",
        leverage=5.0,
        min_liquidation_buffer_pct=15.0,
    )

    assert plan.can_execute is True
    assert plan.effective_notional_usd == pytest.approx(25.0)


def test_target_levels_for_nado_only_use_nado_entry_and_quantities():
    engine = SimpleNamespace(
        nado=SimpleNamespace(round_quantity_to_increment=lambda _pid, qty: float(int(qty))),
        kraken=SimpleNamespace(round_quantity_to_increment=lambda _symbol, qty: float(int(qty))),
    )
    pair_state = PairState(
        symbol="JUP/USDT",
        nado_product_id=86,
        kraken_symbol="JUP/USD:USD",
        nado_side="long",
        kraken_side="",
        requested_notional_usd=25.0,
        effective_notional_usd=24.0,
        nado_qty=120.0,
        kraken_qty=0.0,
        nado_entry=0.194475,
        kraken_entry=0.0,
    )

    levels = cli._build_target_levels(
        engine,
        pair_state,
        reference_entry_price=0.193,
        signal_targets=[0.195, 0.197, 0.199],
        target_weights=[1 / 3, 1 / 3, 1 / 3],
        effective_venue="nado",
    )

    assert [level["label"] for level in levels] == ["TP1", "TP2", "TP3"]
    assert all(level["price"] > 0 for level in levels)
    assert [level["nado_qty"] for level in levels] == [40.0, 40.0, 40.0]
    assert [level["kraken_qty"] for level in levels] == [0.0, 0.0, 0.0]


def test_target_levels_put_rounding_remainder_on_last_nado_target():
    from decimal import Decimal, ROUND_DOWN

    def round_to_cent(_pid, qty):
        inc = Decimal("0.01")
        rounded = (Decimal(str(qty)) / inc).to_integral_value(rounding=ROUND_DOWN) * inc
        return float(rounded)

    engine = SimpleNamespace(
        nado=SimpleNamespace(round_quantity_to_increment=round_to_cent),
        kraken=SimpleNamespace(round_quantity_to_increment=lambda _symbol, qty: qty),
    )
    pair_state = PairState(
        symbol="AAVE/USDT",
        nado_product_id=26,
        kraken_symbol="AAVE/USD:USD",
        nado_side="long",
        kraken_side="",
        requested_notional_usd=25.0,
        effective_notional_usd=24.0,
        nado_qty=0.25,
        kraken_qty=0.0,
        nado_entry=97.21,
        kraken_entry=0.0,
    )

    levels = cli._build_target_levels(
        engine,
        pair_state,
        reference_entry_price=97.21,
        signal_targets=[98.1821, 99.1542, 100.1263],
        target_weights=[1 / 3, 1 / 3, 1 / 3],
        effective_venue="nado",
    )

    assert [level["nado_qty"] for level in levels] == [0.08, 0.08, 0.09]
    assert sum(level["nado_qty"] for level in levels) == pytest.approx(0.25)


def test_attach_solo_protective_orders_places_nado_stop_and_three_tps():
    calls: list[tuple] = []

    class FakeNado:
        def get_perp_position_size(self, _product_id):
            return 120.0

        def round_quantity_to_increment(self, _product_id, qty):
            return float(int(qty))

        def place_stop_loss(self, product_id, quantity, trigger_price, is_long=True, slippage_pct=0.01):
            calls.append(("sl", product_id, quantity, trigger_price, is_long))
            return {"ok": True}

        def place_take_profit(self, product_id, quantity, trigger_price, is_long=True, slippage_pct=0.01):
            calls.append(("tp", product_id, quantity, trigger_price, is_long))
            return {"ok": True}

    engine = SimpleNamespace(nado=FakeNado(), protective_stop_trigger_slippage_pct=0.01)
    state = ManagedSetupState(
        setup_key="institutional-strict",
        symbol="JUP/USDT",
        timeframe="1h",
        side="long",
        pair_state=PairState(
            symbol="JUP/USDT",
            nado_product_id=86,
            kraken_symbol="JUP/USD:USD",
            nado_side="long",
            kraken_side="",
            requested_notional_usd=25.0,
            effective_notional_usd=24.0,
            nado_qty=120.0,
            kraken_qty=0.0,
            nado_entry=0.194475,
            kraken_entry=0.0,
        ),
        reference_entry_price=0.194475,
        stop_price=0.189613125,
        take_profit=0.20030925,
        execution_mode="nado_only",
        effective_venue="nado",
        margin_mode="isolated",
        leverage=5.0,
        metadata={
            "target_levels": [
                {"label": "TP1", "price": 0.19642, "nado_qty": 40.0, "kraken_qty": 0.0},
                {"label": "TP2", "price": 0.19836, "nado_qty": 40.0, "kraken_qty": 0.0},
                {"label": "TP3", "price": 0.20030, "nado_qty": 40.0, "kraken_qty": 0.0},
            ]
        },
    )

    assert cli._attach_solo_protective_orders(engine, state) is True
    assert calls[0] == ("sl", 86, 120.0, 0.189613125, True)
    assert [call[0] for call in calls[1:]] == ["tp", "tp", "tp"]
    assert [call[2] for call in calls[1:]] == [40.0, 40.0, 40.0]


def test_attach_solo_protective_orders_keeps_managed_tp_when_native_partial_below_minimum():
    calls: list[tuple] = []

    class FakeNado:
        def get_perp_position_size(self, _product_id):
            return 1.2

        def round_quantity_to_increment(self, _product_id, qty):
            return float(int(qty * 100) / 100)

        def get_min_order_notional_usd(self, _product_id):
            return 100.0

        def place_stop_loss(self, product_id, quantity, trigger_price, is_long=True, slippage_pct=0.01):
            calls.append(("sl", product_id, quantity, trigger_price, is_long))
            return {"ok": True}

        def place_take_profit(self, product_id, quantity, trigger_price, is_long=True, slippage_pct=0.01):
            calls.append(("tp", product_id, quantity, trigger_price, is_long))
            return {"ok": True}

    engine = SimpleNamespace(nado=FakeNado(), protective_stop_trigger_slippage_pct=0.01)
    state = ManagedSetupState(
        setup_key="institutional-strict",
        symbol="AAVE/USDT",
        timeframe="1h",
        side="long",
        pair_state=PairState(
            symbol="AAVE/USDT",
            nado_product_id=26,
            kraken_symbol="AAVE/USD:USD",
            nado_side="long",
            kraken_side="",
            requested_notional_usd=120.0,
            effective_notional_usd=120.0,
            nado_qty=1.2,
            kraken_qty=0.0,
            nado_entry=100.0,
            kraken_entry=0.0,
        ),
        reference_entry_price=100.0,
        stop_price=95.0,
        take_profit=130.0,
        execution_mode="nado_only",
        effective_venue="nado",
        margin_mode="isolated",
        leverage=5.0,
        metadata={
            "target_levels": [
                {"label": "TP1", "price": 110.0, "nado_qty": 0.4, "kraken_qty": 0.0},
                {"label": "TP2", "price": 120.0, "nado_qty": 0.4, "kraken_qty": 0.0},
                {"label": "TP3", "price": 130.0, "nado_qty": 0.4, "kraken_qty": 0.0},
            ]
        },
    )

    assert cli._attach_solo_protective_orders(engine, state) is False
    assert calls == [("sl", 26, 1.2, 95.0, True)]
    assert state.metadata["nado_managed_tp_policy"] == "first_target_full"
    assert len(state.metadata["target_levels"]) == 1
    assert state.metadata["target_levels"][0]["native_skipped_reason"] == "below_min_notional_managed_full"
    assert state.metadata["target_levels"][0]["nado_qty"] == pytest.approx(1.2)


def test_open_single_venue_kraken_rejects_unconfirmed_isolated_mode():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"SOL/USDT": 5}

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.risk_calls = []
            self.orders = []
            self.closed = []

        def get_symbol_to_product_map(self, product_filter=None):
            return {"SOL/USDT": "SOL/USD:USD"}

        def get_position(self, symbol):
            return KrakenPosition(
                symbol=symbol,
                side="long" if self.orders else "flat",
                size=0.5 if self.orders else 0.0,
                entry_price=100.0,
                mark_price=100.0,
                unrealized_pnl=0.0,
                leverage=5.0,
                margin_mode="cross" if self.orders else "",
            )

        def configure_futures_risk_context(self, symbol, *, leverage=None, margin_mode=None):
            self.risk_calls.append({"symbol": symbol, "leverage": leverage, "margin_mode": margin_mode})
            return {}

        def place_market_order(self, *args, **kwargs):
            self.orders.append({"args": args, "kwargs": kwargs})
            return {"id": "order"}

        def close_position(self, symbol):
            self.closed.append(symbol)

    engine = DeltaNeutralEngine(FakeNado(), FakeKraken(), volume_per_leg_usd=50.0)
    plan = cli.SetupOrderPlan(
        setup_key="hybrid-15m",
        symbol="SOL/USDT",
        execution_mode="kraken_only",
        venue="kraken",
        margin_mode="isolated",
        leverage=5.0,
        requested_notional_usd=50.0,
        effective_notional_usd=50.0,
        requested_margin_usd=0.0,
        sizing_source="notional",
        quantity=0.5,
        entry_price=100.0,
        stop_price=98.0,
        take_profit=106.0,
        liquidation_price=80.0,
        liquidation_buffer_pct=90.0,
        can_execute=True,
        kraken_symbol="SOL/USD:USD",
    )
    signal = SimpleNamespace(side="long")

    pair_state = cli._open_single_venue_setup(engine, plan=plan, signal=signal)

    assert pair_state is not None
    assert pair_state.kraken_margin_mode == "cross"
    assert engine.kraken.closed == []


def test_cmd_open_hedged_without_margin_keeps_notional(monkeypatch):
    captured = {}

    class FakeKraken:
        def get_isolation_context(self):
            return {"account": "flex", "api_fingerprint": "fp", "subaccount_mode": "dedicated_api"}

        def get_trading_safety(self, **_kwargs):
            return {"safe": True, "label": "safe", "reason": ""}

        def validate_entry_subaccount_rule(self, **_kwargs):
            captured["validated_kraken"] = True

    class FakeNado:
        def get_isolation_context(self):
            return {"subaccount_name": "default_1", "signer_mode": "linked", "trade_ready": True}

    class FakeEngine:
        def __init__(self):
            self.nado = FakeNado()
            self.kraken = FakeKraken()
            self.kraken_require_subaccount = True
            self.kraken_api_is_subaccount = True

        def _assert_nado_trade_ready(self):
            captured["validated_nado"] = True

        def open_pair(self, symbol, **kwargs):
            captured["symbol"] = symbol
            captured["open_kwargs"] = kwargs
            return PairState(
                symbol=symbol,
                nado_product_id=4,
                kraken_symbol="ETH/USD:USD",
                nado_side="long",
                kraken_side="short",
                requested_notional_usd=float(kwargs["notional_usd"]),
                effective_notional_usd=float(kwargs["notional_usd"]),
                nado_qty=0.01,
                kraken_qty=0.01,
                nado_entry=2500.0,
                kraken_entry=2501.0,
            )

    monkeypatch.setattr(cli, "build_engine", lambda **_kwargs: FakeEngine())
    monkeypatch.setattr(cli, "save_state", lambda state: captured.setdefault("saved", state))
    args = SimpleNamespace(
        symbol="eth/usdt",
        side="long",
        execution_mode="hedged",
        margin_mode=None,
        nado_margin_mode=None,
        kraken_margin_mode=None,
        leverage=None,
        nado_leverage=None,
        kraken_leverage=None,
        margin_usd=None,
        nado_margin_usd=None,
        kraken_margin_usd=None,
        notional=50.0,
    )

    cli.cmd_open(args)

    assert captured["validated_nado"] is True
    assert captured["validated_kraken"] is True
    assert captured["symbol"] == "ETH/USDT"
    assert captured["open_kwargs"]["notional_usd"] == pytest.approx(50.0)
    assert captured["saved"].requested_notional_usd == pytest.approx(50.0)


def test_process_setup_live_states_removes_manual_closed_nado_solo_state(monkeypatch):
    class FakeNado:
        def get_perp_position_size(self, _product_id):
            return 0.0

    engine = SimpleNamespace(nado=FakeNado())
    state = ManagedSetupState(
        setup_key="institutional-strict",
        symbol="PENGU/USDT",
        timeframe="1h",
        side="long",
        pair_state=PairState(
            symbol="PENGU/USDT",
            nado_product_id=40,
            kraken_symbol="PENGU/USD:USD",
            nado_side="long",
            kraken_side="",
            requested_notional_usd=25.0,
            effective_notional_usd=24.0,
            nado_qty=2400.0,
            kraken_qty=0.0,
            nado_entry=0.01,
            kraken_entry=0.0,
            execution_mode="nado_only",
            effective_venue="nado",
        ),
        execution_mode="nado_only",
        effective_venue="nado",
    )

    monkeypatch.setattr(cli, "_fetch_setup_market_dataset", lambda *_, **__: pytest.fail("nao deve buscar candles sem posicao live"))

    assert cli._process_setup_live_states(engine, [state], dry_run=False) == []


def test_get_setup_execution_config_targets_only_scalps():
    scalp = get_setup_execution_config("hybrid-15m")
    bollinger = get_setup_execution_config("bollinger-mean-reversion")
    institutional_strict = get_setup_execution_config("institutional-strict")

    assert scalp.kraken_leverage == pytest.approx(5.0)
    assert scalp.kraken_margin_mode == "cross"
    assert bollinger.kraken_leverage == pytest.approx(5.0)
    assert bollinger.kraken_margin_mode == "cross"
    assert institutional_strict.kraken_leverage == pytest.approx(0.0)
    assert institutional_strict.kraken_margin_mode == "cross"
    assert institutional_strict.allowed_execution_modes == ("hedged", "kraken_only", "nado_only")
    assert institutional_strict.liquidation_buffer_pct_min == pytest.approx(15.0)


def test_scan_setup_entries_locks_base_and_uses_setup_priority(monkeypatch):
    monkeypatch.setenv("SETUP_LIVE_ALLOWLIST_MODE", "open")
    monkeypatch.setattr(cli, "load_setup_live_states", lambda: [])
    df = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-01T00:00:00"), "close": 100.0}])
    fetched: list[tuple[str, str]] = []

    def fake_fetch(_eng, symbol, timeframe):
        fetched.append((symbol, timeframe))
        return df

    def fake_evaluate(setup_key, _df, **_kwargs):
        return SimpleNamespace(
            timeframe=SETUP_CATALOG[setup_key].timeframe,
            side="long",
            reason=f"{setup_key} signal",
            stop_price=99.0,
            take_profit=103.0,
            take_profit_targets=[],
            target_weights=[],
            close_after_bars=1,
            metadata={},
            reference_entry_price=100.0,
        )

    monkeypatch.setattr(cli, "_fetch_setup_market_dataset", fake_fetch)
    monkeypatch.setattr(cli, "_build_setup_runtime_context", lambda *_, **__: {})
    monkeypatch.setattr(cli, "evaluate_setup_entry", fake_evaluate)

    entries = cli._scan_setup_entries(
        SimpleNamespace(),
        setup_keys=["institutional-strict", "grid-strict"],
        symbols=["BTC/USDT", "BTC/USDC"],
        hybrid_profile="moderado",
    )

    assert [(setup_key, symbol) for setup_key, symbol, _df, _signal in entries] == [
        ("institutional-strict", "BTC/USDT")
    ]
    assert fetched == [("BTC/USDT", "1h")]


def test_execute_setup_entries_locks_base_to_one_attempt_by_priority(monkeypatch):
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_ENABLED", "false")
    calls: list[tuple[str, str]] = []
    nado_symbols = {"BTC/USDT": 1, "BTC/USDC": 2}
    kraken_symbols = {"BTC/USDT": "BTC/USD:USD", "BTC/USDC": "BTC/USDC:USDC"}

    class FakeVenue:
        def get_market_mid_price(self, _symbol):
            return 100.0

        def round_quantity_to_increment(self, _symbol, quantity):
            return quantity

    def fake_open_pair(symbol, nado_side="long", notional_usd=None, **_kwargs):
        calls.append((symbol, nado_side))
        return PairState(
            symbol=symbol,
            nado_product_id=nado_symbols[symbol],
            kraken_symbol=kraken_symbols[symbol],
            nado_side=nado_side,
            kraken_side="short",
            requested_notional_usd=float(notional_usd or 30.0),
            effective_notional_usd=float(notional_usd or 30.0),
            nado_qty=0.3,
            kraken_qty=0.3,
            nado_entry=100.0,
            kraken_entry=100.0,
        )

    engine = SimpleNamespace(
        open_pair=fake_open_pair,
        nado=FakeVenue(),
        kraken=FakeVenue(),
        _nado_symbol_map=nado_symbols,
        _kraken_symbol_map=kraken_symbols,
        volume_per_leg=30.0,
    )
    df = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-01T00:00:00"), "close": 100.0}])
    signal = SimpleNamespace(
        timeframe="1h",
        side="long",
        reason="entry signal",
        stop_price=99.0,
        take_profit=103.0,
        take_profit_targets=[101.0, 102.0, 103.0],
        target_weights=[1 / 3, 1 / 3, 1 / 3],
        close_after_bars=8,
        metadata={},
        reference_entry_price=100.0,
    )

    states = cli._execute_setup_entries(
        engine,
        [("grid-strict", "BTC/USDC", df, signal), ("institutional-strict", "BTC/USDT", df, signal)],
        dry_run=False,
        notional_usd=30.0,
        hybrid_profile="moderado",
        setup_priority=["institutional-strict", "grid-strict"],
    )

    assert calls == [("BTC/USDT", "long")]
    assert len(states) == 1
    assert states[0].setup_key == "institutional-strict"
    assert states[0].symbol == "BTC/USDT"


def test_execute_setup_entries_preserves_default_engine_protection_for_delta_neutral():
    calls: list[dict[str, object]] = []

    class FakeVenue:
        def get_market_mid_price(self, _symbol):
            return 100.0

        def round_quantity_to_increment(self, _symbol, quantity):
            return quantity

    pair_state = PairState(
        symbol="ETH/USDT",
        nado_product_id=4,
        kraken_symbol="ETH/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=20.0,
        nado_qty=0.1,
        kraken_qty=0.1,
        nado_entry=100.0,
        kraken_entry=100.0,
    )

    def fake_open_pair(
        symbol,
        nado_side="long",
        notional_usd=None,
        attach_default_protective_orders=True,
        kraken_leverage=None,
        kraken_margin_mode=None,
    ):
        calls.append(
            {
                "attach_default_protective_orders": bool(attach_default_protective_orders),
                "kraken_leverage": kraken_leverage,
                "kraken_margin_mode": kraken_margin_mode,
            }
        )
        return pair_state

    engine = SimpleNamespace(
        open_pair=fake_open_pair,
        nado=FakeVenue(),
        kraken=FakeVenue(),
        _nado_symbol_map={"ETH/USDT": 4},
        _kraken_symbol_map={"ETH/USDT": "ETH/USD:USD"},
        volume_per_leg=20.0,
    )
    df = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-01T00:00:00")}])
    signal = SimpleNamespace(
        timeframe="1h",
        side="long",
        reason="delta entry",
        stop_price=0.0,
        take_profit=0.0,
        take_profit_targets=[],
        target_weights=[],
        close_after_bars=1,
        metadata={},
        reference_entry_price=0.0,
    )

    states = cli._execute_setup_entries(
        engine,
        [("delta-neutral", "ETH/USDT", df, signal)],
        dry_run=False,
        notional_usd=20.0,
        hybrid_profile="moderado",
    )

    assert calls == [
        {
            "attach_default_protective_orders": True,
            "kraken_leverage": pytest.approx(5.0),
            "kraken_margin_mode": "cross",
        }
    ]
    assert states[0].stop_price == 0.0
    assert states[0].take_profit == 0.0
    assert states[0].metadata["execution_mode"] == "hedged"
    assert states[0].metadata["effective_venue"] == "hedged"


def test_execute_setup_entries_uses_setup_managed_exit_for_directional_setups():
    calls: list[dict[str, object]] = []

    class FakeVenue:
        def get_market_mid_price(self, _symbol):
            return 100.0

        def round_quantity_to_increment(self, _symbol, quantity):
            return quantity

    pair_state = PairState(
        symbol="SOL/USDT",
        nado_product_id=5,
        kraken_symbol="SOL/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=30.0,
        effective_notional_usd=30.0,
        nado_qty=0.3,
        kraken_qty=0.3,
        nado_entry=100.0,
        kraken_entry=100.0,
    )

    def fake_open_pair(
        symbol,
        nado_side="long",
        notional_usd=None,
        attach_default_protective_orders=True,
        kraken_leverage=None,
        kraken_margin_mode=None,
    ):
        calls.append(
            {
                "attach_default_protective_orders": bool(attach_default_protective_orders),
                "kraken_leverage": kraken_leverage,
                "kraken_margin_mode": kraken_margin_mode,
            }
        )
        return pair_state

    engine = SimpleNamespace(
        open_pair=fake_open_pair,
        nado=FakeVenue(),
        kraken=FakeVenue(),
        _nado_symbol_map={"SOL/USDT": 5},
        _kraken_symbol_map={"SOL/USDT": "SOL/USD:USD"},
        volume_per_leg=30.0,
    )
    df = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-01T00:00:00")}])
    signal = SimpleNamespace(
        timeframe="15m",
        side="long",
        reason="hybrid scalp",
        stop_price=99.0,
        take_profit=103.0,
        take_profit_targets=[101.0, 102.0, 103.0],
        target_weights=[1 / 3, 1 / 3, 1 / 3],
        close_after_bars=8,
        metadata={},
        reference_entry_price=100.0,
    )

    states = cli._execute_setup_entries(
        engine,
        [("grid-strict", "SOL/USDT", df, signal)],
        dry_run=False,
        notional_usd=30.0,
        hybrid_profile="moderado",
    )

    assert calls == [
        {
            "attach_default_protective_orders": False,
            "kraken_leverage": pytest.approx(10.0),
            "kraken_margin_mode": "cross",
        }
    ]
    assert states[0].stop_price == pytest.approx(99.0)
    assert states[0].take_profit == pytest.approx(103.0)
    assert len(states[0].metadata["target_levels"]) == 3


def test_operational_backtests_support_hybrid_default_timeframe():
    dataset, results = run_operational_backtests(
        setup_keys=["hybrid"],
        days=10,
        initial_price=30000.0,
        seed=13,
    )

    assert dataset.attrs["timeframe"] == "4h"
    assert dataset.attrs["per_setup_timeframes"]["hybrid"] == "4h"
    assert set(results) == {"hybrid"}
    assert results["hybrid"].key == "hybrid"
    assert results["hybrid"].setup == "HYBRID Strategy"
    assert "profile=moderate" in results["hybrid"].notes


def test_operational_backtests_support_hybrid_15m_timeframe():
    dataset, results = run_operational_backtests(
        setup_keys=["hybrid-15m"],
        days=10,
        initial_price=30000.0,
        seed=15,
        hybrid_profile="moderado",
    )

    assert dataset.attrs["timeframe"] == "15m"
    assert dataset.attrs["per_setup_timeframes"]["hybrid-15m"] == "15m"
    assert set(results) == {"hybrid-15m"}
    assert results["hybrid-15m"].key == "hybrid-15m"
    assert results["hybrid-15m"].setup == "HYBRID 15m Scalp"
    assert "Hybrid 15m scalp" in results["hybrid-15m"].notes


def test_operational_backtests_support_new_setups():
    dataset, results = run_operational_backtests(
        setup_keys=["bollinger-mean-reversion", "low-stoch-storm", "funding-arb"],
        days=30,
        initial_price=30000.0,
        seed=17,
    )

    assert dataset.attrs["per_setup_timeframes"]["bollinger-mean-reversion"] == "15m"
    assert dataset.attrs["per_setup_timeframes"]["low-stoch-storm"] == "4h"
    assert dataset.attrs["per_setup_timeframes"]["funding-arb"] == "1h"
    assert set(results) == {"bollinger-mean-reversion", "low-stoch-storm", "funding-arb"}


def test_directional_setup_allowlists_are_backtest_calibrated():
    assert cli.SETUP_LIVE_DEFAULT_ALLOWLISTS["low-stoch-storm"] == (
        "BTC/USDT",
        "BTC/USDC",
        "ETH/USDT",
        "ETH/USDC",
        "SOL/USDT",
        "SOL/USDC",
        "XRP/USDT",
        "XRP/USDC",
    )
    assert cli.SETUP_LIVE_DEFAULT_ALLOWLISTS["divergence-and-volume-4h"] == (
        "ETH/USDT",
        "ETH/USDC",
        "XMR/USDT",
        "XMR/USDC",
    )
    assert cli.DIVERGENCE_AND_VOLUME_DEFAULT_ALLOWED_SYMBOLS == [
        "ETH/USDT",
        "ETH/USDC",
        "XMR/USDT",
        "XMR/USDC",
    ]
    assert DEFAULT_LOW_STOCH_REAL_SYMBOLS == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    assert DEFAULT_DIVERGENCE_AND_VOLUME_REAL_SYMBOLS == ["ETH/USDT", "XMR/USDT"]


def test_divergence_volume_operational_backtests_keep_variant_labels():
    _, results = run_operational_backtests(
        setup_keys=["divergence-and-volume-15m", "divergence-and-volume-1h", "divergence-and-volume-4h"],
        days=30,
        initial_price=30000.0,
        seed=19,
    )

    assert results["divergence-and-volume-15m"].setup == "Divergence and Volume 15m"
    assert results["divergence-and-volume-1h"].setup == "Divergence and Volume 1h"
    assert results["divergence-and-volume-4h"].setup == "Divergence and Volume 4h"


def test_live_setup_entry_and_exit_for_hybrid_15m():
    dataset = generate_operational_dataset(days=8, initial_price=30000.0, seed=141, timeframe="15m")
    compression_idx = dataset.index[-13:-5]
    for offset, idx in enumerate(compression_idx):
        base = 100.0 + (offset * 0.02)
        dataset.loc[idx, "open"] = base
        dataset.loc[idx, "high"] = base + 0.18
        dataset.loc[idx, "low"] = base - 0.18
        dataset.loc[idx, "close"] = base + 0.04
        dataset.loc[idx, "ema9"] = 100.15
        dataset.loc[idx, "ema21"] = 100.00
        dataset.loc[idx, "atr14"] = 1.2
        dataset.loc[idx, "volume"] = 120000.0
        dataset.loc[idx, "volume_sma20"] = 150000.0

    impulse_rows = [
        (101.00, 101.45, 100.75, 101.20),
        (101.20, 101.75, 101.00, 101.55),
        (101.50, 102.10, 101.30, 101.95),
        (101.90, 102.35, 101.65, 102.10),
    ]
    for idx, (open_price, high, low, close) in zip(dataset.index[-5:-1], impulse_rows):
        dataset.loc[idx, "open"] = open_price
        dataset.loc[idx, "high"] = high
        dataset.loc[idx, "low"] = low
        dataset.loc[idx, "close"] = close
        dataset.loc[idx, "ema9"] = 101.30
        dataset.loc[idx, "ema21"] = 100.70
        dataset.loc[idx, "macd"] = 1.3
        dataset.loc[idx, "macd_signal"] = 0.9
        dataset.loc[idx, "rsi14"] = 48.0
        dataset.loc[idx, "stoch_k"] = 45.0
        dataset.loc[idx, "atr14"] = 1.2
        dataset.loc[idx, "volume"] = 200000.0
        dataset.loc[idx, "volume_sma20"] = 150000.0

    dataset.loc[dataset.index[-1], "open"] = 100.80
    dataset.loc[dataset.index[-1], "high"] = 101.25
    dataset.loc[dataset.index[-1], "low"] = 100.95
    dataset.loc[dataset.index[-1], "ema9"] = 101.10
    dataset.loc[dataset.index[-1], "ema21"] = 100.90
    dataset.loc[dataset.index[-1], "macd"] = 1.5
    dataset.loc[dataset.index[-1], "macd_signal"] = 1.0
    dataset.loc[dataset.index[-1], "close"] = 101.05
    dataset.loc[dataset.index[-1], "rsi14"] = 40.0
    dataset.loc[dataset.index[-1], "stoch_k"] = 30.0
    dataset.loc[dataset.index[-1], "atr14"] = 1.2
    dataset.loc[dataset.index[-1], "volume"] = 210000.0
    dataset.loc[dataset.index[-1], "volume_sma20"] = 150000.0
    signal = evaluate_setup_entry("hybrid-15m", dataset, hybrid_profile="moderado")

    assert signal is not None
    assert signal.side == "long"
    assert signal.close_after_bars == 8
    assert len(signal.take_profit_targets) == 3
    assert signal.target_weights == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    risk = dataset.iloc[-1]["close"] - signal.stop_price
    reward = signal.take_profit - dataset.iloc[-1]["close"]
    assert reward / risk == pytest.approx(3.0)

    pair_state = PairState(
        symbol="SOL/USDT",
        nado_product_id=5,
        kraken_symbol="SOL/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=19.5,
        nado_qty=0.1,
        kraken_qty=0.1,
        nado_entry=100.5,
        kraken_entry=100.5,
    )
    managed = ManagedSetupState(
        setup_key="hybrid-15m",
        symbol="SOL/USDT",
        timeframe="15m",
        side="long",
        pair_state=pair_state,
        hybrid_profile="moderate",
        stop_price=signal.stop_price,
        take_profit=signal.take_profit,
        close_after_bars=signal.close_after_bars,
        opened_bar_at=str(dataset.iloc[-2]["timestamp"].isoformat()),
    )
    dataset.loc[dataset.index[-1], "rsi14"] = 60.0
    dataset.loc[dataset.index[-1], "stoch_k"] = 79.0
    exit_signal = evaluate_setup_exit(managed, dataset, live_price=101.0)

    assert exit_signal is not None
    assert "HYBRID 15m" in exit_signal.reason


def test_live_setup_exit_supports_partial_targets():
    dataset = generate_operational_dataset(days=10, initial_price=30000.0, seed=141, timeframe="15m")
    pair_state = PairState(
        symbol="SOL/USDT",
        nado_product_id=5,
        kraken_symbol="SOL/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=30.0,
        effective_notional_usd=30.0,
        nado_qty=0.3,
        kraken_qty=0.3,
        nado_entry=100.0,
        kraken_entry=100.0,
    )
    managed = ManagedSetupState(
        setup_key="hybrid-15m",
        symbol="SOL/USDT",
        timeframe="15m",
        side="long",
        pair_state=pair_state,
        hybrid_profile="moderate",
        reference_entry_price=100.0,
        stop_price=99.0,
        take_profit=103.0,
        metadata={
            "target_levels": [
                {"label": "TP1", "price": 101.0, "nado_qty": 0.1, "kraken_qty": 0.1},
                {"label": "TP2", "price": 102.0, "nado_qty": 0.1, "kraken_qty": 0.1},
                {"label": "TP3", "price": 103.0, "nado_qty": 0.1, "kraken_qty": 0.1},
            ]
        },
    )

    exit_signal = evaluate_setup_exit(managed, dataset, live_price=101.1)

    assert exit_signal is not None
    assert exit_signal.action == "partial_exit"
    assert "TP1" in exit_signal.reason
    assert exit_signal.metadata["nado_qty"] == pytest.approx(0.1)
    assert exit_signal.metadata["kraken_qty"] == pytest.approx(0.1)


def test_live_setup_entry_and_timeout_for_institutional_strict():
    dataset = generate_operational_dataset(days=10, initial_price=100.0, seed=151, timeframe="1h")
    last_idx = dataset.index[-1]
    dataset.loc[last_idx, "close"] = 100.0
    dataset.loc[last_idx, "ema9"] = 101.0
    dataset.loc[last_idx, "ema21"] = 100.6
    dataset.loc[last_idx, "ema50"] = 98.0
    dataset.loc[last_idx, "rsi"] = 60.0
    dataset.loc[last_idx, "volume"] = 130000.0
    dataset.loc[last_idx, "volume_sma20"] = 100000.0
    dataset.loc[last_idx, "macd"] = 0.35
    dataset.loc[last_idx, "macd_signal"] = 0.10
    signal = evaluate_setup_entry("institutional-strict", dataset)

    assert signal is not None
    assert signal.side == "long"
    assert signal.close_after_bars == 8
    assert signal.stop_price == pytest.approx(98.0)
    assert signal.take_profit == pytest.approx(106.0)
    assert signal.take_profit_targets == pytest.approx([102.0, 103.0, 104.0, 106.0])
    assert signal.target_weights == pytest.approx([0.25, 0.25, 0.25, 0.25])

    pair_state = PairState(
        symbol="ETH/USDT",
        nado_product_id=4,
        kraken_symbol="ETH/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=20.0,
        nado_qty=0.2,
        kraken_qty=0.2,
        nado_entry=100.0,
        kraken_entry=100.0,
    )
    managed = ManagedSetupState(
        setup_key="institutional-strict",
        symbol="ETH/USDT",
        timeframe="1h",
        side="long",
        pair_state=pair_state,
        reference_entry_price=100.0,
        stop_price=signal.stop_price,
        take_profit=signal.take_profit,
        close_after_bars=signal.close_after_bars,
        opened_bar_at=str(dataset.iloc[-10]["timestamp"].isoformat()),
    )

    exit_signal = evaluate_setup_exit(managed, dataset, live_price=100.0)

    assert exit_signal is not None
    assert exit_signal.action == "exit"
    assert exit_signal.reason == "Institutional timeout"


def test_live_setup_entry_and_exit_for_bollinger_mean_reversion():
    dataset = generate_operational_dataset(days=10, initial_price=30000.0, seed=101, timeframe="15m")
    dataset.loc[dataset.index[-1], "close"] = 90.0
    dataset.loc[dataset.index[-1], "bb_lower"] = 95.0
    dataset.loc[dataset.index[-1], "bb_middle"] = 100.0
    dataset.loc[dataset.index[-1], "rsi14"] = 20.0
    dataset.loc[dataset.index[-1], "atr14"] = 10.0
    dataset.loc[dataset.index[-1], "volume_ratio"] = 1.1
    signal = evaluate_setup_entry("bollinger-mean-reversion", dataset)

    assert signal is not None
    assert signal.side == "long"
    assert signal.close_after_bars == 16

    pair_state = PairState(
        symbol="ETH/USDT",
        nado_product_id=4,
        kraken_symbol="ETH/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=19.5,
        nado_qty=0.01,
        kraken_qty=0.01,
        nado_entry=90.0,
        kraken_entry=90.0,
    )
    managed = ManagedSetupState(
        setup_key="bollinger-mean-reversion",
        symbol="ETH/USDT",
        timeframe="15m",
        side="long",
        pair_state=pair_state,
        stop_price=signal.stop_price,
        take_profit=signal.take_profit,
        close_after_bars=signal.close_after_bars,
        opened_bar_at=str(dataset.iloc[-2]["timestamp"].isoformat()),
    )
    dataset.loc[dataset.index[-1], "close"] = 101.0
    dataset.loc[dataset.index[-1], "bb_middle"] = 100.0
    exit_signal = evaluate_setup_exit(managed, dataset, live_price=101.0)

    assert exit_signal is not None
    assert "bb_mid" in exit_signal.reason


def test_triangle_breakout_removed_from_live_catalog():
    dataset = _build_triangle_dataset()
    with pytest.raises(KeyError):
        evaluate_setup_entry("triangle-breakout", dataset)
    assert calculate_triangle_breakout_signal(dataset) is not None

def test_funding_arb_entry_and_exit():
    dataset = generate_operational_dataset(days=5, initial_price=30000.0, seed=77, timeframe="1h")
    signal = evaluate_setup_entry(
        "funding-arb",
        dataset,
        setup_context={
            "funding_rate": 0.00025,
            "funding_threshold": 0.00010,
            "neutral_exit_rate": 0.00002,
            "spread_bps": 6.0,
            "max_hold_hours": 72,
        },
    )

    assert signal is not None
    assert signal.side == "long"
    assert signal.metadata["entry_funding_rate"] == pytest.approx(0.00025)

    pair_state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="BTC/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=19.5,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=30000.0,
        kraken_entry=30000.0,
    )
    managed = ManagedSetupState(
        setup_key="funding-arb",
        symbol="BTC/USDT",
        timeframe="1h",
        side="long",
        pair_state=pair_state,
        metadata=signal.metadata,
        opened_at_ts=0.0,
    )
    exit_signal = evaluate_setup_exit(
        managed,
        dataset,
        live_price=30000.0,
        setup_context={"funding_rate": 0.0, "spread_bps": 5.0, "now_ts": 3600.0},
    )

    assert exit_signal is not None
    assert "faixa neutra" in exit_signal.reason


def test_calibration_candidate_selection_prefers_eligible_high_sharpe():
    weak = CalibrationCandidateResult(
        candidate_key="weak",
        config={"pivot_window": 2},
        eligible=True,
        rejection_reason="",
        median_sharpe_ratio=0.8,
        median_total_pnl=9.0,
        median_max_drawdown=7.0,
        median_total_trades=14.0,
        trade_qualified_symbols=4,
        successful_symbols=4,
        per_symbol={},
        errors={},
    )
    rejected = CalibrationCandidateResult(
        candidate_key="rejected",
        config={"pivot_window": 3},
        eligible=False,
        rejection_reason="drawdown cap",
        median_sharpe_ratio=2.5,
        median_total_pnl=20.0,
        median_max_drawdown=15.0,
        median_total_trades=20.0,
        trade_qualified_symbols=1,
        successful_symbols=4,
        per_symbol={},
        errors={},
    )
    strong = CalibrationCandidateResult(
        candidate_key="strong",
        config={"pivot_window": 4},
        eligible=True,
        rejection_reason="",
        median_sharpe_ratio=1.9,
        median_total_pnl=11.0,
        median_max_drawdown=6.5,
        median_total_trades=16.0,
        trade_qualified_symbols=4,
        successful_symbols=4,
        per_symbol={},
        errors={},
    )

    recommended = _select_best_calibration_candidate([weak, rejected, strong])

    assert recommended is not None
    assert recommended.candidate_key == "strong"


def test_operational_backtests_support_hybrid_profiles():
    _, conservative_results = run_operational_backtests(
        setup_keys=["hybrid"],
        days=10,
        initial_price=30000.0,
        seed=13,
        hybrid_profile="conservador",
    )
    _, degen_results = run_operational_backtests(
        setup_keys=["hybrid"],
        days=10,
        initial_price=30000.0,
        seed=13,
        hybrid_profile="degen",
    )

    assert HYBRID_PROFILE_MAP["conservative"].label in conservative_results["hybrid"].notes
    assert "profile=degen" in degen_results["hybrid"].notes


def test_hybrid_state_is_isolated_between_backtest_runs():
    first = run_operational_backtests(setup_keys=["hybrid"], days=12, initial_price=30000.0, seed=31)[1]["hybrid"]
    second = run_operational_backtests(setup_keys=["hybrid"], days=12, initial_price=30000.0, seed=31)[1]["hybrid"]

    assert first.to_dict() == second.to_dict()


def test_hybrid_short_pnl_uses_inverted_sign():
    profitable = _hybrid_directional_return("short", 100.0, 90.0)
    losing = _hybrid_directional_return("short", 100.0, 110.0)

    assert profitable == pytest.approx(0.10)
    assert losing == pytest.approx(-0.10)


def test_hybrid_cooldown_after_two_losses_waits_two_bars():
    state = _HybridRiskState(initial_equity=10000.0, current_equity=10000.0)
    triggered = state.register_close(-50.0)
    assert triggered is False
    assert state.cooldown_bars_remaining == 0

    triggered = state.register_close(-25.0)
    assert triggered is True
    assert state.cooldown_bars_remaining == 2

    state.consume_cooldown_bar()
    assert state.cooldown_bars_remaining == 1
    assert state.can_open(0) is False

    state.consume_cooldown_bar()
    assert state.cooldown_bars_remaining == 0
    assert state.can_open(0) is True


def test_hybrid_real_backtests_continue_when_one_symbol_fails(monkeypatch):
    class FakeExchange:
        id = "fake"

        def load_markets(self):
            return None

        def fetch_ohlcv(self, symbol, timeframe="4h", limit=None):
            if symbol == "FAIL/USDT":
                raise RuntimeError("boom")
            candles = []
            base = 2000.0 if symbol.startswith("ETH") else 30000.0
            for index in range(300):
                ts = 1_700_000_000_000 + (index * 14_400_000)
                close = base + index
                candles.append([ts, close - 5, close + 15, close - 15, close, 150000 + index])
            return candles

    monkeypatch.setattr("workspace.core.setups._build_ccxt_exchange", lambda exchange_id: FakeExchange())

    results, errors = run_hybrid_real_backtests(
        symbols=["BTC/USDT", "FAIL/USDT"],
        days=30,
        exchange_id="fake",
    )

    assert "BTC/USDT" in results
    assert "FAIL/USDT" in errors
    assert errors["FAIL/USDT"] == "boom"


def test_low_stoch_real_backtests_continue_when_one_symbol_fails(monkeypatch):
    class FakeExchange:
        id = "fake-low-stoch"
        markets = {}

        def load_markets(self):
            return self.markets

        def fetch_ohlcv(self, symbol, timeframe="4h", limit=None):
            if symbol == "FAIL/USDT":
                raise RuntimeError("boom-low-stoch")
            candles = []
            for index in range(320):
                ts = 1_700_000_000_000 + (index * 14_400_000)
                close = 100.0 + (index * 0.1)
                candles.append([ts, close - 0.2, close + 0.5, close - 0.5, close, 150000 + index])
            return candles

    monkeypatch.setattr("workspace.core.setups._build_ccxt_exchange", lambda exchange_id: FakeExchange())

    results, errors = run_low_stoch_real_backtests(
        symbols=["AAVE/USDT", "FAIL/USDT"],
        days=30,
        exchange_id="fake-low-stoch",
    )

    assert "AAVE/USDT" in results
    assert "FAIL/USDT" in errors
    assert errors["FAIL/USDT"] == "boom-low-stoch"


def test_funding_real_backtests_continue_when_one_symbol_fails(monkeypatch):
    class FakeExchange:
        id = "fake-funding"
        markets = {
            "BTC/USD:USD": {"base": "XBT", "swap": True},
            "ETH/USD:USD": {"base": "ETH", "swap": True},
        }

        def load_markets(self):
            return self.markets

        def fetch_funding_rate_history(self, symbol, limit=None):
            if symbol == "FAIL/USDT":
                raise RuntimeError("boom-funding")
            out = []
            for index in range(40):
                out.append(
                    {
                        "symbol": symbol,
                        "fundingRate": 0.00012 if index % 2 == 0 else 0.00003,
                        "timestamp": 1_700_000_000_000 + (index * 28_800_000),
                    }
                )
            return out

    monkeypatch.setattr("workspace.core.setups._build_ccxt_exchange", lambda exchange_id: FakeExchange())

    results, errors = run_funding_real_backtests(
        symbols=["BTC/USDT", "FAIL/USDT"],
        days=30,
        exchange_id="fake-funding",
    )

    assert "BTC/USDT" in results
    assert "FAIL/USDT" in errors
    assert errors["FAIL/USDT"] == "boom-funding"


def test_managed_setup_state_roundtrip():
    pair_state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="BTC/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=19.5,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=78000.0,
        kraken_entry=78010.0,
    )
    state = ManagedSetupState(
        setup_key="hybrid",
        symbol="BTC/USDT",
        timeframe="4h",
        side="long",
        pair_state=pair_state,
        hybrid_profile="moderate",
        stop_price=77000.0,
        take_profit=80500.0,
        close_after_bars=0,
        entry_reason="teste",
        opened_bar_at="2026-04-22T00:00:00",
        opened_at_ts=123.0,
    )

    restored = ManagedSetupState.from_dict(state.to_dict())

    assert restored.setup_key == "hybrid"
    assert restored.pair_state.symbol == "BTC/USDT"
    assert restored.take_profit == 80500.0


def test_live_setup_entry_and_exit_for_delta_neutral():
    dataset = generate_operational_dataset(days=10, initial_price=30000.0, seed=99, timeframe="1h")
    dataset.loc[dataset.index[-2], "close"] = 100.0
    dataset.loc[dataset.index[-1], "close"] = 101.0
    signal = evaluate_setup_entry("delta-neutral", dataset)

    assert signal is not None
    assert signal.action == "enter"
    assert signal.close_after_bars == 1

    pair_state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="BTC/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=19.5,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=101.0,
        kraken_entry=101.0,
    )
    managed = ManagedSetupState(
        setup_key="delta-neutral",
        symbol="BTC/USDT",
        timeframe="1h",
        side="long",
        pair_state=pair_state,
        close_after_bars=1,
        opened_bar_at=str(dataset.iloc[-2]["timestamp"].isoformat()),
    )

    exit_signal = evaluate_setup_exit(managed, dataset, live_price=101.5)
    assert exit_signal is not None
    assert exit_signal.action == "exit"


def test_cmd_backtest_hybrid_real_writes_meta_and_errors(tmp_path, monkeypatch):
    hybrid_result = run_operational_backtests(setup_keys=["hybrid"], days=10, seed=21)[1]["hybrid"]
    monkeypatch.setattr(
        cli,
        "run_hybrid_real_backtests",
        lambda symbols, days, exchange_id, profile_key: (
            {"BTC/USDT": hybrid_result},
            {"ETH/USDT": "sem dados"},
        ),
    )
    output = tmp_path / "hybrid_real.json"
    args = SimpleNamespace(
        symbols="BTC/USDT,ETH/USDT",
        days=30,
        exchange="binance",
        profile="moderado",
        output=str(output),
    )

    cli.cmd_backtest_hybrid_real(args)
    payload = cli.json.loads(output.read_text(encoding="utf-8"))

    assert payload["meta"]["exchange"] == "binance"
    assert payload["meta"]["timeframe"] == "4h"
    assert payload["meta"]["hybrid_profile"] == "moderate"
    assert payload["meta"]["symbols"] == ["BTC/USDT", "ETH/USDT"]
    assert "BTC/USDT" in payload["results"]
    assert payload["errors"]["ETH/USDT"] == "sem dados"


def test_cmd_backtest_funding_real_writes_meta_and_errors(tmp_path, monkeypatch):
    funding_result = run_operational_backtests(setup_keys=["funding-arb"], days=10, seed=23)[1]["funding-arb"]
    monkeypatch.setattr(
        cli,
        "run_funding_real_backtests",
        lambda symbols, days, exchange_id, min_rate, exit_rate, max_hold_intervals: (
            {"BTC/USDT": funding_result},
            {"ETH/USDT": "sem funding"},
        ),
    )
    output = tmp_path / "funding_real.json"
    args = SimpleNamespace(
        symbols="BTC/USDT,ETH/USDT",
        days=30,
        exchange="krakenfutures",
        min_rate=0.0001,
        exit_rate=0.00002,
        max_hold_intervals=9,
        output=str(output),
    )

    cli.cmd_backtest_funding_real(args)
    payload = cli.json.loads(output.read_text(encoding="utf-8"))

    assert payload["meta"]["exchange"] == "krakenfutures"
    assert payload["meta"]["timeframe"] == "8h"
    assert payload["meta"]["symbols"] == ["BTC/USDT", "ETH/USDT"]
    assert payload["meta"]["min_rate"] == pytest.approx(0.0001)
    assert "BTC/USDT" in payload["results"]
    assert payload["errors"]["ETH/USDT"] == "sem funding"


def test_cmd_backtest_low_stoch_real_writes_meta_and_errors(tmp_path, monkeypatch):
    low_stoch_result = run_operational_backtests(setup_keys=["low-stoch-storm"], days=10, seed=23)[1]["low-stoch-storm"]
    monkeypatch.setattr(
        cli,
        "run_low_stoch_real_backtests",
        lambda symbols, days, exchange_id: (
            {"AAVE/USDT": low_stoch_result},
            {"ETH/USDT": "sem candles"},
        ),
    )
    output = tmp_path / "low_stoch_real.json"
    args = SimpleNamespace(
        symbols="AAVE/USDT,ETH/USDT",
        days=DEFAULT_LOW_STOCH_REAL_DAYS,
        exchange="binance",
        output=str(output),
    )

    cli.cmd_backtest_low_stoch_real(args)
    payload = cli.json.loads(output.read_text(encoding="utf-8"))

    assert payload["meta"]["exchange"] == "binance"
    assert payload["meta"]["timeframe"] == "4h"
    assert payload["meta"]["setup_keys"] == ["low-stoch-storm"]
    assert payload["meta"]["symbols"] == ["AAVE/USDT", "ETH/USDT"]
    assert "AAVE/USDT" in payload["results"]
    assert payload["errors"]["ETH/USDT"] == "sem candles"


def test_calibrate_triangle_real_keeps_fetch_errors_and_still_recommends(monkeypatch):
    class FakeExchange:
        id = "fake-triangle"

        def load_markets(self):
            return None

    dataset = _build_triangle_dataset()

    def fake_fetch(exchange, *, symbol, days):
        if symbol == "FAIL/USDT":
            raise RuntimeError("sem candles")
        return dataset

    def fake_backtest(df, *, config):
        score = 1.0 if config.pivot_window == 2 else 0.6
        return BacktestResult(
            key="grid-strict",
            setup="Triangle Breakout",
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            total_pnl=8.0 + score,
            avg_pnl=0.8,
            profit_factor=1.4,
            sharpe_ratio=score,
            best_trade=3.0,
            worst_trade=-1.0,
            max_drawdown=8.0,
            notes="fake",
        )

    monkeypatch.setattr(setups_module, "_build_ccxt_exchange", lambda exchange_id: FakeExchange())
    monkeypatch.setattr(setups_module, "fetch_triangle_real_dataset", fake_fetch)
    monkeypatch.setattr(setups_module, "_backtest_triangle_breakout", fake_backtest)

    candidates, recommended = calibrate_triangle_real(
        symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "FAIL/USDT"],
        days=DEFAULT_TRIANGLE_REAL_DAYS,
        exchange_id="fake-triangle",
        pivot_windows=(2, 4),
        contraction_max_ratios=(0.92,),
        volume_multipliers=(1.5,),
        breakout_buffer_atr_mults=(0.25,),
        flat_threshold_atr_mults=(0.05,),
        slope_threshold_atr_mults=(0.02,),
        stop_atr_mults=(1.0,),
    )

    assert len(candidates) == 2
    assert recommended is None or recommended.config["pivot_window"] in {2, 4}
    assert all(candidate.errors["FAIL/USDT"] == "sem candles" for candidate in candidates)


def test_cmd_calibrate_triangle_real_writes_meta_and_recommendation(tmp_path, monkeypatch):
    candidate = CalibrationCandidateResult(
        candidate_key="triangle | pivot_window=3",
        config={"pivot_window": 3, "contraction_max_ratio": 0.86},
        eligible=True,
        rejection_reason="",
        median_sharpe_ratio=1.4,
        median_total_pnl=9.1,
        median_max_drawdown=8.2,
        median_total_trades=12.0,
        trade_qualified_symbols=4,
        successful_symbols=4,
        per_symbol={},
        errors={},
    )
    monkeypatch.setattr(cli, "calibrate_triangle_real", lambda symbols, days, exchange_id: ([candidate], candidate))
    output = tmp_path / "triangle_calibration.json"
    args = SimpleNamespace(
        symbols="BTC/USDT,ETH/USDT",
        days=DEFAULT_TRIANGLE_REAL_DAYS,
        exchange="binance",
        output=str(output),
    )

    cli.cmd_calibrate_triangle_real(args)
    payload = cli.json.loads(output.read_text(encoding="utf-8"))

    assert payload["meta"]["exchange"] == "binance"
    assert payload["meta"]["timeframe"] == "1h"
    assert payload["meta"]["symbols"] == ["BTC/USDT", "ETH/USDT"]
    assert payload["recommended_config"]["candidate_key"] == "triangle | pivot_window=3"
    assert payload["candidate_results"][0]["eligible"] is True


def test_cmd_calibrate_funding_real_writes_meta_and_recommendation(tmp_path, monkeypatch):
    candidate = CalibrationCandidateResult(
        candidate_key="funding | min_rate=0.00015",
        config={"min_rate": 0.00015, "exit_rate": 0.00002, "max_hold_intervals": 6, "max_hold_hours": 48, "max_spread_bps": 35.0},
        eligible=True,
        rejection_reason="",
        median_sharpe_ratio=1.1,
        median_total_pnl=4.2,
        median_max_drawdown=3.1,
        median_total_trades=6.0,
        trade_qualified_symbols=3,
        successful_symbols=4,
        per_symbol={},
        errors={},
    )
    monkeypatch.setattr(cli, "calibrate_funding_real", lambda symbols, days, exchange_id: ([candidate], candidate))
    output = tmp_path / "funding_calibration.json"
    args = SimpleNamespace(
        symbols="BTC/USDT,ETH/USDT",
        days=DEFAULT_FUNDING_ARB_REAL_DAYS,
        exchange="krakenfutures",
        output=str(output),
    )

    cli.cmd_calibrate_funding_real(args)
    payload = cli.json.loads(output.read_text(encoding="utf-8"))

    assert payload["meta"]["exchange"] == "krakenfutures"
    assert payload["meta"]["timeframe"] == "8h"
    assert payload["meta"]["symbols"] == ["BTC/USDT", "ETH/USDT"]
    assert payload["meta"]["max_spread_bps_fixed"] == pytest.approx(20.0)
    assert payload["recommended_config"]["candidate_key"] == "funding | min_rate=0.00015"


def test_open_pair_blocks_when_kraken_has_existing_position():
    class FakeNado:
        def __init__(self):
            self.orders = []

        def get_symbol_to_product_map(self):
            return {"BTC/USDT": 2}

        def get_perp_position_size(self, product_id):
            return 0.0

        def get_market_mid_price(self, product_id):
            return 80000.0

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"id": "nado-order"}

    class FakeKraken:
        venue = "futures"

        def __init__(self):
            self.orders = []

        def get_symbol_to_product_map(self, product_filter=None):
            return {"BTC/USDT": "BTC/USD:USD"}

        def get_position(self, symbol):
            return KrakenPosition(
                symbol=symbol,
                side="long",
                size=0.0026,
                entry_price=78613.0,
                mark_price=79000.0,
                unrealized_pnl=1.0,
                leverage=1.0,
            )

        def get_market_order_conflicts(self, symbol, is_buy):
            return []

        def get_market_mid_price(self, symbol):
            return 79000.0

        def round_quantity_to_increment(self, symbol, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"id": "kraken-order"}

    nado = FakeNado()
    kraken = FakeKraken()
    engine = DeltaNeutralEngine(nado=nado, kraken=kraken, volume_per_leg_usd=20.0)

    assert engine.open_pair("BTC/USDT", nado_side="long", notional_usd=20.0) is None
    assert nado.orders == []
    assert kraken.orders == []


def test_protective_stop_price_uses_side_direction():
    engine = object.__new__(DeltaNeutralEngine)
    engine.protective_stop_loss_pct = 0.03

    long_stop = engine.protective_stop_price(100.0, "long")
    short_stop = engine.protective_stop_price(100.0, "short")

    assert long_stop == pytest.approx(97.0)
    assert short_stop == pytest.approx(103.0)


def test_protective_take_profit_price_uses_side_direction():
    engine = object.__new__(DeltaNeutralEngine)
    engine.protective_take_profit_pct = 0.03

    long_tp = engine.protective_take_profit_price(100.0, "long")
    short_tp = engine.protective_take_profit_price(100.0, "short")

    assert long_tp == pytest.approx(103.0)
    assert short_tp == pytest.approx(97.0)


def test_open_pair_attaches_protective_stop_losses():
    class FakeNado:
        def __init__(self):
            self.orders = []
            self.stop_orders = []
            self.take_profit_orders = []
            self.network = "mainnet"
            self.subaccount_name = "default_1"
            self.subaccount_hex = "0xsub"
            self.owner_address = "0xowner"
            self.linked_signer_address = ""

        def get_symbol_to_product_map(self):
            return {"BTC/USDT": 2}

        def get_perp_position_size(self, product_id):
            return 0.0

        def get_market_mid_price(self, product_id):
            return 80000.0

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"id": "nado-order"}

        def place_stop_loss(self, **kwargs):
            self.stop_orders.append(kwargs)
            return {"id": "nado-stop"}

        def place_take_profit(self, **kwargs):
            self.take_profit_orders.append(kwargs)
            return {"id": "nado-tp"}

    class FakeKraken:
        venue = "futures"
        account = "flex"
        account_symbol = ""
        api_fingerprint = "fingerprint"
        sandbox = False

        def __init__(self):
            self.orders = []
            self.stop_orders = []
            self.take_profit_orders = []

        def get_symbol_to_product_map(self, product_filter=None):
            return {"BTC/USDT": "BTC/USD:USD"}

        def get_position(self, symbol):
            return KrakenPosition(
                symbol=symbol,
                side="flat",
                size=0.0,
                entry_price=0.0,
                mark_price=79950.0,
                unrealized_pnl=0.0,
                leverage=1.0,
            )

        def get_market_order_conflicts(self, symbol, is_buy):
            return []

        def get_market_mid_price(self, symbol):
            return 79950.0

        def round_quantity_to_increment(self, symbol, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            self.orders.append(kwargs)
            return {"id": "kraken-order"}

        def place_stop_loss(self, **kwargs):
            self.stop_orders.append(kwargs)
            return {"id": "kraken-stop"}

        def place_take_profit(self, **kwargs):
            self.take_profit_orders.append(kwargs)
            return {"id": "kraken-tp"}

        def get_isolation_context(self):
            return {"subaccount_mode": "dedicated_api"}

    nado = FakeNado()
    kraken = FakeKraken()
    engine = DeltaNeutralEngine(nado=nado, kraken=kraken, volume_per_leg_usd=20.0)
    engine.protective_stop_loss_pct = 0.03
    engine.protective_take_profit_pct = 0.03
    engine.protective_stop_trigger_slippage_pct = 0.01

    state = engine.open_pair("BTC/USDT", nado_side="long", notional_usd=20.0)

    assert state is not None
    assert len(nado.stop_orders) == 1
    assert len(kraken.stop_orders) == 1
    assert len(nado.take_profit_orders) == 1
    assert len(kraken.take_profit_orders) == 1
    assert nado.stop_orders[0]["is_long"] is True
    assert kraken.stop_orders[0]["is_long"] is False
    assert nado.take_profit_orders[0]["is_long"] is True
    assert kraken.take_profit_orders[0]["is_long"] is False
    assert nado.stop_orders[0]["trigger_price"] == pytest.approx(80000.0 * 0.97)
    assert kraken.stop_orders[0]["trigger_price"] == pytest.approx(79950.0 * 1.03)
    assert nado.take_profit_orders[0]["trigger_price"] == pytest.approx(80000.0 * 1.03)
    assert kraken.take_profit_orders[0]["trigger_price"] == pytest.approx(79950.0 * 0.97)
    assert state.nado_stop_price == pytest.approx(80000.0 * 0.97)
    assert state.kraken_stop_price == pytest.approx(79950.0 * 1.03)
    assert state.nado_take_profit_price == pytest.approx(80000.0 * 1.03)
    assert state.kraken_take_profit_price == pytest.approx(79950.0 * 0.97)
    assert state.nado_close_side == "sell"
    assert state.kraken_close_side == "buy"


def test_open_pair_applies_requested_kraken_scalp_leverage():
    class FakeNado:
        network = "mainnet"
        subaccount_name = "default_1"
        subaccount_hex = "0xsub"
        owner_address = "0xowner"
        linked_signer_address = ""

        def get_symbol_to_product_map(self):
            return {"SOL/USDT": 5}

        def get_perp_position_size(self, product_id):
            return 0.0

        def get_market_mid_price(self, product_id):
            return 150.0

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def place_market_order(self, **kwargs):
            return {"id": "nado-order"}

        def place_stop_loss(self, **kwargs):
            return {"id": "nado-stop"}

        def place_take_profit(self, **kwargs):
            return {"id": "nado-tp"}

    class FakeKraken:
        venue = "futures"
        account = "flex"
        account_symbol = ""
        api_fingerprint = "fingerprint"
        sandbox = False

        def __init__(self):
            self.risk_calls = []

        def get_symbol_to_product_map(self, product_filter=None):
            return {"SOL/USDT": "SOL/USD:USD"}

        def get_position(self, symbol):
            return KrakenPosition(
                symbol=symbol,
                side="flat",
                size=0.0,
                entry_price=0.0,
                mark_price=150.0,
                unrealized_pnl=0.0,
                leverage=1.0,
            )

        def get_market_order_conflicts(self, symbol, is_buy):
            return []

        def get_market_mid_price(self, symbol):
            return 150.0

        def round_quantity_to_increment(self, symbol, quantity):
            return quantity

        def configure_futures_risk_context(self, symbol, *, leverage=None, margin_mode=None):
            self.risk_calls.append(
                {
                    "symbol": symbol,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                }
            )
            return {"ok": True}

        def place_market_order(self, **kwargs):
            return {"id": "kraken-order"}

        def place_stop_loss(self, **kwargs):
            return {"id": "kraken-stop"}

        def place_take_profit(self, **kwargs):
            return {"id": "kraken-tp"}

        def get_isolation_context(self):
            return {"subaccount_mode": "dedicated_api"}

    engine = DeltaNeutralEngine(nado=FakeNado(), kraken=FakeKraken(), volume_per_leg_usd=30.0)
    state = engine.open_pair(
        "SOL/USDT",
        nado_side="long",
        notional_usd=30.0,
        kraken_leverage=5.0,
        kraken_margin_mode="cross",
    )

    assert state is not None
    assert engine.kraken.risk_calls == [
        {
            "symbol": "SOL/USD:USD",
            "leverage": pytest.approx(5.0),
            "margin_mode": "cross",
        }
    ]
    assert state.kraken_requested_leverage == pytest.approx(5.0)
    assert state.kraken_margin_mode == "cross"


def test_status_reports_delta_neutral_pair_protection_plan():
    class FakeNado:
        def get_market_mid_price(self, product_id):
            return 80050.0

        def get_perp_position_size(self, product_id):
            return 0.001

    class FakeKraken:
        def get_position(self, symbol):
            return KrakenPosition(
                symbol=symbol,
                side="short",
                size=-0.001,
                entry_price=79950.0,
                mark_price=79900.0,
                unrealized_pnl=0.0,
                leverage=1.0,
            )

    engine = object.__new__(DeltaNeutralEngine)
    engine.nado = FakeNado()
    engine.kraken = FakeKraken()
    engine.drift_bps = 50
    engine._validate_saved_state_context = lambda state, allow_legacy=True: None
    state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="BTC/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=20.0,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=80000.0,
        kraken_entry=79950.0,
        pair_stop_loss_pct=0.03,
        pair_take_profit_pct=0.03,
        nado_stop_price=77600.0,
        kraken_stop_price=82348.5,
        nado_take_profit_price=82400.0,
        kraken_take_profit_price=77551.5,
        nado_close_side="sell",
        kraken_close_side="buy",
    )

    report = engine.status(state)

    assert report["pair_stop_loss_pct"] == pytest.approx(0.03)
    assert report["pair_take_profit_pct"] == pytest.approx(0.03)
    assert report["nado_stop_price"] == pytest.approx(77600.0)
    assert report["kraken_take_profit_price"] == pytest.approx(77551.5)
    assert report["nado_close_side"] == "sell"
    assert report["kraken_close_side"] == "buy"


def test_state_context_validation_blocks_wrong_kraken_fingerprint():
    class FakeNado:
        def get_symbol_to_product_map(self):
            return {"BTC/USDT": 2}

        def get_isolation_context(self):
            return {
                "subaccount_name": "default_1",
                "subaccount_hex": "0xsub",
                "linked_signer_address": "0xlinked",
            }

    class FakeKraken:
        venue = "futures"

        def get_symbol_to_product_map(self, product_filter=None):
            return {"BTC/USDT": "BTC/USD:USD"}

        def get_isolation_context(self):
            return {
                "account": "flex",
                "account_symbol": "",
                "api_fingerprint": "current-api",
                "subaccount_mode": "dedicated_api",
                "sandbox": True,
            }

    state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="BTC/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=20.0,
        effective_notional_usd=20.0,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=50000.0,
        kraken_entry=50010.0,
        nado_subaccount_name="default_1",
        nado_subaccount_hex="0xsub",
        nado_linked_signer_address="0xlinked",
        kraken_account="flex",
        kraken_api_fingerprint="saved-api",
        kraken_subaccount_mode="dedicated_api",
        kraken_sandbox=True,
    )
    engine = DeltaNeutralEngine(nado=FakeNado(), kraken=FakeKraken(), volume_per_leg_usd=20.0)

    with pytest.raises(RuntimeError) as exc:
        engine._validate_saved_state_context(state, allow_legacy=False)  # type: ignore[attr-defined]
    assert "fingerprint" in str(exc.value)


def test_build_engine_accepts_owner_private_key(monkeypatch):
    captured = {}

    class FakeNado:
        def __init__(self, owner_private_key, network, subaccount_name, linked_signer_private_key=None, require_linked_signer=True):
            captured["nado"] = {
                "owner_private_key": owner_private_key,
                "network": network,
                "subaccount_name": subaccount_name,
                "linked_signer_private_key": linked_signer_private_key,
                "require_linked_signer": require_linked_signer,
            }

        def get_symbol_to_product_map(self):
            return {}

    class FakeKraken:
        def __init__(self, api_key, api_secret, venue="futures", sandbox=True, account=None, account_symbol=None, require_subaccount=False, declared_is_subaccount=False):
            captured["kraken"] = {
                "api_key": api_key,
                "api_secret": api_secret,
                "venue": venue,
                "sandbox": sandbox,
                "account": account,
                "account_symbol": account_symbol,
                "require_subaccount": require_subaccount,
                "declared_is_subaccount": declared_is_subaccount,
            }

        def get_symbol_to_product_map(self, product_filter=None):
            return {}

    class FakeEngine:
        def __init__(self, nado, kraken, **kwargs):
            self.nado = nado
            self.kraken = kraken
            self.kwargs = kwargs

    monkeypatch.setattr(cli, "load_nado_trader_class", lambda: FakeNado)
    monkeypatch.setattr(cli, "KrakenTrader", FakeKraken)
    monkeypatch.setattr(cli, "DeltaNeutralEngine", FakeEngine)
    monkeypatch.setenv("NADO_OWNER_PRIVATE_KEY", "owner-key")
    monkeypatch.delenv("NADO_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("NADO_LINKED_SIGNER_PRIVATE_KEY", "linked-key")
    monkeypatch.setenv("NADO_SUBACCOUNT_NAME", "default_1")
    monkeypatch.setenv("NADO_REQUIRE_LINKED_SIGNER", "true")
    monkeypatch.setenv("KRAKEN_API_KEY", "kr-key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "kr-secret")
    monkeypatch.setenv("KRAKEN_REQUIRE_SUBACCOUNT", "true")
    monkeypatch.setenv("KRAKEN_API_IS_SUBACCOUNT", "true")
    monkeypatch.setenv("PROTECTIVE_TAKE_PROFIT_PCT", "0.04")

    engine = cli.build_engine()

    assert isinstance(engine, FakeEngine)
    assert captured["nado"]["owner_private_key"] == "owner-key"
    assert captured["nado"]["linked_signer_private_key"] == "linked-key"
    # OpenClaw policy: subaccount strict mode is optional and respected only when the user enables it.
    assert captured["kraken"]["require_subaccount"] is True
    assert captured["kraken"]["declared_is_subaccount"] is True
    assert engine.protective_take_profit_pct == pytest.approx(0.04)


def test_build_engine_uses_owner_when_linked_signer_missing_and_still_confirms_main_fallback(monkeypatch):
    captured = {}

    class FakeNado:
        def __init__(
            self,
            owner_private_key,
            network,
            subaccount_name,
            linked_signer_private_key=None,
            require_linked_signer=True,
            allow_owner_fallback=False,
        ):
            captured["nado"] = {
                "allow_owner_fallback": allow_owner_fallback,
                "require_linked_signer": require_linked_signer,
            }

        def get_symbol_to_product_map(self):
            return {}

    class FakeKraken:
        def __init__(
            self,
            api_key,
            api_secret,
            venue="futures",
            sandbox=True,
            account=None,
            account_symbol=None,
            require_subaccount=False,
            declared_is_subaccount=False,
        ):
            captured["kraken"] = {
                "require_subaccount": require_subaccount,
                "declared_is_subaccount": declared_is_subaccount,
            }

        def get_symbol_to_product_map(self, product_filter=None):
            return {}

    class FakeEngine:
        def __init__(self, nado, kraken, **kwargs):
            self.nado = nado
            self.kraken = kraken

    monkeypatch.setattr(cli, "load_nado_trader_class", lambda: FakeNado)
    monkeypatch.setattr(cli, "KrakenTrader", FakeKraken)
    monkeypatch.setattr(cli, "DeltaNeutralEngine", FakeEngine)
    monkeypatch.setenv("NADO_OWNER_PRIVATE_KEY", "owner-key")
    monkeypatch.setenv("NADO_LINKED_SIGNER_PRIVATE_KEY", "")
    monkeypatch.setenv("NADO_ALLOW_OWNER_FALLBACK", "true")
    monkeypatch.setenv("KRAKEN_API_KEY", "kr-key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "kr-secret")
    monkeypatch.setenv("KRAKEN_REQUIRE_SUBACCOUNT", "true")
    monkeypatch.setenv("KRAKEN_ALLOW_MAIN_ACCOUNT", "true")
    monkeypatch.delenv("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK", raising=False)

    engine = cli.build_engine()

    assert captured["nado"]["allow_owner_fallback"] is True
    # OpenClaw policy: subaccount strict mode is optional and respected only when the user enables it.
    assert captured["kraken"]["require_subaccount"] is True
    assert engine.nado_allow_owner_fallback is True
    assert engine.kraken_allow_main_account is False

    monkeypatch.setenv("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK", "true")
    engine = cli.build_engine()

    assert captured["nado"]["allow_owner_fallback"] is True
    assert captured["kraken"]["require_subaccount"] is True
    assert engine.nado_allow_owner_fallback is True
    assert engine.kraken_allow_main_account is True


def test_setup_exit_closes_all_crossed_targets_in_one_iteration():
    state = ManagedSetupState(
        setup_key="grid-strict",
        symbol="PUMP/USDT",
        timeframe="1h",
        side="long",
        pair_state=PairState(
            symbol="PUMP/USDT",
            nado_product_id=1,
            kraken_symbol="PUMP/USD:USD",
            nado_side="long",
            kraken_side="",
            requested_notional_usd=30.0,
            effective_notional_usd=30.0,
            nado_qty=3000.0,
            kraken_qty=0.0,
            nado_entry=0.0018,
            kraken_entry=0.0,
        ),
        reference_entry_price=0.0018,
        stop_price=0.0017,
        take_profit=0.0021,
        targets_hit=1,
        execution_mode="nado_only",
        effective_venue="nado",
        metadata={
            "target_levels": [
                {"label": "TP1", "price": 0.0019, "nado_qty": 1000.0, "kraken_qty": 0.0},
                {"label": "TP2", "price": 0.0020, "nado_qty": 1000.0, "kraken_qty": 0.0},
                {"label": "TP3", "price": 0.0021, "nado_qty": 1000.0, "kraken_qty": 0.0},
            ]
        },
    )

    df = pd.DataFrame([{"timestamp": pd.Timestamp("2026-01-01T00:00:00"), "close": 0.0018, "sma50": 0.0025}])
    signal = evaluate_setup_exit(state, df, live_price=0.0022)

    assert signal is not None
    assert signal.action == "exit"
    assert signal.reason == "TP2-TP3 atingido"
    assert signal.metadata["targets_advanced"] == 2
    assert signal.metadata["target_index"] == 1
    assert signal.metadata["target_to_index"] == 2
    assert signal.metadata["nado_qty"] == pytest.approx(2000.0)
