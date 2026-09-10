from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workspace.trade_dashboard import TradeDashboardRecorder  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_dashboard_fixture.py <output-dir>")

    output_dir = Path(sys.argv[1]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    recorder = TradeDashboardRecorder(
        state_path=output_dir / "dashboard-state.json",
        html_path=output_dir / "dashboard.html",
        setup_state_path=output_dir / "setup-live-state.json",
    )
    recorder.process_setup_live_line(
        "2026-05-05 12:00:00 [INFO] setup-live entry | grid-strict BTC/USDT | "
        "side=long | mode=hedged | entry=100 | stop=95 | tp=110 | targets=105,110 | "
        "reason=breakout confirmado",
        flush=False,
    )
    recorder.process_setup_live_line(
        "2026-05-05 12:05:00 [INFO] setup-live exit | grid-strict BTC/USDT | "
        "reason=TP1 atingido | live=105",
        flush=False,
    )
    recorder.process_ccxt_log_line(
        "2026-05-05 12:06:00 [INFO] entry | kraken SOL/USDT | setup=low-stoch-storm | "
        "side=short | timeframe=15m | entry=140 | stop=145 | tp=132 | targets=136,132 | "
        "reason=scan confirmado",
        flush=False,
    )
    recorder.record_analysis(
        {
            "ts": "2026-05-05T12:07:00Z",
            "kind": "scan",
            "setup": "low-stoch-storm",
            "symbol": "SOL/USDT",
            "reason": "fixture playwright",
        },
        flush=False,
    )
    recorder.flush()

    print(recorder.html_path)


if __name__ == "__main__":
    main()
