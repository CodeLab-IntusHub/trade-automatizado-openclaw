# Migracao Do Estado Atual

## Snapshot conhecido em 22/04/2026

O ambiente anterior ainda refletia:
- `NADO_SUBACCOUNT_NAME=default`
- `KRAKEN_API_IS_SUBACCOUNT=false`
- operacao validada em testnet/sandbox antes do endurecimento subconta-only
- relatórios operacionais em:
  - `workspace/batch-open-20260422-131925.json`
  - `workspace/batch-status-20260422-132159.json`

## Passos obrigatorios

1. Zerar posicoes abertas do ambiente antigo.
2. Trocar o `.env` para o owner signer, linked signer e API key da subconta Kraken.
3. Ajustar `NADO_SUBACCOUNT_NAME` para a subconta dedicada.
4. Validar Kraken com `kraken-accounts`.
5. So depois abrir um novo `open`.

## Regra de seguranca

Se o `state.json` vier do ambiente antigo, a migracao recomendada e desmontar esse estado antes de usar o modo estrito.
