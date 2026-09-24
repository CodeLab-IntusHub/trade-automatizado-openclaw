# Modelo Subconta-Only

## Objetivo

Isolar o trade da conta principal. Na Nado o linked signer e recomendado; na
Kraken Futures a subconta e recomendada e opcional — o usuario decide.

## Nado

- owner signer continua existindo para montar o client
- com `NADO_LINKED_SIGNER_PRIVATE_KEY` configurada, o trade assina com o linked signer, que precisa bater com o linked signer on-chain da subconta
- **sem** `NADO_LINKED_SIGNER_PRIVATE_KEY`, o trade assina com a owner key — regra da skill (`workspace/cli.py`), mesmo com `NADO_REQUIRE_LINKED_SIGNER=true`
- a subconta usada pelo bot e `NADO_SUBACCOUNT_NAME`, com `default_1` como exemplo operacional

Consequencia:
- consultas continuam disponiveis
- trade falha fechado quando o linked signer configurado nao confere com o on-chain, ou nao pode ser consultado; usar a owner key nesse caso exige `NADO_ALLOW_OWNER_FALLBACK=true` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`

## Kraken Futures

- o isolamento de trade vem da propria API key: subconta ou conta separada
- por padrao (`KRAKEN_REQUIRE_SUBACCOUNT=false`) a skill **nao exige** subconta; o minimo e uma API key dedicada, sem permissao de saque
- com `KRAKEN_REQUIRE_SUBACCOUNT=true`, a validacao estrita liga:
  - novas entradas so rodam com `KRAKEN_API_IS_SUBACCOUNT=true`
  - se a metadata indicar conta master, o projeto bloqueia a abertura
  - se a metadata nao puder ser validada, o projeto tambem bloqueia a abertura
- na venue spot a regra de subconta Futures nao se aplica

## Estado salvo

`workspace/state.json` carrega identidade do ambiente:
- contexto Nado da subconta
- fingerprint nao sensivel da API Kraken
- modo de subconta Kraken

Isso evita `status`, `rebalance` e `unwind` no ambiente errado.
