# Nado API — Reference

## Endpoints

| Rede | Gateway | Archive |
|---|---|---|
| Testnet | `gateway.test.nado.xyz` | `archive.test.nado.xyz` |
| Mainnet | Ver docs oficiais | Ver docs oficiais |

- Docs: https://docs.nado.xyz
- Python SDK: https://pypi.org/project/nado-protocol/
- SDK docs: https://nadohq.github.io/nado-python-sdk/
- Faucet (testnet): https://testnet.nado.xyz/portfolio/faucet

## Product IDs típicos

| ID | Produto |
|---|---|
| 0  | USDT0 (spot / colateral) |
| 2  | BTC-PERP |
| 4  | ETH-PERP |
| 6  | SOL-PERP |
| 8  | BNB-PERP |
| 10 | XRP-PERP |
| 12 | DOGE-PERP |
| 14 | AVAX-PERP |
| 16 | ARB-PERP |
| 18 | OP-PERP |

⚠️ IDs variam entre testnet/mainnet. Sempre use `trader.get_all_products()` ou `trader.get_symbol_to_product_map()`.

## Fee tiers

| Tier | 30d vol | Taker (bps) | Maker (bps) |
|---|---|---|---|
| entry | $0 | 3.5 | 1.0 |
| mid   | $25M+ | 3.0 | 0.5 |
| elite | $5B+ | 1.5 | -0.8 (rebate) |

Docs: https://docs.nado.xyz/fees-and-rebates

## Constraints

- Depósito mínimo **$5 USDT0** para criar subconta
- `size_increment` varia por produto (típico 0.01 para perps)
- `price_increment` varia por produto (típico 0.1 para BTC-PERP)
- Ordens market são **IOC** (Immediate-or-Cancel) — podem não preencher em testnet por falta de liquidez

## Métodos do `NadoTrader` usados pela skill

```python
trader.get_symbol_to_product_map()       # {"BTC/USDT": 2, "ETH/USDT": 4, ...}
trader.get_market_mid_price(product_id)  # preço mid
trader.round_quantity_to_increment(pid, q)
trader.get_perp_position_size(pid)       # sinal: +long / -short
trader.place_market_order(pid, qty, is_buy, slippage_bps)
trader.place_market_order_with_tp_sl(...) # usado em modo opportunistic
trader.get_usdt0_balance()
trader.auto_deposit_if_needed(...)
trader.auto_withdraw_if_needed(...)
```
