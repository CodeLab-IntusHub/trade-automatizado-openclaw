# Roadmap

> Última atualização: 25 de setembro de 2026
> Versão do produto na criação deste plano: 1.6.0

Plano de produto do IntusCripto: de uma instância central que transmite sinais
para um grupo, para **uma skill que cada bot OpenClaw executa sozinho**, com um
ecossistema compartilhado onde os bots publicam e consultam conteúdo, e um
painel local para o operador acompanhar tudo.

Este documento diz **o que** será feito e **em que ordem**. O **porquê** de
cada escolha de arquitetura está nos ADRs em [`decisions/`](decisions/). O que
já existe e funciona está em [`PROGRESS.md`](PROGRESS.md).

## Direção

| Camada | Hoje | Destino |
|---|---|---|
| Execução (escanear, decidir, operar) | Já roda na máquina de cada operador, com as chaves dele | **Mantida** — cada bot faz tudo sozinho |
| Distribuição de sinais | Uma instância transmite para um grupo | Cada bot publica, opcionalmente, num ecossistema compartilhado |
| Instruções do agente (`SKILL.md`) | Manual de operação de uma instância específica | Instrução genérica, com preferências da instância em `settings` |
| Dados compartilhados | Não existem | Banco da IntusHub, acessado por Edge Functions da plataforma, com identidade por bot |
| Visualização | Dashboard HTML estático regenerado por loop | Painel `localhost`: trades, PnL, gráficos e o ecossistema |

A execução descentraliza por completo. O ecossistema **é** um ponto
compartilhado — de dados, não de operação — e isso é escolha consciente,
registrada no [ADR 0001](decisions/0001-execucao-descentralizada-e-ecossistema.md).

## Como seguir este plano

Cada passo abaixo vira **uma PR**, na ordem. O método que se provou nas fases
anteriores continua valendo:

1. **Medir antes de corrigir.** Reproduzir o defeito, ou medir o estado atual,
   por execução — não por leitura.
2. **Teste primeiro** (vermelho → verde → refatorar).
3. **Mutação** em toda decisão de dinheiro, proteção ou segurança: um teste que
   não falha quando o defeito volta não defende nada.
4. **`/code-review`** antes de mergear.
5. **Doc de feature** em [`features/`](features/) antes de considerar a feature
   pronta, e o `CHANGELOG` atualizado na mesma PR.
6. Fatiar por **invariante** e por **direção de consequência** (dinheiro e
   proteção primeiro), nunca por arquivo.

Cada passo traz um **critério de pronto**. Um passo só está feito quando o
critério está verificado — não quando o código foi escrito.

---

## Fase 0 — Fechamentos que destravam o resto

Itens pequenos, herdados das entregas anteriores.

### 0.1 Fechar o legado do contrato do sinal — **concluído em 24/09/2026**

Confirmou-se que nada lê o outbox local. `schema` passou a ter o nome atual, e
`schema_canonico` e `raw_payload` saíram. O conjunto exato de chaves do
registro ficou travado por teste. Ver
[Contrato do sinal](features/contrato-do-sinal.md).

### 0.2 Badge do renderer lê a marca da configuração — **concluído em 24/09/2026**

O badge de `workspace/render_trade_chart.js` passou a mostrar
`SETUP_NOTIFY_BRAND`; vazia, a imagem sai sem badge. O teste roda o `html()` do
renderer pelo `node` — o HTML que o screenshot fotografa — e trava a marca
configurada, a ausência de badge sem marca, o escape e a falta de literal de
marca no arquivo.

### 0.3 `doc referencia/` — **concluído em 24/09/2026**

O sandbox já tinha sido corrigido na fase 4; o que restava era a subconta
Kraken descrita como obrigatória, quando o código só a exige com
`KRAKEN_REQUIRE_SUBACCOUNT=true`. `01` e `04` foram atualizados, o `02`
(migração de 22/04/2026) foi para `doc referencia/historico/`, e os links do
índice foram corrigidos. `test/test_doc_referencia.py` trava os links da pasta.
O `05-entrega-discord-zeus.md`, citado mas ausente, é do passo 1.3.

