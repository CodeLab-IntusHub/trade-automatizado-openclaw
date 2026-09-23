# IntusCripto Trade Pine setup scripts

These Pine scripts define the main visual rules used by the Python scanner setups. They are meant to be pasted into TradingView Pine Editor and saved/published as indicators.

Files:

- `intuscripto_grid_1h.pine` -> setup `grid` (deprecated)
- `intuscripto_grid_strict_1h.pine` -> setup `grid-strict`
- `intuscripto_delta_neutral_1h.pine` -> setup `delta-neutral` (single-chart proxy; execution still requires real venue spread)
- `intuscripto_institutional_strict_1h.pine` -> setup `institutional-strict`
- `intuscripto_hybrid_4h.pine` -> setup `hybrid` (deprecated)
- `intuscripto_hybrid_15m.pine` -> setup `hybrid-15m` (deprecated)
- `intuscripto_bollinger_mean_reversion_15m.pine` -> setup `bollinger-mean-reversion`
- `intuscripto_funding_arb_1h.pine` -> setup `funding-arb` (manual/proxy funding context; execution still uses Kraken funding)
- `intuscripto_liquidity_sweep_15m.pine` -> setup `liquidity-sweep`
- `intuscripto_low_stoch_storm_4h.pine` -> setup `low-stoch-storm`
- `intuscripto_divergence_and_volume_15m.pine` -> setup `divergence-and-volume-15m`
- `intuscripto_divergence_and_volume_1h.pine` -> setup `divergence-and-volume-1h`
- `intuscripto_divergence_and_volume_4h.pine` -> setup `divergence-and-volume-4h`

After publishing/adding the indicator in TradingView, configure the delivered chart renderer with the study identifier accepted by TradingView:

```env
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_GRID=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_GRID_STRICT=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DELTA_NEUTRAL=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_INSTITUTIONAL_STRICT=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_HYBRID=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_HYBRID_15M=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_BOLLINGER_MEAN_REVERSION=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_FUNDING_ARB=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_LIQUIDITY_SWEEP=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_LOW_STOCH_STORM=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_15M=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_1H=["<tradingview-study-id>"]
SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_4H=["<tradingview-study-id>"]
```

If a setup Pine study is not configured, the renderer keeps using the native TradingView fallback studies defined in `workspace/tradingview_chart.py`.
