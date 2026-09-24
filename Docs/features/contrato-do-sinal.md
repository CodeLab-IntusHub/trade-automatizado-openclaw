# Contrato do sinal

> Última atualização: 24 de setembro de 2026
> Versão: 1.1.0

## Visão geral

Quando o scanner detecta um setup, ele produz **duas coisas diferentes**:

| O quê | Para onde vai | Quem lê |
|---|---|---|
| **Texto renderizado** (e o gráfico) | Discord e WhatsApp, via `openclaw message send` | Pessoas |
| **Registro estruturado** — o payload deste documento | Outbox local, `trading-signal-outbox.jsonl` | Programas |

O registro estruturado é o formato que o [ecossistema](../ROADMAP.md) vai
publicar e que outros bots vão consumir. Por isso ele é tratado como contrato
desde já: o que entra nele fica difícil de tirar depois que existe consumidor.

## Arquitetura

| Componente | Arquivo | Função |
|---|---|---|
| Produtor do sinal | `workspace/ccxt_entry_scanner.py` (varredura) | Monta o dicionário interno do sinal |
| Payload estruturado | `_structured_signal_call` | Converte o dicionário interno no registro público |
| Outbox | `_append_outbox_record` | Grava cada evento como uma linha JSON |

Cada sinal gera dois eventos no outbox: `signal_detected` (antes da entrega) e
`publish_attempted` (com o resultado da entrega em cada canal).

## O payload

| Campo | Origem | Observação |
|---|---|---|
| `schema` | fixo | `intuscripto.trading.signal_call.v1` |
| `idempotency_key` | derivado do sinal | Identifica o sinal de forma estável; base da proteção contra reenvio |
| `source` | fixo | `unified_scanner` |
| `called_at`, `bar_at` | sinal | Quando o sinal foi emitido; qual candle o gerou |
| `pair`, `symbol`, `asset_text` | sinal | Par normalizado e textos derivados |
| `setup_slug`, `setup_text` | sinal | Identificador do setup e nome legível |
| `venue`, `side`, `timeframe` | sinal | |
| `entry`, `initial_stop`, `targets` | sinal | Sempre quatro alvos |
| `thesis` | sinal | Justificativa do setup |
| `leverage`, `risk_profile` | sinal | |
| `context` | sinal | `exchange`, `raw_symbol`, `take_profit`, `margin_mode` |

### Todo campo é explícito

Cada campo da tabela é montado um a um em `_structured_signal_call`. Não existe
campo que carregue o dicionário interno do sinal, então nada que entre nele
atravessa para o registro por acidente.

**O contrato está travado num teste.** O conjunto **exato** de chaves — do
topo e do `context` — está declarado em `test/test_payload_do_sinal.py`, e a
comparação é por igualdade: um campo a menos quebra quem consome, e um campo a
mais é o caminho por onde o dicionário interno voltaria a vazar. A lista mora
no teste, e não no módulo, de propósito: se vivesse no código, acrescentar um
campo seria só acrescentar na lista, e o teste concordaria.

**Adicionar um campo ao contrato é uma decisão:** atualizar o teste e este
documento na mesma PR.

## Histórico

Até a v1.6.0, o registro tinha um campo `raw_payload` com o dicionário interno
**inteiro**. Qualquer chave que entrasse nele atravessava — não porque
houvesse segredo ali, mas porque nada impedia. E `context.scanner_state_path`
emitia o caminho absoluto do arquivo de estado na máquina do operador, com o
nome de usuário dele.

Na v1.7.0 o caminho saiu, e `raw_payload` passou a ser filtrado. O rebrand
deixou `schema` com o nome antigo (`aspira.trading.signal_call.v1`) e pôs o
atual ao lado, em `schema_canonico`, para não quebrar em silêncio um eventual
leitor do outbox que comparasse por esse texto.

Em 24/09/2026 confirmou-se que **nada lê o outbox**. A convivência não
protegia ninguém e só deixava dois nomes para a mesma coisa: `schema` passou a
ter o nome atual, e `schema_canonico` e `raw_payload` saíram.

## Testes

| Arquivo | Garante |
|---|---|
| `test/test_payload_do_sinal.py` | O conjunto exato de chaves do contrato; `schema` com o nome atual e sem campo de convivência; nenhum caminho local sai; chave desconhecida não atravessa |
| `test/test_rebrand_intuscripto.py` | O `schema` usa o nome novo |
| `test/test_unified_signal_publication.py` | O caminho de publicação unificado |

O teste de "nenhum caminho local sai" **injeta** um caminho reconhecível no
lugar do caminho real e verifica que ele não aparece. Uma versão anterior
comparava contra o diretório pessoal da máquina e passava mesmo com o
vazamento reintroduzido — o resultado dependia de onde o teste rodava.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Documento inicial: os dois produtos do sinal, o payload, a fronteira pública e os campos de legado |
| 24/09/2026 | Contrato fechado: `schema` com o nome atual, sem `schema_canonico` nem `raw_payload`; o conjunto de chaves passa a ser travado por teste |