---

## Fase 1 — Skill genérica: qualquer bot instala e opera

**Por que é a primeira:** o `SKILL.md` é o que o agente de cada bot lê, e hoje
ele é o manual de uma instância específica — "quando o owner pedir", "no fluxo
Hyperliquid top 50", "default operacional recente: US$1.000 por cenário",
"scripts que ficam no workspace". Um bot que instala a skill recebe a instrução
de agir como aquela instância. Nenhuma outra fase faz sentido enquanto isso não
mudar.

### 1.1 Inventário do que é de uma instância só — **concluído em 24/09/2026**

Registrado em [`inventario-do-skill-md.md`](inventario-do-skill-md.md): cada
trecho com a linha de origem e o grupo, mais as referências de fora do pacote
(1.3) e duas contradições internas a decidir antes do 1.4.

- **Passos:** classificar cada trecho do `SKILL.md` em três grupos — **regra
  geral** (fica), **preferência de instância** (vira configuração), **histórico**
  (vai para o `OPENCLAW-SOURCE.md` ou sai).
- **Pronto quando:** a classificação está registrada na própria PR, trecho a
  trecho, com a linha de origem.

### 1.2 Preferências de instância viram configuração

Exemplos: capital de simulação padrão dos backtests, universo de ativos
auditado, padrão visual do relatório de backtest.

- **Passos:** cada preferência ganha chave em `settings.schema.json` e exemplo
  em `settings.example.json`, com o valor atual como default — ninguém que já
  opera percebe diferença.
- **Pronto quando:** o `SKILL.md` referencia a chave, não o valor; o schema
  aceita a chave; teste cobre o default.

### 1.3 Scripts que "ficam no workspace"

O `SKILL.md` manda reutilizar scripts que não estão neste repositório, e
documentos do pacote apontam para arquivos que não existem nele:

| Referência | Citada em |
|---|---|
| Scripts do "dashboard v3" de backtest ("ficam no workspace") | `SKILL.md`, seção de visualização de backtests |
| `doc referencia/05-entrega-discord-zeus.md` | `SKILL.md` (duas vezes) e `README.md` |
| `map/discord-zeus-delivery.md` | `README.md` |
| `examples/discord-zeus/README.md` | `README.md` |

- **Passos:** para cada item, trazer para o repositório (se for genérico) ou
  remover a instrução e o link (se for da instância).
- **Pronto quando:** toda instrução do `SKILL.md` e todo link do `README` apontam
  para algo que existe no pacote `.skill` — há teste de link quebrado.

### 1.4 `SKILL.md` reescrito como instrução genérica

- **Pronto quando:** o `SKILL.md` não cita operador específico, data de decisão
  de instância nem arquivo fora do pacote; um teste de guarda impede a volta.

### 1.5 Primeira execução sem pressupor centro

O onboarding (`first_run_setup.py`, questionário em `references/`) não pode
pressupor grupo de Discord nem canal central: entrega de mensagem é opcional e
aponta para o operador.

- **Pronto quando:** um bot OpenClaw limpo instala a skill, passa por
  `setup-check`/`doctor` e roda `setup-live --simular` sem configurar Discord.

### 1.6 Sem venue padrão

Decisão do autor em 24/09/2026: não existe DEX nem CEX padrão, cada operador
escolhe onde opera, e a Nado não é obrigatória. Até a v1.8.0, `DEX_ID` e
`CEX_ID` ausentes viravam `nado` e `kraken`.

- **Código — feito em 24/09/2026:** o resolvedor não completa a escolha; o
  comando que precisa da venue que falta para com mensagem; o `doctor` reprova
  sem venue (`venue_escolhida`); o wizard e o `.env.example` não sugerem par;
  o dashboard sincroniza só as venues escolhidas. Transição sem versão de
  aviso, também por decisão do autor. Teste em `test/test_venue_sem_padrao.py`.
