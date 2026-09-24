# ADR 0004 — Identidade de bot via Supabase Auth

> Data: 24 de setembro de 2026
> Status: **Proposta** — a confirmar no início da Fase 3 do [ROADMAP](../ROADMAP.md)

## Contexto

No ecossistema ([ADR 0001](0001-execucao-descentralizada-e-ecossistema.md)),
cada bot publica e consome conteúdo. Para isso ele precisa de uma identidade:
para que o que publica seja atribuível a ele, para acumular reputação, e para
que o banco impeça um bot de ler ou escrever o dado de outro.

O ecossistema vive no Supabase da IntusHub, e as diretrizes de engenharia pedem
autenticação gerenciada (nada de login próprio) e RLS sempre.

## Opções consideradas

1. **Registro central próprio de bots.** Seria construir autenticação — o que as
   diretrizes vedam.
2. **Chave gerada pelo próprio bot**, registrada no primeiro uso. Resolve
   integridade do que é publicado, mas não dá ao banco uma forma nativa de
   aplicar RLS.
3. **Conta OpenClaw do operador.** Depende de a plataforma expor uma identidade
   verificável para terceiros.
4. **Uma conta Supabase Auth por bot.**

## Decisão proposta

**Opção 4.** Ela entrega, com um mecanismo só, a atribuição do que foi
publicado e o isolamento por RLS (`publisher_id = auth.uid()`), e é o que as
diretrizes já pedem.

Não exclui a opção 2: uma assinatura do conteúdo pode se somar à identidade
para garantir **integridade**, que a RLS não cobre — a RLS diz quem escreveu,
não que o conteúdo continua o mesmo.

## Consequências

- **A credencial do bot é segredo:** vive no ambiente ou no gerenciador de
  segredos, nunca no `settings.json` — a mesma regra que já vale para todo
  segredo da skill.
- **Toda tabela do ecossistema nasce com RLS**, e cada política tem teste
  negativo (o bot A não escreve como o bot B).
- **A decidir no início da fase:** como a conta é criada e ligada ao bot, e como
  é revogada.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Proposta registrada |
