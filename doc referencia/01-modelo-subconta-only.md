# Modelo Subconta-Only

## Objetivo

Todo trade deve rodar apenas no ambiente isolado da subconta.

## Nado

- owner signer continua existindo para montar o client
- a execucao de trade depende de `NADO_LINKED_SIGNER_PRIVATE_KEY`
- o linked signer configurado precisa bater com o linked signer on-chain da subconta
- a subconta usada pelo bot e `NADO_SUBACCOUNT_NAME`, com `default_1` como exemplo operacional

Consequencia:
- consultas continuam disponiveis
- trade falha fechado sem linked signer valido

## Kraken Futures

- o isolamento de trade vem da propria API key
- novas entradas so podem rodar com `KRAKEN_API_IS_SUBACCOUNT=true`
- se a metadata indicar conta master, o projeto bloqueia a abertura
- se a metadata nao puder ser validada, o projeto tambem bloqueia a abertura

## Estado salvo

`workspace/state.json` agora carrega identidade do ambiente:
- contexto Nado da subconta
- fingerprint nao sensivel da API Kraken
- modo de subconta Kraken

Isso evita `status`, `rebalance` e `unwind` no ambiente errado.