- **Limite descoberto no review:** candles e universo de símbolos vêm sempre
  da CEX (`_fetch_setup_market_dataset`), inclusive no modo só DEX. Por isso
  só DEX ainda exige `CEX_ID` (sem credencial); o motor recusa subir sem ela.
  Para só DEX de fato, a DEX precisa virar fonte de dados — a Hyperliquid
  expõe candles pelo CCXT, a Nado não — ou o operador escolhe a fonte de
  dados à parte da venue de execução.
- **Modo de execução — feito em 25/09/2026:** também sem padrão, por decisão do
  autor. `abrir` sem modo para e sugere os modos compatíveis com as venues;
  o modo não é deduzido pelas credenciais; o `doctor` avisa modo ausente ou
  incompatível (`modo_execucao`). Teste em `test/test_modo_sem_padrao.py`.
- **Documentação — feita em 25/09/2026:** `SKILL.md`, `README`, `INSTALL` e
  `references/` deixam de eleger venue ("default seguro `DEX_ID=nado`",
  "Nado DEX/Kraken CEX como defaults"). Um teste
  (`test/test_docs_sem_venue_padrao.py`) trava a volta. **Passo concluído.**
- **Referral:** no futuro, cada venue suportada ganha o link de referral da
  IntusHub para contas novas (decisão do autor em 24/09/2026). O referral não
  muda a ordem nem o destaque das venues: nenhuma vira padrão por isso.
- **Pronto quando:** nenhum doc de operador elege venue nem modo de execução.

### 1.7 Autonomia do agente, com as travas no lugar certo

Decidido no [ADR 0007](decisions/0007-autonomia-do-agente.md): as travas da
skill são instrução ao agente, não fechadura, e as que valem ficam na exchange
e na aprovação de execução do OpenClaw. Modos: **análise** (padrão), **real
com aprovação** (recomendado) e **real autônomo**.

- **Passos:**
  1. Onboarding e `SKILL.md` descrevem os três modos e o que prende cada um;
     a configuração de aprovação recomendada do OpenClaw (`tools.exec` em
     allowlist estreita, com aprovação para os comandos de trade); e sugerem o
     **1Password** para os segredos. **Feito em 25/09/2026:** o onboarding
     pergunta o modo (`autonomy_mode`, análise até o operador escolher).
  2. O `doctor` verifica, onde a venue expõe, se a API key pode sacar, e
     reprova se puder; onde não expõe, diz que não conseguiu verificar.
     **Feito em 25/09/2026 para CEX** (Binance, Bybit e OKX expõem; as demais
     ficam "não verificado"). Por decisão do autor no mesmo dia, é **aviso**;
     `BLOQUEAR_SAQUE=sim` o torna bloqueio (doctor e comando de trade). Falta DEX: API wallet da Hyperliquid não saca,
     a chave principal saca; a owner key da Nado saca.
  3. O `doctor` avisa quando detectar que o OpenClaw dispensa aprovação
     (`security: full`). Antes: confirmar o formato de `tools.exec` e de
     `~/.openclaw/exec-approvals.json`. **Levantado em 25/09/2026:** a
     política efetiva é a mais restritiva entre `tools.exec.*` (ou o novo
     `tools.exec.mode`: deny, allowlist, ask, auto, full) e o arquivo de
     aprovações, e as versões novas aposentaram o `exec-approvals.json`. Ler
     arquivo daria falso "seguro"; a fonte é `openclaw exec-policy show`.
     **Feito em 25/09/2026** com a saída real de uma instância: check
     `openclaw_aprovacao` (aviso; `BLOQUEAR_SEM_APROVACAO=sim` o torna
     bloqueio).
  4. A confirmação de operação real passa a ser registrada no log como rastro
     de auditoria, **qualquer que seja a variável usada** — o código aceita
     quatro como equivalentes: `AUTORIZAR_TRADE_REAL`, `CONFIRMAR_TRADE_REAL`,
     `TRADE_AUTOMATIZADO_CONFIRM_LIVE` e `DELTA_NEUTRAL_CONFIRM_LIVE`. A
     documentação deixa de chamá-las de trava. **Feito em 25/09/2026:**
     `auditoria-trade-real.jsonl` no diretório de log.
  5. `workspace/nado/auto_trade_nado.py` tem saque automático
     (`AUTO_WITHDRAW_ENABLED`), contra a política de key sem saque. É script
     avulso, que nenhum comando da skill chama: decidir se sai do pacote ou
     fica documentado como fora da política. **Decidido em 25/09/2026:** fica,
     com aviso no `doctor` quando `AUTO_WITHDRAW_ENABLED=true`, bloqueável por
     `BLOQUEAR_SAQUE`.
