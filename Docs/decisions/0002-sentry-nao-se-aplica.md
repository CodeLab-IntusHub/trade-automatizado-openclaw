# ADR 0002 — Sentry não se aplica a esta skill

> Data: 24 de setembro de 2026
> Status: **Aceita**

## Contexto

A diretriz geral de engenharia da IntusHub marca o Sentry como obrigatório em
todo projeto, para saber quando algo quebra em produção.

Esta skill declara `"runtime": "openclaw"`: ela roda **na máquina do operador**,
operando o dinheiro dele com as chaves dele. Não existe uma "produção nossa" —
a produção é a máquina de cada operador.

## Opções consideradas

1. **Sentry com DSN do projeto, embutido.** Os erros de todo operador chegariam
   ao mantenedor. Mas o evento de erro de um bot de trade carrega tamanho de
   posição, venue, símbolo e caminhos de arquivo com o nome de usuário da
   máquina — enviado a um terceiro que o operador nunca autorizou.
2. **Sentry com DSN do próprio operador, opcional.** Inócuo, mas então é opção
   documentada, não obrigação; e o mantenedor não recebe nada de qualquer forma.
3. **Observabilidade local.** Log estruturado com um identificador de execução
   que o operador anexa ao relatar um problema, e eliminação das falhas
   engolidas em silêncio.

## Decisão

**Opção 3.** O Sentry não entra como obrigação.

A intenção da diretriz — saber quando e por que algo quebrou — se cumpre aqui
sem tirar o dado financeiro do operador da máquina dele.

## Consequências

- **A pendência real é o log**, não o Sentry: a skill não tem log estruturado e
  tem 87 blocos `except` que não registram nada. Isso entra na trilha contínua
  do [ROADMAP](../ROADMAP.md).
- **A mesma pergunta decide a telemetria.** Enviar dados do bot para o
  ecossistema é o mesmo dilema, por isso a telemetria só existe como opt-in com
  lista fechada de campos ([ADR 0001](0001-execucao-descentralizada-e-ecossistema.md)).
- Se um dia existir um serviço que a IntusHub opere de fato (uma API do
  ecossistema, por exemplo), **esse serviço** segue a diretriz normalmente — a
  exceção é da skill, não da empresa.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Decisão registrada |
