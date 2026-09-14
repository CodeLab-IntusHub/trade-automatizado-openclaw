"""
Smoke tests offline.

Valida:
- imports principais
- fee tiers
- PairState com o novo esquema de notional
- PairState com identidade de subconta
- CLI exposta com os novos comandos
"""

from __future__ import annotations

import subprocess
import sys
import json
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _have_nado_deps() -> bool:
    try:
        import nado_protocol  # noqa: F401
        return True
    except ImportError:
        return False


def _have_ccxt() -> bool:
    try:
        import ccxt  # noqa: F401
        return True
    except ImportError:
        return False


def test_nado_imports():
    if not _have_nado_deps():
        pytest.skip("nado_protocol nao instalado")
    from workspace.nado import NADO_FEE_TIERS, NadoTrader, get_nado_fees  # noqa: F401

    maker, taker = get_nado_fees("entry")
    assert abs(taker - 0.00035) < 1e-9
    assert abs(maker - 0.00010) < 1e-9


def test_kraken_fee_tiers():
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace.kraken import get_kraken_fees

    maker, taker = get_kraken_fees("futures", "entry")
    assert abs(taker - 0.0005) < 1e-9
    assert abs(maker - 0.0002) < 1e-9


def test_delta_neutral_imports():
    if not (_have_nado_deps() and _have_ccxt()):
        pytest.skip("deps nao instaladas")
    from workspace.core import DeltaNeutralEngine, PairState  # noqa: F401

    assert DeltaNeutralEngine.__name__ == "DeltaNeutralEngine"
    state = PairState(
        symbol="BTC/USDT",
        nado_product_id=2,
        kraken_symbol="XBT/USD:USD",
        nado_side="long",
        kraken_side="short",
        requested_notional_usd=100.0,
        effective_notional_usd=99.5,
        nado_qty=0.001,
        kraken_qty=0.001,
        nado_entry=50000.0,
        kraken_entry=50010.0,
        nado_network="testnet",
        nado_subaccount_name="default_1",
        nado_subaccount_hex="0xsubaccount",
        nado_owner_address="0xowner",
        nado_linked_signer_address="0xlinked",
        kraken_account="flex",
        kraken_account_symbol="",
        kraken_api_fingerprint="abc123",
        kraken_subaccount_mode="dedicated_api",
        kraken_sandbox=True,
    )
    payload = state.to_dict()
    assert payload["symbol"] == "BTC/USDT"
    assert payload["requested_notional_usd"] == 100.0
    assert payload["effective_notional_usd"] == 99.5
    assert payload["requested_margin_usd"] == 0.0
    assert payload["sizing_source"] == "notional"
    assert payload["nado_subaccount_name"] == "default_1"
    assert payload["kraken_api_fingerprint"] == "abc123"
    assert state.notional_usd == 99.5