- **Pronto quando:** nenhum doc de operador apresenta trava da skill como
  segurança; os passos 2 e 3 têm teste; e um operador novo sabe, pelo
  onboarding, qual modo está usando e o que o protege.

### 1.8 Entrega pelos canais do OpenClaw do operador

Decisão do autor em 25/09/2026: a entrega (Telegram, WhatsApp, Discord e o que
mais o OpenClaw tiver) usa os canais configurados no OpenClaw do próprio
operador, com opção de tópico no Telegram ou bot dedicado. A skill não lê nem
guarda token de bot: bot dedicado é uma conta dedicada no OpenClaw.

- **Mapa (25/09):** o Discord ia direto pela API REST nos três componentes
  (`setup-live`, scanner e watcher), lendo o token até do
  `~/.openclaw/openclaw.json`, com fallback ao OpenClaw desligado; o canal
  padrão era `telegram`; o tópico do Telegram existia só no `setup-live`, sem
  documentação; a audiência "@Intus Club Member" estava fixa; os defaults
  divergiam entre componentes.
- **`setup-live` — feito em 25/09/2026:** tudo por `openclaw message send`,
  sem canal nem conta padrão, tópico com flag. Teste em
  `test/test_entrega_pelo_openclaw.py`.
- **Scanner, watcher e onboarding — feito em 25/09/2026:** os dois chamam a
  mesma função de entrega do `setup-live`; audiência sem valor padrão; o
  onboarding pergunta canal, destino, conta e tópico, sem token de bot; a
  allowlist do `config.env` passa a aceitar toda a configuração de entrega.
  Teste em `test/test_entrega_scanner_watcher.py`. **Passo concluído.**
- **Pronto quando:** nenhum componente chama API de mensageria direto, nenhum
  lê token de bot, e os três leem a mesma configuração de entrega.

**Critério de pronto da fase:** instalar a skill num bot limpo e operar sem
herdar nada da instância original.

---

## Fase 2 — Painel local do próprio bot

Pode andar em paralelo com a Fase 1. Não depende do ecossistema.

**Estado atual:** o dashboard estático já mostra exposição real, trades
monitorados, win rate, PnL não realizado e filtros, com atualização a cada 60 s.
**Não tem nenhum gráfico**, o histórico de trades fechados e o PnL realizado são
fracos, e ele é um arquivo regenerado por loop — não um servidor. Desenho
proposto no [ADR 0003](decisions/0003-painel-localhost-como-app-local.md).

### 2.1 Servidor local mínimo

- **Passos:** servidor que escuta **só em `127.0.0.1`**, porta configurável em
  `settings`, só leitura, rejeitando requisição com cabeçalho `Host` diferente de
  `localhost`/`127.0.0.1` (defesa contra DNS rebinding). Novo comando no
  `run.py`.
- **Decidir no início do passo:** biblioteca padrão ou framework — a skill evita
  dependência nova sem motivo (ver o `settings.schema.json`, que dispensou
  `jsonschema`).
