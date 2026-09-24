# ADR 0001 — Execução descentralizada, ecossistema de dados compartilhado

> Data: 24 de setembro de 2026
> Status: **Aceita**

## Contexto

O produto nasceu como uma instância central: um bot roda o scanner e transmite
os sinais para um grupo de Discord, onde os assinantes os recebem. O objetivo
passou a ser que **qualquer bot OpenClaw** use a skill, sem depender dessa
instância.

O código já era, em boa parte, descentralizado: todo o estado vive por operador
em `~/.openclaw/`, as chaves são de cada operador, não há nenhum endpoint
central fixo no código, e a skill já é empacotada como `.skill` OpenClaw. O que
era central era a **topologia** (um transmissor, muitos receptores) e as
**instruções do agente** (o `SKILL.md` descreve a operação de uma instância).

## Opções consideradas

1. **Cada bot faz tudo sozinho, sem nada compartilhado.** Mais simples; perde o
   valor de rede — um bot não aprende nada com os outros.
2. **Cada bot faz tudo sozinho e pode transmitir para um canal próprio.**
   Próximo do código atual; a troca entre bots fica restrita a canais humanos.
3. **Rede de sinais entre bots sem nenhum servidor.** Bots publicam e assinam
   diretamente. O problema central vira autenticidade sem nenhum ponto de
   verificação — descoberta, assinatura, anti-reenvio e reputação teriam de ser
   resolvidos de ponta a ponta.
4. **Execução descentralizada, dados compartilhados.** Cada bot escaneia, decide
   e opera sozinho; um ecossistema compartilhado recebe publicações (setups,
   análises, validações, notícias macro) e telemetria.

## Decisão

**Opção 4**, com o ecossistema no **Supabase da IntusHub**, no schema Postgres
`trading` que já existe lá — reformulável por completo (ver o passo 3.2 do
[ROADMAP](../ROADMAP.md)).

A execução descentraliza por completo: nenhum bot depende de outro para operar,
e as chaves de cada operador nunca saem da máquina dele. O ecossistema **é** um
ponto compartilhado, e isso é escolha consciente: ele é um centro **de dados**,
não **de operação**. Se ele cair, os bots continuam operando; perdem só o
conteúdo compartilhado.

## Consequências

- **Confiança vira o problema central.** Se um bot opera em cima do que outro
  publicou, uma publicação forjada ou defeituosa move o dinheiro de quem segue.
  Identidade, RLS, integridade e validação entram antes de qualquer consumo
  automático ([ROADMAP, Fase 3](../ROADMAP.md)).
- **O `SKILL.md` precisa deixar de ser o manual de uma instância** antes de
  qualquer outra coisa ([ROADMAP, Fase 1](../ROADMAP.md)).
- **O contrato do sinal volta a importar, e maior.** Deixa de ser um formato e
  vira vários (setup, análise, validação, notícia), consumidos por bots que
  operam em cima deles.
- **Telemetria envolve o dado financeiro de cada operador.** Ela só existe como
  opt-in com lista fechada de campos ([ADR 0002](0002-sentry-nao-se-aplica.md)).

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Decisão registrada |
| 24/09/2026 | Local do ecossistema: schema `trading` existente, reformulável |