def test_manifest_fields():
    import json

    manifest = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "trade-automatizado-openclaw"
    assert manifest["version"] == "1.4.0"
    assert "delta-neutral" in manifest["tags"]
    assert "NADO_OWNER_PRIVATE_KEY" in manifest["dependencies"]["env"]
    assert any(cmd["name"] == "venues" for cmd in manifest["commands"])
    assert any(cmd["name"] == "kraken-accounts" for cmd in manifest["commands"])
    assert any(cmd["name"] == "cex-accounts" for cmd in manifest["commands"])
    assert any(cmd["name"] == "live-status" for cmd in manifest["commands"])
    assert any(cmd["name"] == "live-hedge" for cmd in manifest["commands"])
    assert any(cmd["name"] == "live-sync" for cmd in manifest["commands"])
    assert any(cmd["name"] == "rodar-setups-live" for cmd in manifest["commands"])
    assert any(cmd["name"] == "abrir" for cmd in manifest["commands"])
    assert any(cmd["name"] == "open-venue-pair" for cmd in manifest["commands"])
    assert any(cmd["name"] == "abrir-par-delta-neutro" for cmd in manifest["commands"])
    assert any(cmd["name"] == "close-venue-pair" for cmd in manifest["commands"])
    assert any(cmd["name"] == "fechar-par-delta-neutro" for cmd in manifest["commands"])
    assert any(cmd["name"] == "setups" for cmd in manifest["commands"])
    assert any(cmd["name"] == "backtest-operational" for cmd in manifest["commands"])
    assert any(cmd["name"] == "backtest-divergence-volume-real" for cmd in manifest["commands"])
    assert any(cmd["name"] == "backtest-funding-real" for cmd in manifest["commands"])
    assert any(cmd["name"] == "calibrate-triangle-real" for cmd in manifest["commands"])
    assert any(cmd["name"] == "calibrate-funding-real" for cmd in manifest["commands"])
    assert any(cmd["name"] == "simulate" for cmd in manifest["commands"])
    assert any(cmd["name"] == "scenario-matrix" for cmd in manifest["commands"])
    assert any(cmd["name"] == "setup-check" for cmd in manifest["commands"])
    assert any(cmd["name"] == "doctor" for cmd in manifest["commands"])
    assert "EXECUTION_MODE" in manifest["dependencies"]["env"]
    assert "NADO_MARGIN_MODE" in manifest["dependencies"]["env"]
    assert "KRAKEN_MARGIN_MODE" in manifest["dependencies"]["env"]
    assert "MARGIN_USD" in manifest["dependencies"]["env"]
    assert "NADO_MARGIN_USD" in manifest["dependencies"]["env"]
    assert "KRAKEN_MARGIN_USD" in manifest["dependencies"]["env"]
    assert "DEX_ID" in manifest["dependencies"]["env"]
    assert "CEX_ID" in manifest["dependencies"]["env"]
    assert "CEX_API_KEY" in manifest["dependencies"]["env"]
    assert "DEX_ADAPTER_MODULE" in manifest["dependencies"]["env"]
    assert "HYPERLIQUID_WALLET_ADDRESS" in manifest["dependencies"]["env"]
    assert "HYPERLIQUID_PRIVATE_KEY" in manifest["dependencies"]["env"]
    assert "HYPERLIQUID_VAULT_ADDRESS" in manifest["dependencies"]["env"]
    assert "MEXC_API_KEY" in manifest["dependencies"]["env"]
    assert "BITGET_API_KEY" in manifest["dependencies"]["env"]
    assert "GATEIO_API_KEY" in manifest["dependencies"]["env"]
    assert "AUTORIZAR_TRADE_REAL" in manifest["dependencies"]["env"]
    assert "CONFIRMAR_TRADE_REAL" in manifest["dependencies"]["env"]
    assert "NADO_ALLOW_OWNER_FALLBACK" in manifest["dependencies"]["env"]
    assert "KRAKEN_ALLOW_MAIN_ACCOUNT" in manifest["dependencies"]["env"]
    assert "DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK" in manifest["dependencies"]["env"]
    assert "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID" in manifest["dependencies"]["env"]
    assert "SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT" in manifest["dependencies"]["env"]
    assert "DISCORD_BOT_TOKEN" in manifest["dependencies"]["env"]
    assert "SETUP_NOTIFY_DISCORD_NATIVE_EMBED" in manifest["dependencies"]["env"]
    assert "SETUP_NOTIFY_DISCORD_EMBED_AUTHOR" in manifest["dependencies"]["env"]
    assert "SETUP_NOTIFY_DISCORD_BOX_STYLE" in manifest["dependencies"]["env"]
    assert "discord_delivery" in manifest["metadata"]["wizard"]["short_wizard_fields"]
    assert manifest["metadata"]["wizard"]["discord_delivery_policy"]["secret_env"] == "DISCORD_BOT_TOKEN"
    assert "SETUP_LIVE_TARGET_STOP_MODE" in manifest["dependencies"]["env"]


