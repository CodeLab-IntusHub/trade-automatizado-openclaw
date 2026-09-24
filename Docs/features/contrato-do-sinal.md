# Contrato do sinal

> Última atualização: 24 de setembro de 2026
> Versão: 1.0.0

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
| Fronteira pública | `CAMPOS_PUBLICOS_DO_SINAL`, `_payload_publico` | Lista do que pode atravessar em `raw_payload` |
| Outbox | `_append_outbox_record` | Grava cada evento como uma linha JSON |

Cada sinal gera dois eventos no outbox: `signal_detected` (antes da entrega) e
`publish_attempted` (com o resultado da entrega em cada canal).

## O payload

| Campo | Origem | Observação |
|---|---|---|
| `schema` | fixo | `aspira.trading.signal_call.v1` — nome **antigo**, mantido por compatibilidade |
| `schema_canonico` | fixo | `intuscripto.trading.signal_call.v1` — nome **atual** |
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
| `raw_payload` | sinal, **filtrado** | Só os campos de `CAMPOS_PUBLICOS_DO_SINAL` — ver abaixo |

### A fronteira pública

O produtor monta 14 campos, e **todos já saem como campo de primeira classe**
na tabela acima. `raw_payload` é, portanto, redundante — ele existe porque
havia consumidores lendo dele.

Até a v1.6.0 ele era o dicionário interno **inteiro**, passado direto. Qualquer
chave que entrasse no dicionário interno atravessava para o registro — não
porque houvesse segredo ali, mas porque nada impedia. Desde então ele carrega
só os campos declarados em `CAMPOS_PUBLICOS_DO_SINAL`.

**Adicionar um campo ao contrato é uma decisão**, não um efeito colateral: a
lista está no código e é repetida num teste, e mudar uma sem a outra quebra a
suíte.

### O que foi removido, e por quê

`context.scanner_state_path` emitia o **caminho absoluto do arquivo de estado**
na máquina do operador — que inclui o nome de usuário dele. Qualquer leitor do
outbox recebia isso, e o ecossistema receberia. É informação de diagnóstico, e
pertence ao log local.

## Campos de legado

Dois campos existem só por compatibilidade, e saem juntos no passo 0.1 do
[ROADMAP](../ROADMAP.md):

- **`schema`** guarda o nome antigo porque um leitor do outbox pode estar
  comparando por esse texto — e uma comparação que deixa de bater não levanta
  erro, só faz o sinal deixar de ser reconhecido. Ao fechar, `schema` passa a
  ter o nome atual e `schema_canonico` sai.
- **`raw_payload`** sai por inteiro.

Antes de fechar, é preciso conferir se algo lê o outbox dependendo de um dos
dois. A mensagem do Discord **não** é um consumidor deste payload.

## Testes

| Arquivo | Garante |
|---|---|
| `test/test_payload_do_sinal.py` | Nenhum caminho local sai; chave desconhecida não atravessa; `raw_payload` limitado; a lista pública não declara campo que o produtor não monta |
| `test/test_rebrand_intuscripto.py` | `schema` com o nome antigo e `schema_canonico` com o novo, enquanto durar a convivência |
| `test/test_unified_signal_publication.py` | O caminho de publicação unificado |

O teste de "nenhum caminho local sai" **injeta** um caminho reconhecível no
lugar do caminho real e verifica que ele não aparece. Uma versão anterior
comparava contra o diretório pessoal da máquina e passava mesmo com o
vazamento reintroduzido — o resultado dependia de onde o teste rodava.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Documento inicial: os dois produtos do sinal, o payload, a fronteira pública e os campos de legado |
