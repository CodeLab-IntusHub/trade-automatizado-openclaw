# Modelo Subconta-Only

## Objetivo

Isolar o trade da conta principal. Na Nado o isolamento e obrigatorio por
padrao; na Kraken Futures e recomendado e opcional — o usuario decide.

## Nado

- owner signer continua existindo para montar o client
- a execucao de trade depende de `NADO_LINKED_SIGNER_PRIVATE_KEY` (`NADO_REQUIRE_LINKED_SIGNER=true` e o default)
- o linked signer configurado precisa bater com o linked signer on-chain da subconta
- a subconta usada pelo bot e `NADO_SUBACCOUNT_NAME`, com `default_1` como exemplo operacional

Consequencia:
- consultas continuam disponiveis
- trade falha fechado sem linked signer valido

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