def test_execution_mode_aliases():
    import importlib.util

    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        pytest.skip("numpy/pandas nao instalados")

    spec = importlib.util.spec_from_file_location("setups_under_test", ROOT / "workspace" / "core" / "setups.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.normalize_execution_mode("hedged") == module.EXECUTION_MODE_HEDGED
    assert module.normalize_execution_mode("delta-neutral") == module.EXECUTION_MODE_HEDGED
    assert module.normalize_execution_mode("delta-neutro") == module.EXECUTION_MODE_HEDGED
    assert module.normalize_execution_mode("protegido") == module.EXECUTION_MODE_HEDGED
    assert module.normalize_execution_mode("dex_only") == module.EXECUTION_MODE_NADO_ONLY
    assert module.normalize_execution_mode("somente-dex") == module.EXECUTION_MODE_NADO_ONLY
    assert module.normalize_execution_mode("nado_only") == module.EXECUTION_MODE_NADO_ONLY
    assert module.normalize_execution_mode("cex_only") == module.EXECUTION_MODE_KRAKEN_ONLY
    assert module.normalize_execution_mode("somente-cex") == module.EXECUTION_MODE_KRAKEN_ONLY
    assert module.normalize_execution_mode("kraken_only") == module.EXECUTION_MODE_KRAKEN_ONLY


def test_skill_md_frontmatter():
    txt = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert txt.startswith("---")
    front = txt.split("---", 2)[1]
    assert "name: trade-automatizado-openclaw" in front
    assert "description:" in front


def test_first_run_payload_includes_discord_zeus_delivery():
    from workspace import first_run_setup

    payload = first_run_setup.DEFAULT_PAYLOAD
    assert payload["discord_delivery_reference"] == "doc referencia/05-entrega-discord-zeus.md"
    guidance = payload["discord_delivery_guidance"]
    assert guidance["required_secret_envs"] == ["DISCORD_BOT_TOKEN"]
    assert "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID" in guidance["required_config_envs"]
    assert payload["state"]["discord_delivery"]["stage"] == "teste"
    assert payload["state"]["discord_delivery"]["format"] == "embed_nativo"
    assert any(item["field"] == "discord_delivery" for item in payload["question_flow"])


def test_runtime_env_arg_can_be_before_or_after_command():
    from workspace import run

    runtime_env, argv = run._extract_runtime_env_arg(["--runtime-env", "/tmp/runtime.env", "setup-check"])
    assert runtime_env == "/tmp/runtime.env"
    assert argv == ["setup-check"]

    runtime_env, argv = run._extract_runtime_env_arg(["setup-check", "--runtime-env=/tmp/runtime.env"])
    assert runtime_env == "/tmp/runtime.env"
    assert argv == ["setup-check"]


def test_venue_pair_commands_are_live_guarded():
    from workspace import run

    assert "open" in run.TRADE_COMMANDS
    assert "abrir" in run.TRADE_COMMANDS
    assert "setup-live" in run.TRADE_COMMANDS
    assert "rodar-setups-live" in run.TRADE_COMMANDS
    assert "open-venue-pair" in run.TRADE_COMMANDS
    assert "abrir-par-delta-neutro" in run.TRADE_COMMANDS
    assert "close-venue-pair" in run.TRADE_COMMANDS
    assert "fechar-par-delta-neutro" in run.TRADE_COMMANDS
    assert run._has_explicit_sizing(["abrir", "ETH/USDT", "--valor-nominal", "20"])
    assert run._has_explicit_sizing(["rodar-setups-live", "--margem-cex-usd", "20"])
    assert run._has_explicit_sizing(["abrir-par-delta-neutro", "BTC/USDT", "--valor-nominal", "20"])
    assert run._has_explicit_sizing(["abrir-par-delta-neutro", "BTC/USDT", "--margem-usd=20"])
    assert not run._has_explicit_sizing(["abrir-par-delta-neutro", "BTC/USDT"])
    old = os.environ.get("AUTORIZAR_TRADE_REAL")
    os.environ["AUTORIZAR_TRADE_REAL"] = "sim"
    try:
        assert run._live_trade_confirmed() is True
    finally:
        if old is None:
            os.environ.pop("AUTORIZAR_TRADE_REAL", None)
        else:
            os.environ["AUTORIZAR_TRADE_REAL"] = old


def test_runtime_env_file_is_loaded_by_wrapper():
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "runtime.env"
        env_file.write_text("NADO_NETWORK=testnet\nKRAKEN_SANDBOX=true\nMARGIN_USD=20\n", encoding="utf-8")
        env = os.environ.copy()
        env["DELTA_NEUTRAL_USER_CONFIG_FILE"] = str(Path(tmp) / "missing-user-config.env")
        env["DELTA_NEUTRAL_STATE_CONFIG_FILE"] = str(Path(tmp) / "missing-state-config.env")
        for key in (
            "DELTA_NEUTRAL_ENV_FILE",
            "NADO_NETWORK",
            "KRAKEN_SANDBOX",
            "MARGIN_USD",
            "DEX_ID",
            "TRADE_DEX_ID",
            "PRIMARY_DEX",
            "CEX_ID",
            "TRADE_CEX_ID",
            "PRIMARY_CEX",
        ):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "workspace" / "run.py"), "setup-check", "--runtime-env", str(env_file)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["paths"]["env_file"] == str(env_file)
    assert payload["paths"]["active_env_file"] == str(env_file)
    assert payload["safe_defaults"]["margin_usd"] == "20"
    assert payload["venues"]["dex_id"] == "nado"
    assert payload["venues"]["cex_id"] == "kraken"