- **Pronto quando:** existe teste que falha se o servidor escutar em outra
  interface, e teste que falha se aceitar `Host` estranho.

### 2.2 Camada de dados em JSON

- **Passos:** extrair a coleta que `workspace/trade_dashboard.py` já faz para
  funções reutilizáveis, **sem duplicar** — o dashboard estático e o painel
  passam a ler da mesma fonte. Expor: exposição real, trades monitorados, trades
  fechados, PnL realizado e não realizado.
- **Pronto quando:** o dashboard estático continua passando no seu e2e, e o
  painel entrega os mesmos números por outra porta.

### 2.3 Histórico de fechados e PnL realizado

Hoje é o ponto mais fraco.

- **Passos:** definir a fonte da verdade (estado do `setup-live` mais os
  preenchimentos da venue) e persistir localmente o fechamento de cada trade.
- **Pronto quando:** o PnL realizado de um trade fechado bate com o que a venue
  reporta, com teste.

### 2.4 Página com gráficos

- **Passos:** tabelas de abertos e fechados; curva de patrimônio; PnL por setup
  e por período; gráfico do trade com entrada, stop e alvos. UI com o
  `impeccable`; cores de ganho e perda que não dependam só de vermelho/verde.
- **Pronto quando:** e2e com Playwright (a base já existe em `tests/e2e/`)
  cobre carga, filtros e gráficos sem erro de console.

### 2.5 Segurança do painel

- **Regras:** sem ações na primeira versão — um botão "fechar posição" numa
  página local pode ser acionado por qualquer site aberto no mesmo navegador;
  nenhum segredo no HTML; `Content-Security-Policy` restritiva.
- **Pronto quando:** cada regra tem teste que falha se ela for removida.

### 2.6 Convivência e depreciação do dashboard estático

- **Pronto quando:** o painel cobre tudo o que o estático mostra, e o estático é
  marcado como depreciado no `CHANGELOG`, sem ser removido na mesma versão.

**Critério de pronto da fase:** um comando abre o painel no navegador com os
dados do bot, e os testes de segurança estão verdes.

---

## Fase 3 — Ecossistema no Supabase da IntusHub

Bots publicam **setups, análises, validações e notícias macro**; outros bots
consultam e, se o operador quiser, operam em cima. Os agentes também
**compartilham setups** entre si (passo 3.8) e alimentam uma **central de
aprendizagem** (passo 3.9). A lista fica aberta: o que vier depois entra pelo
mesmo caminho, com contrato próprio.

**Onde cada parte mora.** Este repositório é satélite do `intushub-core`, o
repositório de plataforma da IntusHub (ver [`CLAUDE.md`](../CLAUDE.md)). O
schema, as funções (RPC), as Edge Functions e os testes de banco desta fase são
**PR no planeta**. Aqui entram o cliente HTTP, o contrato do que a skill publica
e os testes de que ela não emite nada fora dele
([ADR 0006](decisions/0006-ecossistema-pela-plataforma.md)). Ordem de cada
entrega: **expand no banco primeiro, contract no satélite depois.**

O problema central desta fase **não é armazenar** — é **confiança**. Se um bot
opera em cima do que outro publicou, uma publicação forjada ou só defeituosa
move o dinheiro de quem segue. Toda decisão desta fase responde a isso.

### 3.1 Identidade de bot

- **Proposta:** uma credencial por bot, emitida pela plataforma, verificada na
  Edge Function e revogável individualmente. Ver
  [ADR 0006](decisions/0006-ecossistema-pela-plataforma.md), que substitui a
  conta Supabase Auth por bot do ADR 0004.
- **Passos:** como a credencial é emitida, ligada ao bot e revogada; onde ela
  vive (ambiente ou gerenciador de segredos — **nunca** `settings.json`, pela
  regra que já vale para todo segredo da skill).
