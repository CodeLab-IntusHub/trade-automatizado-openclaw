# Estratégia: Delta-Neutral Cross-Exchange Airdrop Farming

## Princípio

Toda corretora (CEX ou DEX) distribui airdrops baseados em **volume negociado**, não em **direção** ou **PnL**. Então:

- Se eu compro $100 de BTC na Nado, gero $100 de volume lá.
- Se eu ven­do $100 de BTC na Kraken *no mesmo instante*, gero $100 de volume lá **e** zero exposição direcional líquida.

Ao final do dia, somei $200 de volume total, sem ter apostado em nenhuma direção. Se o BTC sobe, ganho na Nado e perdo na Kraken (e vice-versa) — o PnL se cancela.

## Fórmula do custo

```
custo_por_ciclo = fee_abertura_nado
                + fee_abertura_kraken
                + fee_fechamento_nado
                + fee_fechamento_kraken
                + funding_diff × tempo
                + spread_divergencia_preco
```

No tier **entry** (volume $0):
- Nado taker: 3.5 bps (0.035%)
- Kraken Futures taker: 5.0 bps (0.05%)
- Total fees round-trip: `(3.5 + 5.0) × 2 = 17 bps = 0.17%`

Ou seja, a cada abre+fecha de $100 em cada perna, o custo fixo é ~$0.17.
Funding no geral é simétrico entre exchanges (ambas trackeiam spot+basis), mas pode ter spikes — monitorar.

## Janela ideal

Airdrops tipicamente olham **volume cumulativo** em uma janela (7–30 dias). Então:

- **Não quer** fazer churn rápido (abre+fecha toda hora → só acumula fees).
- **Quer** manter posições abertas por horas/dias, rebalanceando só quando o drift for significativo.

## Regras aplicadas pelo código

| Regra | Valor default | Por quê |
|---|---|---|
| `DRIFT_BPS=50` | rebalance se delta > 0,5% | abaixo disso, pagar fee do ajuste gasta mais do que o risco |
| `MAX_PAIR_LOSS_PCT=0.03` | stop em -3% do notional | protege de divergência extrema Nado×Kraken |
| `SLIPPAGE_BPS=100` | 1% slippage market | garante preenchimento em testnet/pares ilíquidos |
| rollback automático | ativo | se perna 2 falha, reverte perna 1 |

## Por que Nado × Kraken (e não Nado × Binance)?

- **Kraken também tem airdrop em andamento** (Ink L2 + história de incentivos), e pagar volume só num lado é desperdício.
- Binance não dá airdrops (é listed); Bybit tem mas requer alma.
- Kraken Futures tem fees baixas e suporta ordens simétricas à Nado (perp USD-margined).

## Variação: Nado × Kraken Spot

Se `KRAKEN_VENUE=spot`, a perna Kraken vira **spot** (compra real da moeda). Bom se o objetivo é acumular volume na **Kraken Pro** (não Kraken Futures) — mas perde a elegância do hedge (spot não tem alavancagem).

## Recomendação prática

1. Começar em testnet (Nado testnet + Kraken demo futures).
2. Rodar 3 dias com notional baixo (`VOLUME_ORDER=20`) para validar fills, rollbacks, rebalance.
3. Passar para mainnet com `VOLUME_ORDER=100` e `farm --interval 600` (10min).
4. Monitorar volume acumulado via dashboards das duas exchanges.
5. Desmontar quando: (a) campanha de airdrop terminar, ou (b) funding adverso > 0,1%/8h sustentado.