def test_first_run_wizard_lists_main_venues():
    result = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "first_run_setup.py"), "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["supported_venues"]["default_pair"] == {"dex_id": "nado", "cex_id": "kraken"}
    assert any(item["id"] == "hyperliquid" for item in payload["supported_venues"]["main_dex"])
    cex_ids = {item["id"] for item in payload["supported_venues"]["main_cex"]}
    assert {"binance", "kraken", "bybit", "okx", "kucoin", "mexc", "bitget", "gateio"}.issubset(cex_ids)
    assert "outras CEXs" in payload["supported_venues"]["other_integrations_notice"]
    assert payload["question_flow"][1]["field"] == "venue_selection"
    assert "bybit" in payload["question_flow"][1]["question"].lower()
    assert "kucoin" in payload["venue_setup_guides"]
    assert "mexc" in payload["venue_setup_guides"]
    assert "bitget" in payload["venue_setup_guides"]
    assert "gateio" in payload["venue_setup_guides"]
    assert "outras_cex_ccxt" in payload["venue_setup_guides"]
    assert "outras_dex_adapter" in payload["venue_setup_guides"]
    requirements = payload["venue_credential_requirements"]
    assert "KUCOIN_API_PASSWORD ou CEX_API_PASSWORD" in requirements["kucoin"]["required_envs"]
    assert "MEXC_API_SECRET ou CEX_API_SECRET" in requirements["mexc"]["required_envs"]
    assert "BITGET_API_PASSWORD ou CEX_API_PASSWORD" in requirements["bitget"]["required_envs"]
    assert "GATEIO_API_SECRET ou CEX_API_SECRET" in requirements["gateio"]["required_envs"]
    assert payload["account_isolation_policy"]["subaccount_required_by_default"] is False
    assert payload["question_strategy"]["subaccount_required_by_default"] is False
    assert payload["account_isolation_policy"]["subaccount_user_decides"] is True
    assert payload["account_isolation_policy"]["must_not_hardcode_subaccount_requirement"] is True
    assert payload["question_strategy"]["subaccount_user_decides"] is True
    assert payload["question_strategy"]["target_stop_mode_user_decides"] is True
    assert any(item["field"] == "target_stop_mode" for item in payload["question_flow"])
    target_stop_question = next(item for item in payload["question_flow"] if item["field"] == "target_stop_mode")
    assert target_stop_question["options"] == ["desligado", "entrada-no-tp1", "escada"]
    assert target_stop_question["default"] == "desligado"
    assert "KRAKEN_REQUIRE_SUBACCOUNT=false por padrao" in requirements["kraken"]["config_envs"]
    assert "recomendada" in payload["account_isolation_policy"]["kraken"]
    assert "HYPERLIQUID_PRIVATE_KEY" in requirements["hyperliquid"]["required_envs"]
    assert "HYPERLIQUID_VAULT_ADDRESS" in requirements["hyperliquid"]["optional_envs"]
    assert "DEX_MARKET_TYPE=trade" in payload["dex_market_type_reference"]
    assert any("DEX_MARKET_TYPE=trade" in item for item in requirements["hyperliquid"]["config_envs"])


def test_doc_reference_exists():
    doc_root = ROOT / "doc referencia"
    assert (doc_root / "00-indice.md").exists()
    assert (doc_root / "01-modelo-subconta-only.md").exists()


def test_security_guards_present():
    nado = (ROOT / "workspace" / "nado" / "nado_integration.py").read_text(encoding="utf-8")
    kraken = (ROOT / "workspace" / "kraken" / "kraken_integration.py").read_text(encoding="utf-8")
    cli = (ROOT / "workspace" / "cli.py").read_text(encoding="utf-8")
    nado_auto = (ROOT / "workspace" / "nado" / "auto_trade_nado.py").read_text(encoding="utf-8")
    nado_example = (ROOT / "workspace" / "nado" / "example.py").read_text(encoding="utf-8")
    backup = (ROOT / "backup_project.py").read_text(encoding="utf-8")

    assert "raise RuntimeError(self.trade_auth_error)" in nado
    assert "raise RuntimeError(str(safety[\"reason\"]))" in kraken
    assert "TRADE_AUTOMATIZADO_CONFIRM_LIVE" in cli
    assert "DELTA_NEUTRAL_CONFIRM_LIVE" in cli
    assert 'os.environ.get("PRIVATE_KEY")' in cli
    assert 'os.environ.get("PRIVATE_KEY")' in nado_auto
    assert 'os.environ.get("PRIVATE_KEY")' in nado_example
    assert '"workspace/.env"' not in backup


