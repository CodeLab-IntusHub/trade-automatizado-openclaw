# Escolha de venue e de modo de execução

> Última atualização: 25 de setembro de 2026
> Versão: 1.9.0

## Visão Geral

A skill não tem venue padrão nem modo de execução padrão. Cada operador escolhe
a DEX e/ou a CEX em que opera e o modo (`hedged`, `dex_only` ou `cex_only`).
Até a v1.8.0, `DEX_ID` e `CEX_ID` ausentes viravam `nado` e `kraken`, e `abrir`
sem modo virava `hedged`. Era a escolha da instância em que a skill nasceu,
aplicada a quem não tinha escolhido nada.

**Por que não deduzir.** Um default de venue opera onde o operador não pediu.
Um modo deduzido pelas credenciais configuradas mudaria sozinho: um operador em
`dex_only` que acrescentasse a chave da CEX para consultar o saldo passaria a
abrir a perna na CEX no ciclo seguinte.

## Comportamento

| Situação | O que acontece |
|---|---|
| Nenhuma venue escolhida | o motor não sobe; a mensagem pede `DEX_ID` e/ou `CEX_ID`; o `doctor` reprova (`venue_escolhida`, bloqueante) |
| O comando exige uma venue que não foi escolhida | para, e diz qual escolher, ou sugere o modo de uma venue só |
| Só CEX | opera; a DEX vira um substituto que recusa operar |
| Só DEX | **exige `CEX_ID` mesmo assim, sem credencial**: candles e universo de símbolos vêm da CEX em todos os modos |
| `abrir` sem modo | para, e sugere os modos compatíveis com as venues (`hedged` só com DEX e CEX) |
| Leitura e diagnóstico sem modo | rodam normalmente; o `doctor` avisa (`modo_execucao`, não bloqueante) |
| Modo incompatível com as venues | o `doctor` avisa (ex.: `hedged` sem DEX) |

Os setups hedgeados por natureza (`delta-neutral`, `funding-arb`) rodam em
`hedged` porque o setup só existe assim. Nesse caso o modo vem do setup que o
operador escolheu, não de um default. O `setup-live` real com setup direcional
exige o modo explícito.

## Venues suportadas

DEX: Nado e Hyperliquid, mais qualquer DEX com adapter (`DEX_ADAPTER_MODULE`).
CEX: Kraken, Binance, Bybit, OKX, KuCoin, Bitget, MEXC e Gate.io, e qualquer
`exchange_id` do CCXT. Nenhuma é padrão. O detalhe por venue está no
[PROGRESS](../PROGRESS.md#venues).

## Componentes

| Componente | Arquivo | Função |
|---|---|---|
| Seleção | `workspace/venues/config.py` | `selected_venues()` sem default; `modos_compativeis()` e a mensagem de modo não escolhido |
| Motor | `workspace/cli.py` | `build_engine()` para quando falta a venue exigida, ou quando falta a CEX |
| Abrir | `workspace/cli.py` | `cmd_open` exige o modo |
| Diagnóstico | `workspace/run.py` | `doctor`: `venue_escolhida` (bloqueante) e `modo_execucao` (aviso) |
| Painel | `workspace/trade_dashboard.py` | sincroniza só as venues em que o operador opera; a CEX sem credencial é só fonte de dados |

## Configuração

| Variável | Valores | Padrão |
|---|---|---|
| `DEX_ID` | `nado`, `hyperliquid` ou id com adapter | nenhum |
| `CEX_ID` | `kraken` ou `exchange_id` do CCXT | nenhum; obrigatória também no modo só DEX |
| `EXECUTION_MODE` (ou `--execution-mode`) | `hedged`, `dex_only`, `cex_only` e sinônimos | nenhum |

## Limite conhecido

Só DEX sem CEX nenhuma não é possível hoje. Para isso, a DEX precisaria virar
fonte de dados (a Hyperliquid expõe candles pelo CCXT, a Nado não), ou a fonte
de dados precisaria ser escolhida separada da venue de execução. O item está no
[ROADMAP, passo 1.6](../ROADMAP.md).

Testes: `test/test_venue_sem_padrao.py` e `test/test_modo_sem_padrao.py`.

## Changelog

| Data | Mudança |
|---|---|
| 24/09/2026 | Sem venue padrão (#37) |
| 25/09/2026 | Sem modo de execução padrão (#38) |
