# ADR 0003 — Painel localhost como app local novo

> Data: 24 de setembro de 2026
> Status: **Proposta** — a confirmar no início da Fase 2 do [ROADMAP](../ROADMAP.md)

## Contexto

O operador precisa acompanhar o próprio bot — trades abertos, PnL, trades
fechados, gráficos — e, depois, o ecossistema.

Já existe um dashboard: `workspace/trade_dashboard.py` gera um `index.html`
estático e um `dashboard-data.json`, regenerados por um loop. Ele mostra
exposição real, trades monitorados, win rate e PnL não realizado. Mas **não tem
nenhum gráfico**, o histórico de fechados e o PnL realizado são fracos, e ele
monta HTML por concatenação de texto num arquivo de 4.224 linhas.

## Opções consideradas

1. **Estender o gerador atual** e servir a pasta de saída em `localhost`. Menor
   esforço inicial; gráficos, dados ao vivo e ecossistema cresceriam um monolito
   que já é o segundo maior arquivo do projeto.
2. **App local novo, reaproveitando a coleta de dados.** Um servidor local
   pequeno expõe JSON, usando as funções de coleta que o gerador já tem, e uma
   página só consome esse JSON.

## Decisão proposta

**Opção 2.**

Além de evitar crescer o monolito, ela resolve um problema que a opção 1 não
resolve: quando o painel mostrar o ecossistema, **a credencial do Supabase
precisa ficar num processo local, nunca na página**. O servidor dá isso sem
esforço adicional. É também o que as diretrizes de arquitetura pedem — o
backend fornece JSON, a borda de apresentação não decide nada.

## Consequências

- **Três regras de segurança desde o primeiro commit**, porque "local" não quer
  dizer "seguro":
  1. escutar **só em `127.0.0.1`** — em `0.0.0.0`, posições e PnL ficam visíveis
     para toda a rede em que a máquina estiver;
  2. **só leitura** na primeira versão — uma ação numa página local pode ser
     disparada por qualquer site aberto no mesmo navegador (CSRF e DNS rebinding
     contra `localhost`); ações só depois, com token e checagem do cabeçalho
     `Host`;
  3. **nenhum segredo no HTML.**
- A coleta de dados passa a ter **uma** implementação, lida pelo dashboard
  estático e pelo painel, até o estático ser depreciado.
- **A decidir no início da fase:** biblioteca padrão ou framework para o
  servidor. A skill evita dependência nova sem motivo.

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Proposta registrada |