def test_direct_cli_trade_guard_before_dependencies():
    env = os.environ.copy()
    for key in (
        "AUTORIZAR_TRADE_REAL",
        "CONFIRMAR_TRADE_REAL",
        "TRADE_AUTOMATIZADO_CONFIRM_LIVE",
        "DELTA_NEUTRAL_CONFIRM_LIVE",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "abrir", "ETH/USDT", "--lado", "comprado", "--valor-nominal", "20"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode != 0
    assert "TRADE_AUTOMATIZADO_CONFIRM_LIVE" in result.stderr
    assert "DELTA_NEUTRAL_CONFIRM_LIVE" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_cli_help():
    if not (_have_nado_deps() and _have_ccxt()):
        pytest.skip("deps nao instaladas")
    help_timeout = 60
    result = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result.returncode == 0
    assert "trade-automatizado-openclaw" in result.stdout
    assert "venues" in result.stdout
    assert "kraken-accounts" in result.stdout
    assert "cex-accounts" in result.stdout
    assert "simulate" in result.stdout
    assert "scenario-matrix" in result.stdout
    assert "live-hedge" in result.stdout
    assert "live-sync" in result.stdout
    assert "setup-live" in result.stdout
    assert "setup-live-status" in result.stdout
    assert "setups" in result.stdout
    assert "backtest-operational" in result.stdout
    assert "backtest-hybrid-real" in result.stdout
    assert "backtest-funding-real" in result.stdout
    assert "calibrate-triangle-real" in result.stdout
    assert "calibrate-funding-real" in result.stdout

    result_backtest = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "backtest-operational", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_backtest.returncode == 0
    assert "--timeframe" in result_backtest.stdout
    assert "--hybrid-profile" in result_backtest.stdout

    result_hybrid = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "backtest-hybrid-real", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_hybrid.returncode == 0
    assert "--exchange" in result_hybrid.stdout
    assert "--symbols" in result_hybrid.stdout
    assert "--profile" in result_hybrid.stdout

    result_funding = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "backtest-funding-real", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_funding.returncode == 0
    assert "--symbols" in result_funding.stdout
    assert "--min-rate" in result_funding.stdout
    assert "--max-hold-intervals" in result_funding.stdout

    result_triangle_cal = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "calibrate-triangle-real", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_triangle_cal.returncode == 0
    assert "--symbols" in result_triangle_cal.stdout
    assert "--exchange" in result_triangle_cal.stdout
    assert "--output" in result_triangle_cal.stdout

    result_funding_cal = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "calibrate-funding-real", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_funding_cal.returncode == 0
    assert "--symbols" in result_funding_cal.stdout
    assert "--exchange" in result_funding_cal.stdout
    assert "--output" in result_funding_cal.stdout

    result_open = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "open", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_open.returncode == 0
    assert "--execution-mode" in result_open.stdout
    assert "--modo" in result_open.stdout
    assert "--lado" in result_open.stdout
    assert "--margin-mode" in result_open.stdout
    assert "--modo-margem" in result_open.stdout
    assert "--margin-usd" in result_open.stdout
    assert "--margem-usd" in result_open.stdout
    assert "--valor-nominal" in result_open.stdout
    assert "--alavancagem" in result_open.stdout
    assert "--nado-margin-usd" in result_open.stdout
    assert "--kraken-margin-usd" in result_open.stdout
    assert "--dex-margin-usd" in result_open.stdout
    assert "--cex-margin-usd" in result_open.stdout
    assert "--dex-leverage" in result_open.stdout
    assert "--cex-leverage" in result_open.stdout
    assert "dex_only" in result_open.stdout
    assert "cex_only" in result_open.stdout

    result_setup_live = subprocess.run(
        [sys.executable, str(ROOT / "workspace" / "cli.py"), "setup-live", "--help"],
        capture_output=True,
        text=True,
        timeout=help_timeout,
    )
    assert result_setup_live.returncode == 0
    assert "--setup" in result_setup_live.stdout
    assert "--symbol" in result_setup_live.stdout
    assert "--interval" in result_setup_live.stdout
    assert "--margin-usd" in result_setup_live.stdout
    assert "--dex-margin-usd" in result_setup_live.stdout
    assert "--cex-margin-usd" in result_setup_live.stdout
    assert "--stop-loss-preset" in result_setup_live.stdout
    assert "--stop-loss-pct" in result_setup_live.stdout
    assert "--modo-stop-alvo" in result_setup_live.stdout
    assert "--target-stop-mode" in result_setup_live.stdout
    assert "--notify-entry-discord-channel-id" in result_setup_live.stdout
    assert "--notify-entry-discord-account" in result_setup_live.stdout
    assert "dex_only" in result_setup_live.stdout
    assert "cex_only" in result_setup_live.stdout


def test_venue_summary_accepts_hyperliquid_builtin_and_ccxt_cex(monkeypatch):
    from workspace.venues.config import venue_summary

    monkeypatch.setenv("DEX_ID", "hyperliquid")
    monkeypatch.delenv("DEX_ADAPTER_MODULE", raising=False)
    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")

    summary = venue_summary()
    assert summary["dex_id"] == "hyperliquid"
    assert summary["dex_adapter"] == "builtin:hyperliquid"
    assert summary["cex_id"] == "binance"
    assert summary["cex_adapter"] == "ccxt"
    assert summary["cex_credentials_configured"] is True
    assert summary["dex_adapter_configured"] is True
    assert summary["capabilities"]["dex"] == {
        "native_sl": True,
        "native_tp": True,
        "edit_stop": False,
        "cancel_trigger": True,
        "reduce_only": True,
    }
    assert summary["capabilities"]["cex"]["native_tp"] is True
    assert "HYPERLIQUID_PRIVATE_KEY" in summary["dex_required_env"]["private_key"]


def test_hyperliquid_dex_adapter_maps_perps_without_live_credentials():
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    adapter = HyperliquidDexTrader(load_markets=False, symbol_quote="USDT")
    adapter.client.markets = {
        "BTC/USDC:USDC": {
            "symbol": "BTC/USDC:USDC",
            "base": "BTC",
            "quote": "USDC",
            "swap": True,
            "contract": True,
            "precision": {"amount": 0.001},
            "limits": {"amount": {"min": 0.001}},
        }
    }
    adapter.client.market = lambda symbol: adapter.client.markets[symbol]

    symbol_map = adapter.get_symbol_to_product_map()
    assert symbol_map["BTC/USDT"] == "BTC/USDC:USDC"
    assert adapter.round_quantity_to_increment("BTC/USDT", 0.0019) == 0.001

    created_orders = []
    cancelled_orders = []
    adapter.vault_address = "0x1234567890abcdef1234567890abcdef12345678"
    adapter.get_market_mid_price = lambda product_id: 65000.0
    adapter.client.create_order = lambda *args: created_orders.append(args) or {"id": "stub"}
    adapter.client.cancel_order = lambda *args: cancelled_orders.append(args) or {"id": args[0], "status": "canceled"}

    adapter.place_market_order("BTC/USDT", 0.002, is_buy=True, slippage_bps=100)
    assert created_orders[-1][:5] == ("BTC/USDC:USDC", "market", "buy", 0.002, 65000.0)
    assert created_orders[-1][5]["slippage"] == 0.01
    assert created_orders[-1][5]["vaultAddress"] == adapter.vault_address

    replaced = adapter.replace_stop_loss("BTC/USDT", 0.001, 64000.0, previous_order_ref={"id": "old-sl"})
    assert replaced["cancelled"] is True
    assert cancelled_orders[-1][0] == "old-sl"
    assert cancelled_orders[-1][2]["vaultAddress"] == adapter.vault_address
    assert created_orders[-1][:5] == ("BTC/USDC:USDC", "market", "sell", 0.001, 64000.0)
    assert created_orders[-1][5]["vaultAddress"] == adapter.vault_address
    assert adapter.capabilities()["cancel_trigger"] is True

    adapter.place_stop_loss("BTC/USDT", 0.002, 64000.0, is_long=True, slippage_pct=0.02)
    assert created_orders[-1][:5] == ("BTC/USDC:USDC", "market", "sell", 0.002, 64000.0)
    assert created_orders[-1][5]["stopLossPrice"] == 64000.0
    assert created_orders[-1][5]["reduceOnly"] is True

    adapter.place_take_profit("BTC/USDT", 0.002, 67000.0, is_long=True, slippage_pct=0.02)
    assert created_orders[-1][:5] == ("BTC/USDC:USDC", "market", "sell", 0.002, 67000.0)
    assert created_orders[-1][5]["takeProfitPrice"] == 67000.0
    assert created_orders[-1][5]["reduceOnly"] is True

    try:
        adapter.assert_trade_ready()
    except RuntimeError as exc:
        assert "HYPERLIQUID_WALLET_ADDRESS" in str(exc)
    else:
        raise AssertionError("Hyperliquid live trade should require wallet/private key")


def test_hyperliquid_market_type_trade_alias_maps_to_ccxt_swap():
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    adapter = HyperliquidDexTrader(load_markets=False, market_type="trade")

    assert adapter.market_type == "swap"
    assert adapter.client.options["defaultType"] == "swap"


def test_hyperliquid_dex_market_type_trade_fallback_maps_to_ccxt_swap(monkeypatch):
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace import cli
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    monkeypatch.delenv("HYPERLIQUID_MARKET_TYPE", raising=False)
    monkeypatch.setenv("DEX_MARKET_TYPE", "trade")

    config = cli._load_hyperliquid_config("hyperliquid")
    adapter = HyperliquidDexTrader(load_markets=False, market_type=config["market_type"])

    assert config["market_type"] == "trade"
    assert adapter.market_type == "swap"
    assert adapter.client.options["defaultType"] == "swap"


def test_hyperliquid_risk_context_passes_leverage_to_margin_mode():
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    adapter = HyperliquidDexTrader(load_markets=False)
    calls = []
    adapter._resolve_market_symbol = lambda product_id: "ETH/USDC:USDC"
    adapter.client.has["setMarginMode"] = True
    adapter.client.has["setLeverage"] = True
    adapter.client.set_margin_mode = lambda mode, symbol, params=None: calls.append((mode, symbol, params)) or {"ok": True}
    adapter.client.set_leverage = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("set_leverage should not be called after set_margin_mode"))

    result = adapter.configure_futures_risk_context("ETH/USDT", leverage=5, margin_mode="cross")

    assert result["margin_mode"] == "cross"
    assert result["leverage"] == 5.0
    assert calls == [("cross", "ETH/USDC:USDC", {"leverage": 5})]


