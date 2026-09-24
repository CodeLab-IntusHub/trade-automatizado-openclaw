# Proteção de ordens (SL/TP)

> Última atualização: 24 de setembro de 2026
> Versão: 1.1.0

## Visão geral

Quando o bot abre posição, ele anexa stop loss e take profit na venue. Este
documento descreve como a skill decide que a proteção foi **de fato** anexada.

O motivo de existir: os chamadores de `place_stop_loss`/`place_take_profit`
testam apenas `if order is None`. Sem validação, **qualquer objeto** devolvido
pela corretora contava como sucesso — inclusive uma rejeição estruturada. A
posição ficava sem stop e nada no sistema registrava isso.

## Arquitetura

A checagem vive num módulo só, consumido pelos três adapters. Cópia por adapter
garantiria que as cópias divergissem — foi exatamente o que aconteceu com o
`FileLock` antes de ser consolidado.

| Componente | Arquivo | Função |
|---|---|---|
| Validador | `workspace/venues/order_validation.py` | Decide se a resposta confirma a ordem |
| CEX genérica | `workspace/venues/ccxt_cex.py` | Qualquer exchange via CCXT |
| Hyperliquid | `workspace/venues/hyperliquid_dex.py` | Adapter próprio |
| Kraken | `workspace/kraken/kraken_integration.py` | Adapter próprio |
| Nado | `workspace/nado/nado_integration.py` | Parcial — ver Limitações |

## Contrato

`validate_order_response` recusa em três casos e aceita no resto:

1. **Resposta não estruturada** (não é `dict`) → `VenueCapabilityError`.
2. **Status terminal de falha** (`canceled`, `cancelled`, `rejected`,
   `expired`, `failed`) → `VenueCapabilityError`.
3. **Sem `id`** → `UnconfirmedOrderError`.

### Por que denylist, e não allowlist

A primeira versão usava uma lista de status *aceitos*. Isso é pior que o bug
original: o CCXT repassa status não mapeados das venues (`active`, `triggered`,
`working`), então uma ordem legitimamente aceita seria tratada como falha — o
chamador marcaria a posição como desprotegida e um retry anexaria **um segundo
stop para a mesma quantidade**.

### Por que `UnconfirmedOrderError` é um tipo separado

Sem `id`, a ordem **pode** ter sido criada e o bot não consegue rastreá-la.
Afirmar "não há stop" seria falso, e recomendar retry empilharia uma segunda
ordem sobre uma viva e invisível. Esse erro pede conferência manual na
corretora, não nova tentativa.

## Substituição de stop

`replace_stop_loss` cancela o stop vivo **antes** de criar o novo, nos três
adapters. Se a criação falhar, a posição fica sem stop nenhum — e a mensagem
de erro diz isso explicitamente, porque é a parte urgente.

A ordem não foi invertida de propósito: criar antes de cancelar deixaria dois
stops simultâneos para a mesma quantidade. Escolher entre os dois riscos é
decisão em aberto.

No `setup-live`, a falha também limpa a referência da ordem cancelada do estado
(`_invalidate_native_stop_ref`). Sem isso, o ciclo seguinte tentaria cancelar um
id que não existe mais e levantaria `OrderNotFound` **por cima** do erro real,
escondendo que a posição está desprotegida.

### Modo de stop por alvo, lido do estado

O `setup-live` pode mover o stop de uma posição aberta conforme os alvos são
atingidos: `breakeven_on_tp1` leva o stop à entrada depois do primeiro alvo, e
`ladder` o sobe em escada. O modo escolhido é gravado no estado da posição e
relido a cada ciclo por `_target_stop_mode_from_state`.

Quando o valor gravado não é reconhecido, o ciclo usa `off` — **e avisa**,
nomeando o símbolo, o setup e o valor recusado. `off` não deixa a posição sem
stop: o stop atual continua onde está. O que se perde é a **melhoria** que o
operador pediu.

Duas escolhas deliberadas:

- **Não levanta erro.** O loop gerencia várias posições; derrubá-lo por causa
  do estado de uma só deixaria as outras sem gestão.
- **Avisa.** Antes, o valor irreconhecível caía em `off` em silêncio. Isso não
  acontece dentro de uma mesma versão — o valor é validado na entrada do
  comando —, mas acontece entre versões, porque o arquivo de estado sobrevive
  à atualização: um nome de modo removido ou renomeado desligaria o trailing
  de toda posição aberta sem ninguém saber. E acontece com estado editado à mão.

## Limitações conhecidas

- **Nado:** a resposta do SDK não é validada. O formato não está documentado no
  módulo e não há como verificá-lo sem conta ativa. O log deixou de declarar
  sucesso — diz "enviada (resposta não validada)". O `replace_stop_loss` da Nado
  já tem o aviso de posição desprotegida.
- **Cancelamento não é validado.** Um cancel bem-sucedido volta com status
  `canceled`, que é justamente o que a denylist de criação trata como falha;
  reaproveitar o validador ali inverteria o significado.
- **Contadores do `live-hedge`** ainda contam posição aberta-e-desprotegida como
  `blocked`, que se lê como "não abriu".

## Nota sobre capacidade de venue

Não existe portão estático de "esta venue suporta stop nativo".
`has['createStopLossOrder']` do CCXT **não é oráculo confiável**: hyperliquid,
kraken e mexc reportam `None` e mesmo assim implementam `stopLossPrice`. Gatear
nesse flag recusaria venues que funcionam. O que funciona é validar a resposta.

## Changelog

| Data | Mudança |
|------|---------|
| 14/09/2026 | Documento inicial, cobrindo PRs #4, #5 e #8 |
| 24/09/2026 | Modo de stop por alvo lido do estado: aviso quando o valor não é reconhecido (PR #22) |
