# Kraken API — Reference

## Endpoints

| Venue | REST | WS | Sandbox |
|---|---|---|---|
| Spot | `api.kraken.com` | `ws.kraken.com/v2` | — |
| Futures | `futures.kraken.com` | `futures.kraken.com/ws/v1` | `demo-futures.kraken.com` |

- Spot docs: https://docs.kraken.com/rest/
- Futures docs: https://docs.kraken.com/api/docs/futures-api/trading/
- ccxt wrapper: https://docs.ccxt.com/en/latest/manual.html

## Fee tiers

### Spot (30d vol USD)

| Tier | Maker (bps) | Taker (bps) |
|---|---|---|
| $0 | 25 | 40 |
| $100k+ | 14 | 24 |
| $10M+ | 0 | 10 |

### Futures (30d vol USD)

| Tier | Maker (bps) | Taker (bps) |
|---|---|---|
| $0 | 2 | 5 |
| $100k+ | 1 | 4 |
| $10M+ | 0 | 2 |

**Recomendação para delta-neutral:** use **Kraken Futures** (fee 5 bps taker vs 40 bps spot).

## Símbolos

ccxt `kraken` (spot) usa formato `BASE/QUOTE`:
- `XBT/USDT`, `ETH/USDT`, `SOL/USDT`, etc.
- ⚠️ BTC se chama **XBT** na Kraken. O `KrakenTrader.normalize_symbol()` já faz essa conversão.

ccxt `krakenfutures` usa formato `BASE/USD:USD`:
- `XBT/USD:USD` → corresponde a `PF_XBTUSD` no protocolo nativo
- `ETH/USD:USD` → `PF_ETHUSD`
- `SOL/USD:USD` → `PF_SOLUSD`

## API Key permissions

Para a skill funcionar, a API key deve ter:

- ✅ `Query Funds`
- ✅ `Query Open Orders & Trades`
- ✅ `Query Closed Orders & Trades`
- ✅ `Modify Orders`
- ✅ `Create & Modify Orders`
- ❌ `Withdraw Funds` — **NUNCA habilitar** (não é necessário para hedging)
- ❌ `Global settings` — desnecessário

Kraken Futures usa uma key separada da Spot. Se `KRAKEN_VENUE=futures`, use a key Futures.

## Funding

Kraken Futures paga/cobra funding a cada 4 horas (00:00, 04:00, 08:00 UTC, etc.).
`kraken_trader.get_funding_rate(symbol)` retorna a taxa atual (decimal).

## Limites

- Min order size: varia por par (tipicamente 0.0001 XBT, 0.01 ETH)
- Max open orders: 80 por símbolo
- Rate limits: 60 req/min (API-level, gerenciado por ccxt automaticamente via `enableRateLimit`)