- **Pronto quando:** um bot se autentica, e a credencial não aparece em nenhum
  arquivo versionado nem em log.

### 3.2 Modelo de dados

O ecossistema nasce no schema Postgres **`trading`**, que já existe no Supabase
da IntusHub — em vez de num schema novo. Ele pode ser **reformulado por
completo**. (O identificador do sinal, `intuscripto.trading.signal_call.v1`, já
usa o mesmo nome.)

- **Passos:**
  1. **Inventário antes de reformular.** O que existe hoje em `trading` —
     tabelas, views, funções, gatilhos, políticas — e **quem lê ou escreve
     nele**: a instância que está no ar, outros produtos da IntusHub, Edge
     Functions, dashboards. "Ninguém usa" se verifica no banco, não se presume:
     reformular um schema que tem consumidor apaga dado e quebra sem erro.
     **Primeira leitura feita em 24/09/2026, registrada no planeta:** o schema
     tem dados e não é exposto pela API, e nenhum repositório versionado
     escreve nele. Quem gravou o que está lá ainda precisa ser identificado
     antes do passo 2.
  2. **Destino dos dados que já estão lá:** migrar, arquivar ou descartar —
     decidido por tabela, antes da primeira migration destrutiva.
  3. **Modelo novo, no planeta:** tabelas de publicação por tipo, com
     `publisher_id` ligado à identidade; acesso só por RPC, chamada pela Edge
     Function; tabelas fechadas a acesso direto. Migrations no `intushub-core`,
     revisadas com o `database-reviewer`.
  4. **Como os bots chegam ao schema:** **decidido** — pela Edge Function, nunca
     direto. `trading` continua fora dos schemas expostos pela API
     ([ADR 0006](decisions/0006-ecossistema-pela-plataforma.md)).
- **Pronto quando:** o inventário está registrado e aprovado antes de qualquer
  migration destrutiva; e um teste **negativo**, no planeta, prova que o bot A
  não consegue escrever como o bot B, nem alterar publicação alheia.

### 3.3 Contrato de publicação v1

- **Passos:** schema versionado para cada tipo (setup, análise, validação,
  notícia); documento em `features/`; política de compatibilidade — adicionar
  campo é versão menor, remover ou mudar significado é versão maior com período
  de convivência. O contrato do sinal atual é o ponto de partida (ver passo 0.1).
- **Pronto quando:** existe teste que falha se o produtor emitir campo fora do
  contrato — o mesmo mecanismo que já trava o registro do sinal
  (`test/test_payload_do_sinal.py`).

### 3.4 Autenticidade e integridade

A Edge Function garante **quem escreveu**. Falta garantir que o conteúdo **não mudou** e
que não foi **reenviado** fora de hora.

- **Passos:** integridade do conteúdo publicado; proteção contra reenvio (a
  `idempotency_key` do sinal já existe e é o começo); expiração de publicação de
  setup.
- **Pronto quando:** publicação alterada depois de gravada, ou reenviada, é
  rejeitada pelo consumidor — com teste.

### 3.5 Validações como mecanismo de confiança

- **Proposta:** uma validação é um bot atestando uma publicação de outro, e a
  reputação de quem publica deriva das validações recebidas.
- **Regra:** por padrão, nenhum bot opera em cima de publicação não validada.
- **Pronto quando:** a regra é aplicada no consumidor, com teste que falha se
  uma publicação sem validação levar a uma ordem.

### 3.6 Consumir e publicar

- **Passos:** o bot lê publicações; operar em cima delas é **opt-in**, com
  limites definidos pelo operador (tamanho máximo, publicadores confiáveis).
  Publicar os próprios setups também é opt-in.
- **Pronto quando:** dois bots, cada um com a sua conta, publicam e consomem; o
  que ultrapassa os limites do operador é recusado, com teste.

### 3.7 Notícias macroeconômicas