def test_hyperliquid_get_balance_reads_usdc_free_balance():
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace.venues.hyperliquid_dex import HyperliquidDexTrader

    adapter = HyperliquidDexTrader(load_markets=False)
    adapter.client.fetch_balance = lambda params=None: {"USDC": {"free": 26.19, "total": 26.19}}

    assert adapter.get_balance() == 26.19


def test_setup_readiness_uses_generic_dex_balance_for_hyperliquid():
    from workspace import cli
    from workspace.core import EXECUTION_MODE_NADO_ONLY

    class FakeDex:
        def get_isolation_context(self):
            return {"venue": "hyperliquid", "trade_ready": True}

        def get_balance(self, asset="USDC"):
            assert asset == "USDC"
            return 26.19

    class FakeCex:
        def get_trading_safety(self, **kwargs):
            return {"safe": True, "label": "safe"}

        def get_accounts_overview(self):
            return {
                "selected": {"account": "flex"},
                "accounts": [{"name": "flex", "available_margin": 1000.0}],
            }

    class FakeEngine:
        dex_id = "hyperliquid"
        volume_per_leg = 100.0
        nado = FakeDex()
        kraken = FakeCex()

    snapshot = cli._assess_setup_entry_readiness(
        FakeEngine(),
        managed_states=[],
        requested_notional_usd=100.0,
        execution_mode=EXECUTION_MODE_NADO_ONLY,
    )

    assert snapshot["can_open"] is True
    assert snapshot["dex_venue_label"] == "Hyperliquid"
    assert snapshot["dex_balance"] == 26.19
    assert snapshot["blockers"] == []


