# Risk Management

## Cenários de risco

### 1. Divergência de preço Nado × Kraken
**Causa:** os dois mercados têm books independentes. Em momentos de volatilidade, Nado (DEX em L2) pode atrasar segundos em relação à Kraken.
**Mitigação:**
- `slippage_bps=100` (1%) para garantir fills
- Ordens simultâneas, mas em caso de fill parcial, `close_position` da perna cheia
- Rebalance detecta drift e ajusta

### 2. Funding rate adverso
**Causa:** mesmo sendo "neutro", você paga funding nas duas pernas. Se uma delas tem funding muito positivo ou muito negativo, o custo acumula.
**Mitigação:**
- `cli.py funding` para checar antes de abrir
- Se `funding_nado – funding_kraken > 0.05%/8h`, considerar o par mais caro

### 3. Liquidação de uma perna
**Causa:** Kraken Futures tem margem isolada. Se o preço se move contra a perna *short*, a margem cai.
**Mitigação:**
- Stop global `MAX_PAIR_LOSS_PCT=0.03` (-3% do notional total)
- Leverage default 1× (margem total = notional)
- Monitor via `status` (campo `leverage` no `KrakenPosition`)

### 4. Falha de API após perna 1
**Causa:** Nado preenche, Kraken está fora do ar → você fica direcional.
**Mitigação:**
- Rollback automático (reverte perna Nado)
- Se rollback também falha → log em vermelho, o usuário precisa fechar manualmente
- `cli.py status` mostra a posição Nado isolada

### 5. Vazamento de chaves
**Causa:** `NADO_PRIVATE_KEY` dá controle total da wallet.
**Mitigação:**
- `.env` fora de git (gitignore já inclui)
- Usar wallet dedicada ao farming, com só o necessário
- API Kraken com permissão **só trade + funding** (nunca withdraw)

## Checklist antes de abrir posição mainnet

- [ ] `NADO_NETWORK=testnet` foi testado por ≥ 24h
- [ ] `KRAKEN_SANDBOX=false` só se sandbox rodou por ≥ 24h
- [ ] `VOLUME_ORDER` começa pequeno ($20–50)
- [ ] `cli.py symbols` mostra o par que você quer
- [ ] `cli.py funding` < 0.03%/8h em ambas as pernas
- [ ] Saldo USDT0 na Nado ≥ `notional × 1.5` (colateral + margem de segurança)
- [ ] Saldo USD na Kraken ≥ `notional × 1.5`
- [ ] Alertas Telegram/Discord (skill de funding-rate-monitor) armados

## Limites duros do código

```python
DRIFT_BPS              = 50        # rebalance threshold
MAX_PAIR_LOSS_PCT      = 0.03      # -3% do notional → unwind
SLIPPAGE_BPS           = 100       # 1% max slippage market
VERIFY_FILL_WAIT_SECS  = 2.0       # espera antes de checar fill
ROLLBACK_ON_LEG2_FAIL  = True      # sempre reverte perna 1 se perna 2 falha
```

Alterar esses valores sem entender o impacto vai quebrar a premissa de neutralidade.