- **Decidir no início do passo:** de onde vêm, quem pode publicar e como uma
  notícia é validada — ela não tem um preço de entrada para conferir, como um
  setup tem.

### 3.8 Compartilhamento de setups entre agentes

Um agente publica a **configuração** de um setup, e outro a importa para operar
com ela.

- **Base que já existe:** o `settings.json` com schema
  ([`features/schema-do-settings.md`](features/schema-do-settings.md)) e o
  `config-export` ([`features/config-export.md`](features/config-export.md)),
  que já monta a configuração de um setup e avisa o que não deve sair da máquina.
- **Passos:** o formato publicado é o do `settings`, restrito a um setup;
  importar valida contra o schema e recusa chave desconhecida; **nada** de
  segredo ou caminho local no que é publicado (teste, como no contrato do
  sinal); o setup importado entra **desligado** até o operador ativar.
- **Pronto quando:** um setup exportado por um bot é importado por outro e
  produz a mesma configuração, e um teste prova que a publicação não carrega
  segredo.

### 3.9 Central de aprendizagem dos agentes

Os agentes aprendem com o resultado uns dos outros: que setup funcionou, em que
mercado, em que timeframe.

- **Depende de** 3.5 (validações) e da Fase 5 (telemetria opt-in): o
  aprendizado se alimenta de resultado, e resultado de operador é dado
  financeiro dele.
- **Decidir no início do passo:** o que é agregado e o que é individual; como um
  resultado ruim publicado de propósito é neutralizado (o mesmo problema de
  confiança da fase inteira); e se a central só **informa** o operador ou também
  **ajusta** configuração — ajustar sozinho é operar com dinheiro alheio, e
  começa desligado.
- **Decidido ([ADR 0007](decisions/0007-autonomia-do-agente.md)):** só entram
  resultados conferíveis na exchange (fills reconciliados pela API da venue).
  O relato do agente e o raciocínio narrado por ele não entram como fato.
- **Pronto quando:** o operador vê, no painel, o desempenho agregado de um setup
  entre os bots que aceitaram compartilhar, sem identificar nenhum deles.

**Critério de pronto da fase:** dois bots independentes trocam publicações; o
isolamento por bot e a regra de validação estão provadas por testes negativos.

---

## Fase 4 — O painel ganha o ecossistema

Depende das Fases 2 e 3.

- **4.1** O servidor local chama as Edge Functions do ecossistema. **A
  credencial do bot fica no processo local, nunca na página.**
- **4.2** Aba do ecossistema: publicações recentes, validações, reputação de
  quem publica, e o que o próprio bot publicou.
- **Pronto quando:** a aba funciona, e um teste prova que nenhuma credencial
  chega ao HTML.

---

## Fase 5 — Telemetria

Depende da Fase 3.

A telemetria envolve o dado financeiro de cada operador saindo da máquina dele —
a mesma questão que levou a descartar o Sentry
([ADR 0002](decisions/0002-sentry-nao-se-aplica.md)). Por isso ela é desenhada
como exceção controlada, não como "enviar tudo".

- **5.1** Lista **fechada** de campos: o que não está na lista não sai.
- **5.2** **Opt-in**, desligada por padrão, com consentimento explícito do
  operador (LGPD).
- **5.3** Nunca: segredo, caminho de arquivo local, identificador pessoal.
  Agregar sempre que o dado individual não for necessário.
- **5.4** Escrita por Edge Function da plataforma: cada bot só grava a própria
  telemetria.
- **Pronto quando:** teste prova que, com a telemetria desligada, nada sai; e
  que, ligada, só sai o que está na lista.

---

## Trilha contínua — dívida estrutural

Não bloqueia as fases, mas cada item tem um gatilho natural.