def test_hyperliquid_symbols_diagnostic_does_not_require_live_credentials(monkeypatch):
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    from workspace import cli

    monkeypatch.setenv("DEX_ID", "hyperliquid")
    monkeypatch.setenv("CEX_ID", "kraken")
    monkeypatch.setenv("KRAKEN_API_KEY", "dummy")
    monkeypatch.setenv("KRAKEN_API_SECRET", "dummy")
    for name in (
        "HYPERLIQUID_WALLET_ADDRESS",
        "HYPERLIQUID_ACCOUNT_ADDRESS",
        "HYPERLIQUID_PRIVATE_KEY",
        "HYPERLIQUID_API_PRIVATE_KEY",
        "HYPERLIQUID_AGENT_PRIVATE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    class FakeHyperliquid:
        def get_symbol_to_product_map(self, product_filter=None):
            return {"BTC/USDT": "BTC/USDC:USDC"}

    class FakeKraken:
        venue = "futures"
        account = "flex"
        account_symbol = ""
        api_fingerprint = "test"
        sandbox = False

        def __init__(self, *args, **kwargs):
            pass

        def get_symbol_to_product_map(self, product_filter=None):
            assert product_filter == ["BTC/USDT"]
            return {"BTC/USDT": "BTC/USD:USD"}

    def fake_hyperliquid_from_config(config):
        assert not config.get("wallet_address")
        assert not config.get("private_key")
        return FakeHyperliquid()

    monkeypatch.setattr(cli, "KrakenTrader", FakeKraken)
    monkeypatch.setattr(cli.HyperliquidDexTrader, "from_config", fake_hyperliquid_from_config)

    engine = cli.build_engine(require_nado=False)

    assert engine.dex_id == "hyperliquid"
    assert engine.common_symbols() == ["BTC/USDT"]


def test_cex_market_type_trade_alias_is_user_friendly(monkeypatch):
    from workspace import cli
    from workspace.venues import config as venue_config

    monkeypatch.setenv("CEX_MARKET_TYPE", "trade")

    assert cli._load_cex_market_type("binance") == "swap"
    assert cli._load_cex_market_type("kraken") == "futures"
    assert venue_config._normalize_cex_market_type("trade", "bybit") == "swap"
    assert venue_config._normalize_cex_market_type("trade", "kraken") == "futures"


def test_custom_dex_adapter_loader_validates_interface():
    import sys
    import types
    from workspace.venues.custom_dex import load_custom_dex_adapter

    module = types.ModuleType("test_custom_dex_adapter")

    class Adapter:
        def __init__(self, **config):
            self.config = config

        def get_symbol_to_product_map(self):
            return {"ETH/USDT": "ETH-PERP"}

        def get_market_mid_price(self, product_id):
            return 2500.0

        def get_perp_position_size(self, product_id):
            return 0.0

        def get_all_positions(self):
            return []

        def round_quantity_to_increment(self, product_id, quantity):
            return quantity

        def place_market_order(self, *args, **kwargs):
            return {"ok": True}

        def place_stop_loss(self, *args, **kwargs):
            return {"ok": True}

        def place_take_profit(self, *args, **kwargs):
            return {"ok": True}

        def assert_trade_ready(self):
            return None

        def get_isolation_context(self):
            return {"trade_ready": True}

    module.Adapter = Adapter
    sys.modules[module.__name__] = module
    adapter = load_custom_dex_adapter("test_custom_dex_adapter:Adapter", {"network": "testnet"})
    assert adapter.config["network"] == "testnet"
    assert adapter.get_symbol_to_product_map() == {"ETH/USDT": "ETH-PERP"}


def test_generic_ccxt_trader_uses_any_ccxt_exchange(monkeypatch):
    if not _have_ccxt():
        pytest.skip("ccxt nao instalado")
    import ccxt
    from workspace.venues.ccxt_cex import GenericCcxtTrader

    class FakeExchange:
        has = {"fetchFundingRate": True, "fetchPositions": True, "setLeverage": False, "setMarginMode": False}

        def __init__(self, config):
            self.config = config
            self.markets = {
                "ETH/USDT:USDT": {
                    "base": "ETH",
                    "quote": "USDT",
                    "settle": "USDT",
                    "swap": True,
                    "contract": True,
                    "precision": {"amount": 3},
                    "limits": {"amount": {"min": 0.001}},
                }
            }
            self.created_orders = []

        def load_markets(self):
            return self.markets

        def market(self, symbol):
            return self.markets[symbol]

        def fetch_ticker(self, symbol):
            assert symbol == "ETH/USDT:USDT"
            return {"bid": 2499.0, "ask": 2501.0}

        def fetch_funding_rate(self, symbol):
            return {"fundingRate": 0.0002}

        def fetch_positions(self, symbols=None):
            return []

        def fetch_open_orders(self, symbol=None):
            return []

        def fetch_balance(self, params=None):
            return {"USDT": {"free": 1000}}

        def create_order(self, symbol, order_type, side, quantity, price, params):
            order = {"id": f"order-{len(self.created_orders) + 1}", "symbol": symbol, "type": order_type, "side": side, "amount": quantity, "params": params}
            self.created_orders.append(order)
            return order

        def cancel_order(self, order_id, symbol=None):
            return {"id": order_id, "symbol": symbol, "status": "canceled"}

    monkeypatch.setattr(ccxt, "fakecex", FakeExchange, raising=False)
    trader = GenericCcxtTrader("fakecex", "key", "secret", market_type="trade")
    assert trader.venue == "swap"
    assert trader.client.config["options"]["defaultType"] == "swap"
    assert trader.get_symbol_to_product_map() == {"ETH/USDT": "ETH/USDT:USDT"}
    assert trader.get_market_mid_price("ETH/USDT") == 2500.0
    assert trader.get_funding_rate("ETH/USDT") == 0.0002
    assert trader.round_quantity_to_increment("ETH/USDT", 0.12345) == 0.123
    order = trader.place_market_order("ETH/USDT", 0.123, is_buy=False, reduce_only=True, leverage=5)
    assert order["side"] == "sell"
    assert order["params"]["reduceOnly"] is True
    assert order["params"]["leverage"] == 5

    replaced = trader.replace_stop_loss("ETH/USDT", 0.1, 2400.0, previous_order_ref={"id": "old-sl"})
    assert replaced["cancelled"] is True
    assert replaced["order"]["params"]["stopLossPrice"] == 2400.0
    assert trader.capabilities()["reduce_only"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
