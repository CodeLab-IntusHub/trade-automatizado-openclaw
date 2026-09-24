# ADR 0006 — O ecossistema é acessado pela plataforma, não pelo banco

> Data: 24 de setembro de 2026
> Status: **Aceita** quanto ao caminho de acesso; o mecanismo de identidade é
> **Proposta**, a confirmar no início da Fase 3 do [ROADMAP](../ROADMAP.md)
> Substitui: [ADR 0004](0004-identidade-de-bot-supabase-auth.md)

## Contexto

O [ADR 0004](0004-identidade-de-bot-supabase-auth.md) propôs que cada bot
tivesse uma conta Supabase Auth e falasse **direto com o banco**, com uma RLS
por bot (`publisher_id = auth.uid()`). Ele foi escrito antes de conferir como a
IntusHub organiza o banco compartilhado. Conferido, o modelo não cabe:

- **Toda integração com o banco compartilhado vive no repositório de plataforma
  da IntusHub**, o `intushub-core`. Isso inclui DDL, migrations, Edge Functions
  e políticas, de todos os schemas, inclusive os que pertencem a um produto.
  Este repositório é satélite dele e não guarda nada disso (ver
  [`CLAUDE.md`](../../CLAUDE.md)).
- **O caminho de acesso da plataforma não passa por usuário autenticado no
  banco.** O cliente chama uma Edge Function. Ela é a única que tem a
  credencial de serviço, e chama uma função (RPC) que acessa as tabelas. As
  tabelas não aceitam acesso direto de ninguém.
- **O schema `trading` não é exposto pela API.** Um bot não chega nele por
  conta própria, nem deveria.

Uma conta Supabase Auth por bot abriria um segundo caminho de acesso, paralelo
ao da plataforma. Esse caminho precisaria de política de RLS escrita e mantida
por tabela, e exporia o schema para que existisse.

## Opções consideradas

1. **Manter o ADR 0004:** conta Supabase Auth por bot, acesso direto, RLS por
   bot. Contraria o caminho de acesso da plataforma e exige expor `trading`.
2. **Edge Functions da plataforma como única porta.** O bot chama endpoints
   HTTP publicados pelo `intushub-core`. A Edge Function autentica o bot,
   valida o conteúdo contra o contrato e grava por RPC.
3. **Um servidor próprio do produto na frente do banco.** Duplicaria o que as
   Edge Functions já são, com deploy e credencial a mais para manter.

## Decisão

**Opção 2.** O ecossistema é um conjunto de **endpoints da plataforma**, e a
skill é **cliente HTTP** deles.

- **Quem escreveu** é garantido pela Edge Function, que autentica o bot antes de
  gravar. Não é o banco que garante isso por RLS.
- **O que pode ser escrito** é garantido duas vezes: pelo contrato, validado na
  Edge Function (o mesmo contrato que este repositório trava por teste do lado
  do produtor), e pela RPC, que só aceita o formato que conhece.
- **Onde o código mora:** o endpoint, a RPC e as tabelas vivem no
  `intushub-core`. Aqui ficam o cliente, o contrato do que a skill publica e os
  testes de que ela não emite nada fora dele.

**Proposta, a confirmar no início da Fase 3: o mecanismo de identidade.** Uma
credencial por bot, emitida pela plataforma e revogável individualmente, é a
direção. O formato (chave de API, token assinado, chave pública registrada) é
decidido junto com o passo 3.4 (integridade), porque uma assinatura do conteúdo
pode servir às duas coisas.

## Consequências

- **O trabalho de banco da Fase 3 é PR no planeta.** Aqui só entram o cliente e
  o contrato. Ordem: **expand no banco primeiro, contract no satélite depois.**
  Uma versão da skill que chama um endpoint que ainda não existe quebra o bot de
  quem atualizar.
- **A credencial do bot continua segredo:** vive no ambiente ou no gerenciador
  de segredos, nunca no `settings.json`. A credencial de serviço do banco
  **nunca** chega a um bot, em forma nenhuma.
- **O teste negativo que o ADR 0004 pedia continua valendo, em outro lugar:** o
  bot A não publica como o bot B. Ele passa a ser teste da Edge Function, no
  planeta, e não política de RLS.
- **Indisponibilidade da plataforma não para o bot.** O
  [ADR 0001](0001-execucao-descentralizada-e-ecossistema.md) já exige isso: o
  ecossistema é centro **de dados**, não **de operação**. O cliente HTTP da
  skill falha fechado para publicar e consumir, e aberto para operar.
- **Pergunta em aberto, herdada da plataforma:** os bots do ecossistema são de
  operadores **externos** à IntusHub, clientes do produto. Se o banco
  compartilhado da plataforma é o lugar certo para os dados deles, ou se o
  produto merece um projeto próprio, é decisão da plataforma. Ela precisa ser
  tomada antes da primeira gravação de um bot de terceiro.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Decisão registrada; substitui o ADR 0004 |