| Item | Situação | Quando atacar |
|---|---|---|
| Piso de cobertura | ~42%, reporta sem bloquear | Antes da Fase 3 — contrato público precisa de proteção contra regressão. Piso no nível atual, com catraca |
| Log estruturado | Não existe; 87 `except` não registram nada | Junto da Fase 2 — o painel precisa de eventos confiáveis para mostrar |
| `workspace/cli.py` (8.594 linhas) | Monolito | Com propósito: extrair a emissão de sinal na Fase 3, a camada de dados na Fase 2. Nunca como projeto isolado |
| Helpers de ambiente restantes | Os de direção de dinheiro e proteção já foram fechados | Baixa prioridade |
| `_to_float` dos adapters | Resposta de corretora ilegível vira default | Decisão própria: é dado externo, não configuração do operador |

## Ordem e dependências

```
Fase 0 ──┐
         ├──> Fase 1 ─────────────┐
         └──> Fase 2 (paralela) ──┼──> Fase 4
                                  │
   Portão ──> Fase 3 (3.1–3.8) ───┴──> Fase 5 ──> 3.9
```

A Fase 2 é a entrega mais visível e não depende de nada. A Fase 3 é a de maior
risco, e por isso tem um **portão** antes do primeiro passo.

### Portão da Fase 3

Nenhum passo da Fase 3 começa antes de:

1. **Piso de cobertura com catraca** (trilha contínua): contrato público
   precisa de proteção contra regressão.
2. **Escritor atual do schema `trading` identificado** (passo 3.2, item 1): o
   schema tem dados e nenhum repositório versionado escreve nele.
3. **Decisão da plataforma sobre onde vivem os dados de operadores externos**
   ([ADR 0006](decisions/0006-ecossistema-pela-plataforma.md), pergunta em
   aberto): banco compartilhado da IntusHub ou projeto próprio do produto.
4. **`premortem`** da fase, com o resultado registrado. Cobre obrigatoriamente
   os três riscos do [ADR 0007](decisions/0007-autonomia-do-agente.md): risco
   sistêmico (teto de exposição agregada por ativo no ecossistema), injeção de
   instrução via dados, e envenenamento do aprendizado.

Os itens 2 e 3 são decididos **fora** deste repositório, na plataforma.

### Etapas, em ordem

| Etapa | Passos | Depende de |
|---|---|---|
| A — fechamentos pequenos | 0.2, 0.3 | — |
| B — skill genérica | 1.1 → 1.8 | A; o 1.3 exige decidir item a item o que falta no pacote |
| C — painel local | 2.1 → 2.6 | nada; corre em paralelo com B |
| D — portão | os quatro itens acima | — ; pode começar já, em paralelo |
| E — ecossistema | 3.1 → 3.8 (3.8 depois de 3.3 e 3.4) | D |
| F — painel com ecossistema | 4.1, 4.2 | C e E |
| G — telemetria | 5.1 → 5.4 | E |
| H — central de aprendizagem | 3.9 | 3.5 e G |

## Changelog

| Data | Mudança |
|------|---------|
| 24/09/2026 | Plano inicial: execução descentralizada, skill genérica, painel local, ecossistema no Supabase e telemetria opt-in |
| 24/09/2026 | Passo 0.1 concluído |
| 24/09/2026 | Passo 3.2: o ecossistema nasce no schema `trading` existente, reformulável; inventário de uso antes de qualquer migration destrutiva |
| 24/09/2026 | Portão da Fase 3 e etapas A–H em "Ordem e dependências"; 3.9 passa a depender da Fase 5 |
| 24/09/2026 | Fase 3 pela plataforma: repo é satélite do `intushub-core`, acesso por Edge Function (ADR 0006); passos 3.8 (compartilhamento de setups) e 3.9 (central de aprendizagem) |
| 24/09/2026 | Passo 1.6: sem venue padrão (código na #37) |
| 25/09/2026 | Passo 1.6: sem modo de execução padrão (#38); passo 1.7 (autonomia do agente, ADR 0007); 3.9 aceita só fills reconciliados; premortem da Fase 3 ganha três riscos obrigatórios |
