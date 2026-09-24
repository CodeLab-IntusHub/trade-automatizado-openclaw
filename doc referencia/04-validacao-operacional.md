# Validacao Operacional

## Checklist antes do primeiro trade

1. `symbols`
2. `funding`
3. `kraken-accounts`
4. conferir o contexto ativo logado no terminal

## Comandos

```powershell
python3 workspace/run.py symbols
python3 workspace/run.py funding
python3 workspace/run.py kraken-accounts
python3 workspace/run.py open ETH/USDT --side long --notional 20
python3 workspace/run.py status
python3 workspace/run.py unwind
```

## O que deve acontecer

- Nado mostra subconta e linked signer como contexto de trade
- Kraken mostra `safe` ou `unsafe` (sem validacao estrita, `safe` com o motivo "regra de subconta nao esta habilitada")
- com `KRAKEN_REQUIRE_SUBACCOUNT=true`, `open` falha fechado se a subconta nao estiver realmente isolada
- `status` mostra notional solicitado vs efetivo e o contexto salvo
- `unwind` fecha as duas pernas apenas no mesmo contexto que abriu

## Quando bloquear

- linked signer configurado e diferente do on-chain, ou impossivel de consultar (ausente nao bloqueia: o trade assina com a owner key)
- subconta Nado vazia ou invalida

So com a validacao estrita da Kraken ligada (`KRAKEN_REQUIRE_SUBACCOUNT=true`):

- `KRAKEN_API_IS_SUBACCOUNT=false`
- metadata Kraken indisponivel
- deteccao de conta master na Kraken Futures
