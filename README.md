# Trade Automatizado OpenClaw

> Bot/skill OpenClaw para setups delta-neutros e ordens solo em DEX/CEX configuráveis, com defaults Nado DEX + Kraken CEX, CEX via CCXT e Hyperliquid DEX builtin e DEX custom por adapter Python.

## O que faz

- Diagnostica ambiente DEX/CEX antes de qualquer operação; defaults Nado + Kraken.
- Lista símbolos/funding e simula cenários delta-neutros.
- Monitora estado do par ou da perna solo, drift/exposição e PnL.
- Abre, rebalanceia e desmonta pares ou ordens solo quando explicitamente autorizado.
- Suporta `hedged`, `dex_only`/`nado_only` e `cex_only`/`kraken_only`.
- Separa margem e valor nominal com `--margem-usd` (`--margin-usd`): valor nominal operacional = margem * alavancagem.
- Usa o minimo real do ativo/venue para entrada, sem bloquear por minimo artificial do setup.
- Mantem take profit do setup e aceita stop percentual configuravel por execucao.
- Quando TP nativo parcial da Nado fica abaixo do minimo, aplica fallback gerenciado seguro: por padrao (`SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`) o loop fecha 100% no primeiro alvo em vez de deixar sobras pequenas sem TP nativo.
- `live-status` diferencia posicoes `managed` de `ORPHAN`; posicao `ORPHAN` e exposicao real sem `setup_live_state.json` correspondente e nao tem TP/SL gerenciado ativo.
- `setup-live` registra `PNL potencial max` por entrada, usando o melhor preço favorável observado desde a abertura, para auditar lucro potencial vs lucro realmente capturado.
- Se o preço atravessar múltiplos TPs entre duas iterações, o fechamento gerenciado avança todos os alvos cruzados na mesma iteração, somando as quantidades correspondentes.
- `setup-live --dry-run` apenas analisa/simula; nao fecha posicoes reais nem executa TP/SL gerenciado.
- Com `--max-open-setups`/`SETUP_LIVE_MAX_OPEN_SETUPS`, quando uma operacao fecha 100% e sai do state, o slot abre imediatamente e o mesmo ciclo live pode avaliar nova entrada.
- Wizard/first run no padrão Skill Builder: `SKILL.md` mantém regras essenciais e o questionário completo fica em `references/onboarding-questionario.md`, incluindo escolha de DEX/CEX, passos por corretora, TP fallback, órfãs, dry-run e reciclagem de slots.
- Suporta setups operacionais como `delta-neutral`, `funding-arb`, `hybrid`, `grid`, `institutional-strict`, `low-stoch-storm`, `divergence-and-volume-4h` e outros.
- Usa estado fora do Git no padrão OpenClaw.

## Segurança

Esta skill pode operar capital real se configurada para live trading. Por isso:

- nunca salve private key, seed ou API secret no Git;
- use env/secret manager do OpenClaw;
- prefira operar em subconta/conta isolada quando a corretora/DEX oferecer esse recurso; a decisão é do usuário e não deve ser hard-coded; no mínimo use API key dedicada sem saque;
- use Nado linked signer limitado quando configurado;
- fallback para Nado owner key ou Kraken main account exige flags explícitas e confirmação privilegiada;
- mantenha `venues.cex.kraken.sandbox: true` no `settings.json` e `NADO_NETWORK=testnet` até validar tudo (ver [Sandbox por venue](Docs/features/sandbox-por-venue.md));
- comandos de trade são bloqueados pelo wrapper até definir `AUTORIZAR_TRADE_REAL=sim` na execução aprovada; `TRADE_AUTOMATIZADO_CONFIRM_LIVE=true` e `DELTA_NEUTRAL_CONFIRM_LIVE=true` seguem aceitos como aliases técnicos.

## Estrutura

```text
trade-automatizado-openclaw/
├── SKILL.md                 # instruções que o agente do bot lê
├── skill.json               # manifesto OpenClaw
├── README.md
├── CHANGELOG.md
├── INSTALL.md
├── LICENSE
├── settings.example.json    # exemplo de configuração por arquivo
├── settings.schema.json     # vocabulário aceito no settings
├── build.py                 # empacota o .skill (só arquivos rastreados pelo git)
├── CLAUDE.md                # instruções de desenvolvimento; fora do pacote
├── Docs/
│   ├── PROGRESS.md          # o que existe e funciona
│   ├── ROADMAP.md           # o que vem depois, passo a passo
│   ├── decisions/           # ADRs: o porquê das decisões
│   └── features/            # uma página por feature
├── references/              # onboarding e setups Pine
├── resources/
├── doc referencia/          # material de referência antigo
├── test/                    # suíte pytest
├── tests/e2e/               # Playwright
└── workspace/
    ├── run.py               # entrada OpenClaw recomendada
    ├── cli.py               # motor original preservado
    ├── config.py            # fonte única de configuração
    ├── requirements.txt
    ├── core/
    ├── venues/              # adapters e resolvedor de sandbox
    ├── kraken/
    └── nado/
```

A documentação técnica fica em [`Docs/`](Docs/): o estado do produto em
[`PROGRESS.md`](Docs/PROGRESS.md), o plano em [`ROADMAP.md`](Docs/ROADMAP.md) e
as decisões de arquitetura em [`Docs/decisions/`](Docs/decisions/).

## Pré-requisitos

| Requisito | Como configurar |
|---|---|
| Python 3 | Já disponível no container OpenClaw |
| Dependências Python | `python3 workspace/run.py bootstrap` ou bootstrap automático no primeiro comando real |
| Credenciais DEX | Nado usa `NADO_*`; DEX custom usa adapter e secrets definidos por ele, sempre no env/secret manager |
| Credenciais CEX | Kraken usa `KRAKEN_*`; Binance, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io usam `CEX_*` ou envs específicas da venue, sempre no env/secret manager |


## Venues configuráveis

Por padrão a skill usa `DEX_ID=nado` e `CEX_ID=kraken`. O wizard lista as principais venues: DEX `nado` e `hyperliquid`; CEX `kraken`, `binance`, `bybit`, `okx`, `kucoin`, `mexc`, `bitget` e `gateio`. Para trocar a CEX, use qualquer `exchange_id` suportado pelo CCXT e configure `CEX_API_KEY`, `CEX_API_SECRET` e, quando necessário, `CEX_API_PASSWORD`.

## Configuração

Calibração de setup vive em `settings.json` (versionado) ou `settings.local.json`
(do operador, fora do git). Ver `settings.example.json` e
[Docs/features/configuracao-de-setups.md](Docs/features/configuracao-de-setups.md).

Precedência: variável de ambiente → `settings.local.json` → `settings.json` →
default do código. **A variável de ambiente vence o arquivo**; o boot avisa
quais chaves do settings estão encobertas. Segredo nunca entra no settings — o
arquivo declara apenas o *nome* da variável.

Corretoras/venues suportadas ou validadas:

| Venue | IDs/config | Uso atual |
|---|---|---|
| Nado DEX | `DEX_ID=nado` | DEX nativa para ordens live, posicoes, SL/TP e gerenciamento de setup. |
| Kraken Futures/Spot | `CEX_ID=kraken`, `krakenfutures`, `kraken-futures`, `kraken-spot` | CEX nativa principal para hedge/solo, leitura de contas, posicoes e ordens live. |
| Binance USD-M/Futures | `CEX_ID=binanceusdm` ou `CEX_ID=binance` com `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; execucao live depende dos recursos da API e deve passar por dry-run pequeno. |
| Bybit | `CEX_ID=bybit`, `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; execucao live depende dos recursos da API e deve passar por dry-run pequeno. |
| OKX | `CEX_ID=okx`, `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; exige `CEX_API_PASSWORD` quando a conta/API pedir passphrase. |
| KuCoin Futures | `CEX_ID=kucoinfutures` ou `CEX_ID=kucoin` conforme mercado | CCXT validado para dados/conectividade; use `CEX_MARKET_TYPE=swap|future` conforme contrato. |
| Gate.io | `CEX_ID=gateio`, `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; execucao live depende de suporte da conta/permissao. |
| MEXC | `CEX_ID=mexc`, `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; execucao live depende de suporte da conta/permissao. |
| Bitget | `CEX_ID=bitget`, `CEX_MARKET_TYPE=swap` | CCXT validado para dados/conectividade; normalmente exige passphrase/password da API. |
| Outras CEXs via CCXT | `CEX_ID=<exchange_id>` | Adapter CCXT generico; validar `venues`, `symbols`, conta, margem, dry-run e ordem minima antes de qualquer live. |
| Hyperliquid | `DEX_ID=hyperliquid` + `HYPERLIQUID_WALLET_ADDRESS` + `HYPERLIQUID_PRIVATE_KEY` | Adapter builtin via CCXT Hyperliquid para perps; `HYPERLIQUID_VAULT_ADDRESS` opcional. |

Chaves/envs por CEX principal:

| Venue | Chaves especificas aceitas | Alias generico aceito |
|---|---|---|
| Kraken | `KRAKEN_API_KEY_` ou `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` | n/a |
| Binance | `BINANCE_API_KEY`, `BINANCE_API_SECRET` | `CEX_API_KEY`, `CEX_API_SECRET` |
| Bybit | `BYBIT_API_KEY`, `BYBIT_API_SECRET` | `CEX_API_KEY`, `CEX_API_SECRET` |
| OKX | `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSWORD` | `CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD` |
| KuCoin | `KUCOIN_API_KEY`, `KUCOIN_API_SECRET`, `KUCOIN_API_PASSWORD` | `CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD` |
| MEXC | `MEXC_API_KEY`, `MEXC_API_SECRET` | `CEX_API_KEY`, `CEX_API_SECRET` |
| Bitget | `BITGET_API_KEY`, `BITGET_API_SECRET`, `BITGET_API_PASSWORD` | `CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD` |
| Gate.io | `GATEIO_API_KEY`, `GATEIO_API_SECRET` | `CEX_API_KEY`, `CEX_API_SECRET` |
| Outra CCXT | n/a | `CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD` quando exigido |

Observacao operacional: Nado e Kraken sao as integracoes nativas. As demais CEXs usam CCXT; elas podem funcionar para dados, validacoes operacionais, scanner e perna CEX generica, mas margem, sandbox, leverage, SL/TP e parametros de ordem variam por corretora. Antes de live, rode `venues`, `setup-check`, `doctor`, `symbols` e um `--dry-run --max-iter 1` com sizing baixo.

Para usar Hyperliquid como DEX, defina `DEX_ID=hyperliquid` e salve `HYPERLIQUID_WALLET_ADDRESS`/`HYPERLIQUID_PRIVATE_KEY` no Secret Manager; `HYPERLIQUID_VAULT_ADDRESS` é opcional. Para outras DEXs custom, forneça `DEX_ADAPTER_MODULE=pacote.modulo:Classe` e dados não sensíveis em `DEX_CONFIG_JSON`. O adapter deve implementar a interface de trading usada pela skill (`get_symbol_to_product_map`, preço médio, posições, arredondamento, ordens market, SL/TP e `assert_trade_ready`).

Comandos de diagnóstico:

```bash
python3 workspace/run.py venues
python3 workspace/run.py symbols
python3 workspace/run.py cex-accounts
```

Exemplo CEX-only em Binance Futures:

```bash
CEX_ID=binance CEX_MARKET_TYPE=swap python3 workspace/run.py abrir ETH/USDT --modo somente-cex --margem-cex-usd 20 --alavancagem-cex 5
```

Delta neutro manual entre duas venues do mesmo tipo fica isolado em `abrir-par-delta-neutro` (`open-venue-pair`). Ele sempre abre uma perna comprada e uma perna vendida do mesmo símbolo, sem alterar `rodar-setups-live` (`setup-live`), `abrir --modo delta-neutro` (`open --execution-mode hedged`), `somente-dex` ou `somente-cex`:

```bash
# CEX/CEX: long Binance, short Kraken
python3 workspace/run.py abrir-par-delta-neutro BTC/USDT --comprado-em cex:binance --vendido-em cex:kraken --margem-usd 20 --alavancagem 5

# DEX/DEX: long Nado, short Hyperliquid builtin
python3 workspace/run.py abrir-par-delta-neutro BTC/USDT --comprado-em dex:nado --vendido-em dex:hyperliquid --margem-usd 20 --alavancagem 5
```

## Entrada padrão

Use sempre o wrapper OpenClaw:

```bash
python3 workspace/run.py setup-check
python3 workspace/run.py doctor
python3 workspace/run.py bootstrap
```

Depois, rode comandos operacionais pelo mesmo wrapper:

```bash
python3 workspace/run.py symbols
python3 workspace/run.py funding
python3 workspace/run.py kraken-accounts
python3 workspace/run.py simulate --symbol ETH/USDT
python3 workspace/run.py scenario-matrix --symbol ETH/USDT
python3 workspace/run.py status
```

O wrapper preserva o `workspace/cli.py` original, mas adiciona:

- `setup-check` sem dependências pesadas;
- `doctor` com checklist operacional;
- bootstrap previsível de `.venv` local;
- carregamento opcional de env seguro;
- estado/logs fora do repositório;
- bloqueio de comandos live sem confirmação.

## Env e secrets

Arquivo opcional fora do repo:

```text
~/.config/openclaw/trade-automatizado-openclaw.env
```

Fallback legado ainda aceito:

```text
~/.config/openclaw/delta-neutral-airdrop-farmer.env
```

Também pode customizar:

```bash
export DELTA_NEUTRAL_ENV_FILE=/caminho/seguro/delta-neutral.env
export DELTA_NEUTRAL_STATE_DIR=/caminho/seguro/state
export DELTA_NEUTRAL_LOG_DIR=/caminho/seguro/logs
export DELTA_NEUTRAL_VENV_DIR=/caminho/seguro/.venv
```

Para usar um env temporario sem salvar no ambiente OpenClaw:

```bash
python3 workspace/run.py --runtime-env /tmp/delta-runtime.env setup-check
python3 workspace/run.py setup-check --runtime-env /tmp/delta-runtime.env
```

Variáveis principais:

```env
NADO_OWNER_PRIVATE_KEY=***
NADO_PRIVATE_KEY=***
PRIVATE_KEY=
NADO_LINKED_SIGNER_PRIVATE_KEY=***
NETWORK=testnet
NADO_NETWORK=testnet
NADO_SUBACCOUNT_NAME=default_1  # opcional; ajuste só se usar nome customizado
NADO_REQUIRE_LINKED_SIGNER=true
NADO_ALLOW_OWNER_FALLBACK=false  # só para erro/mismatch; ausência de linked signer já usa owner

KRAKEN_API_KEY=***
KRAKEN_API_SECRET=***
KRAKEN_VENUE=futures
# sandbox NÃO vai aqui: configure em settings.json (venues.cex.kraken.sandbox).
# A variável KRAKEN_SANDBOX continua sendo lida, mas vence o arquivo.
KRAKEN_ACCOUNT=flex
KRAKEN_REQUIRE_SUBACCOUNT=false
KRAKEN_API_IS_SUBACCOUNT=false
KRAKEN_ALLOW_MAIN_ACCOUNT=false

TRADE_AUTOMATIZADO_CONFIRM_LIVE=false
DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=false

EXCHANGES=nado,kraken
VOLUME_ORDER=100
ORDER_TYPE=market
DRIFT_BPS=50
MAX_PAIR_LOSS_PCT=0.03
SLIPPAGE_BPS=100
PROTECTIVE_STOP_LOSS_PCT=0.03
PROTECTIVE_TAKE_PROFIT_PCT=0.03

EXECUTION_MODE=hedged
MARGIN_MODE=cross
NADO_MARGIN_MODE=isolated
KRAKEN_MARGIN_MODE=cross
MARGIN_USD=
NADO_MARGIN_USD=
KRAKEN_MARGIN_USD=
LEVERAGE=
NADO_LEVERAGE=
KRAKEN_LEVERAGE=
```

Alias legado aceito:

```env
NADO_PRIVATE_KEY=***
PRIVATE_KEY=
```

Prefira `NADO_OWNER_PRIVATE_KEY`. `PRIVATE_KEY` existe apenas para compatibilidade com envs legados. `CERTAINTY` aceita `70`, `70%` ou `0.70`; `UNIQUE_TREND` deve ser vazio, `LONG` ou `SHORT`.

## Estado local

Por padrão:

```text
~/.openclaw/state/trade-automatizado-openclaw/state.json
~/.openclaw/state/trade-automatizado-openclaw/setup_live_state.json
~/.openclaw/logs/trade-automatizado-openclaw/
```

Estados antigos em `~/.openclaw/state/delta-neutral-airdrop-farmer/` ainda são lidos se o novo caminho estiver vazio.

Esses arquivos ficam fora do Git e podem ser movidos via env.

## Comandos seguros

### Diagnóstico

```bash
python3 workspace/run.py setup-check
python3 workspace/run.py doctor
```

### Mercado/simulação

```bash
python3 workspace/run.py symbols
python3 workspace/run.py funding
python3 workspace/run.py setups
python3 workspace/run.py simulate --symbol all
python3 workspace/run.py scenario-matrix --symbol all
```

### Status

```bash
python3 workspace/run.py status
python3 workspace/run.py live-status
python3 workspace/run.py setup-live-status
python3 workspace/run.py kraken-accounts
```

### Dashboard do usuário

1. Rode os checks operacionais:

```bash
python3 workspace/run.py setup-check
python3 workspace/run.py doctor
```

2. Salve as credenciais fora do Git:

```bash
mkdir -p ~/.config/openclaw
cp workspace/.env.example ~/.config/openclaw/trade-automatizado-openclaw.env
```

Preencha no arquivo seguro as envs da Nado e da Kraken. Para o dashboard mostrar `Exposição real`, as credenciais precisam permitir leitura de posições. Para publicar sem consultar exchanges, use `--no-live-exposure`, mas isso não serve para o painel operacional live.

3. Valide leitura das contas antes de gerar o painel:

```bash
python3 workspace/run.py live-status
python3 workspace/run.py setup-live-status
```

4. Gere o HTML/JSON local:

```bash
python3 workspace/run.py dashboard
```

Isso atualiza:

```text
index.html
dashboard-data.json
```

5. Opcional: publique em um destino externo passando explicitamente o comando de deploy escolhido:

```bash
python3 workspace/run.py dashboard-publisher --once --deploy-command "<comando-deploy>"
```

6. Para manter atualização contínua local em foreground:

```bash
python3 workspace/run.py dashboard-publisher --loop --interval 60 --min-deploy-seconds 60 --no-deploy
```

7. Para manter atualização contínua local via systemd de usuário:

```bash
mkdir -p ~/.config/systemd/user
```

Crie `~/.config/systemd/user/delta-dashboard-publisher.service`:

```ini
[Unit]
Description=Refresh OpenClaw trade dashboard

[Service]
WorkingDirectory=%h/trade-automatizado-openclaw
ExecStart=%h/.openclaw/state/trade-automatizado-openclaw/.venv/bin/python workspace/dashboard_publisher.py --loop --interval 60 --min-deploy-seconds 60 --no-deploy
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

Ative:

```bash
systemctl --user daemon-reload
systemctl --user enable --now delta-dashboard-publisher.service
systemctl --user status delta-dashboard-publisher.service --no-pager
```

Por padrão o publisher consulta exposição live Nado/Kraken e grava em `live_exposures`. Use `--no-live-exposure` somente para rebuild offline.

O painel separa duas leituras:

- `Monitoradas`: operações gerenciadas pelo `setup-live`, com setup, entrada, stop, alvos/TPs e fechamento quando disponível.
- `Exposição real`: posições abertas detectadas diretamente nas exchanges, mesmo que ainda não estejam vinculadas a um setup monitorado.

Validação local recomendada:

```bash
jq '{updated_at, monitoradas:.summary.open_trades, live_exposure:.summary.live_exposure_count, erro:.live_exposures.error}' dashboard-data.json
```

Se `live-status` mostra mais ativos do que `summary.live_exposure_count`, o problema é sync de exposição real. Se `live_exposure_count` está correto mas `open_trades` está baixo, o setup-live está monitorando menos operações do que a exposição real aberta.

Checklist esperado no final:

- `index.html` e `dashboard-data.json` gerados na raiz da skill.
- Se houver publicação externa, `dashboard-data.json` acessível no destino configurado.
- `summary.live_exposure_count` igual à quantidade de posições abertas detectadas em `live-status`.
- `live_exposures.error` vazio.
- Serviço `delta-dashboard-publisher.service` ativo quando a atualização automática estiver habilitada.

## Comandos de trade

Comandos abaixo são bloqueados por padrão no wrapper:

```bash
python3 workspace/run.py abrir ETH/USDT --lado comprado --valor-nominal 20
python3 workspace/run.py rebalance
python3 workspace/run.py unwind
python3 workspace/run.py farm --interval 60
python3 workspace/run.py live-hedge --dry-run
python3 workspace/run.py live-sync --dry-run
python3 workspace/run.py rodar-setups-live --simular
```

Para uma execução live explicitamente aprovada:

```bash
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py abrir ETH/USDT --lado comprado --valor-nominal 20
```

Modos manuais aceitos:

```bash
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py abrir ETH/USDT --lado comprado --modo delta-neutro --valor-nominal 20
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py abrir ETH/USDT --lado comprado --modo somente-dex --modo-margem isolated --valor-nominal 20
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py abrir ETH/USDT --lado vendido --modo somente-cex --modo-margem cross --valor-nominal 20
```

Use sempre valores pequenos primeiro.

### Margin sizing e stop percentual

`--valor-nominal` (`--notional`) define o tamanho nominal. Quando quiser operar por margem, use `--margem-usd` (`--margin-usd`) junto com `--alavancagem` (`--leverage`):

```bash
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py abrir ETH/USDT --lado comprado --modo somente-dex --modo-margem isolated --margem-usd 20 --alavancagem 5
```

Nesse exemplo, a entrada valida o valor nominal operacional de `$100` contra o minimo real do ativo/venue. Se o ativo exigir `$100`, `--margem-usd 5 --alavancagem 5` gera `$25` de valor nominal e deve ser bloqueado por minimo do ativo, independentemente do setup.

Para testes controlados, `NADO_MIN_ORDER_NOTIONAL_USD=10` substitui o minimo de notional usado pela validacao local da skill. Isso nao altera regras reais da Nado; se a venue rejeitar ordens abaixo do minimo efetivo, a execucao vai falhar na resposta da Nado.

Para usar toda a margem em uma unica oportunidade e impedir novas entradas enquanto ela estiver aberta, use `--max-open-setups 1` ou `SETUP_LIVE_MAX_OPEN_SETUPS=1`.

Para auditar atualizacoes de perps entre Nado e Kraken sem abrir trade, use:

```bash
NADO_DISABLED_PERP_SYMBOLS=ADA/USDT,ARB/USDT python3 workspace/run.py asset-scan --spread-limit-pct 5 --max-suspect 20
```

O comando salva snapshot em `~/.openclaw/state/trade-automatizado-openclaw/asset_scan_state.json` e destaca ativos adicionados/removidos ou suspeitos por preco/spread.

Para cross margin na Nado, o bot pode dividir o orçamento da conta em slots e bloquear novas entradas por Maint. Margin Usage/stress:

```bash
python3 workspace/run.py rodar-setups-live --setup all --symbol all --modo somente-dex --modo-margem cross \
  --risk-profile moderate --stop-loss-pct 20 \
  --account-margin-reserve-pct 20 --slots-margem-conta 8 \
  --account-max-maint-usage-pct 80 --account-stress-pct 10
```

Sem `--margem-usd`, a margem por entrada vira `orcamento operacional / slots`; com `--margem-usd` explícito, o valor manual continua prevalecendo. `slots` aceita qualquer inteiro positivo. Em contas pequenas, prefira menos slots para manter cada ordem acima do mínimo da Nado; por exemplo, 8 slots com saldo ~$22.91 e reserva de 20% gera notional aproximado de $11.46 a 5x.

Para avisar quando uma entrada live for confirmada, defina o target principal por flag ou env. O canal principal pode ser Telegram, WhatsApp ou outro canal aceito pelo OpenClaw.

Exemplo Telegram + copia Discord:

```bash
python3 workspace/run.py rodar-setups-live ... \
  --notify-entry-channel telegram \
  --notify-entry-target <chat_id_ou_usuario> \
  --notify-entry-discord-channel-id <discord_channel_id>
```

ou:

```bash
SETUP_NOTIFY_ENTRY_ENABLED=true
SETUP_NOTIFY_ENTRY_CHANNEL=telegram
SETUP_NOTIFY_ENTRY_TARGET=<chat_id_ou_usuario>
DISCORD_BOT_TOKEN=<salvo-no-secret-manager>
SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID=<discord_channel_id>
SETUP_NOTIFY_DISCORD_NATIVE_EMBED=false
SETUP_NOTIFY_FALLBACK_OPENCLAW=true
SETUP_NOTIFY_DISCORD_BOX=false
SETUP_NOTIFY_TRADINGVIEW_IMAGE=true
SETUP_NOTIFY_DISCORD_MENTION=none
```

Exemplo WhatsApp como destino principal:

```bash
python3 workspace/run.py setup-live ... \
  --notify-entry-channel whatsapp \
  --notify-entry-target <chat_id_ou_destino_whatsapp>
```

ou:

```bash
SETUP_NOTIFY_ENTRY_ENABLED=true
SETUP_NOTIFY_ENTRY_CHANNEL=whatsapp
SETUP_NOTIFY_ENTRY_TARGET=<chat_id_ou_destino_whatsapp>
```

Para WhatsApp, o destino deve ser o identificador aceito pelo conector OpenClaw configurado, por exemplo número E.164 em conversa direta ou JID/id do grupo quando o provider expuser esse formato. Se quiser manter WhatsApp como principal e ainda copiar no Discord, use `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID=<discord_channel_id>` junto.

O mesmo caminho vale para `setup-live --dry-run`: quando o dry-run encontra uma oportunidade, ele envia o texto formatado para o canal principal configurado. Com `SETUP_NOTIFY_TRADINGVIEW_IMAGE=true`, WhatsApp e Discord recebem também o PNG do TradingView como anexo/mídia da notificação; updates, stops e fechamentos continuam podendo sair só como texto.

Esse aviso cobre entradas confirmadas do `setup-live` em `dex_only`, `cex_only` e `hedged`.

Para agentes com limite de leitura de 200 linhas, use primeiro [`map/discord-zeus-delivery.md`](map/discord-zeus-delivery.md), que referencia arquivo e linhas de cada ponto. Para o contrato canônico completo do formato Discord de produção, incluindo H1 (`# `), duas linhas após título, subtítulos/valores/porcentagens em negrito, emojis, imagem TradingView, mapa de indicadores por setup e envio multipart, veja [`doc referencia/05-entrega-discord-zeus.md`](doc%20referencia/05-entrega-discord-zeus.md). Ignore guias posteriores/conflitantes que adicionem `ZEUS TRADE`, `Venue`, `P&L Amount`, `PNL potencial max`, histórico de eventos, bloco de código ou embed nativo ao formato; relação risco/retorno só entra na leitura técnica quando vier do sinal. Para exemplos reais com PNG, overlay, config TradingView e payload Discord, veja [`examples/discord-zeus/README.md`](examples/discord-zeus/README.md). Quando `setup-live` entregar no Discord, o padrão válido é texto puro com Markdown do Discord e gráfico abaixo na mesma mensagem (`payload_json.content` + `files[0]`); embed nativo, bloco de código, ticket curto ou entrega sem imagem não equivalem ao formato de produção.

Para usar versões calibradas no live, prefira:

- `grid-strict` — variante mais conservadora do grid, com SMA50, desvio ampliado, RSI baixo, TP curto e SL controlado.
- `grid` — variante historica do grid, mantida por compatibilidade; para live novo, prefira `grid-strict`.
- `bollinger-mean-reversion` — exige 0.20 ATR fora da banda, RSI e volume acima da média para reduzir entrada fraca.
- `institutional-strict` — usa EMA50, RSI 52-65, volume>SMA20x1.15, EMA gap>0.10%, MACD gap 0.20%-0.50%, alvos 1R/1.5R/2R/3R e timeout de 8 candles. Prefira esta variante para live direcional.
- `low-stoch-storm` — por padrão opera apenas BTC/ETH/SOL/XRP até nova validação operacional por ativo.
- `divergence-and-volume-*` — setup experimental restrito por padrão a ETH/XMR até nova validação operacional por timeframe.


Em `setup-live`, o take profit vem do setup e o stop pode ser definido na execucao:

```bash
python3 workspace/run.py rodar-setups-live --simular --setup institutional-strict --symbol allowlist --modo somente-dex --modo-margem cross --margem-usd 20 --hybrid-profile moderado --stop-loss-preset 20
python3 workspace/run.py rodar-setups-live --simular --setup institutional-strict --symbol allowlist --modo somente-cex --margem-usd 20 --hybrid-profile moderado --stop-loss-pct 15
```

Presets de stop aceitos: `10`, `20`, `30`, `conservador`, `moderado`, `degen`.

Politica opcional para mover o stop conforme alvos do setup:

```bash
python3 workspace/run.py rodar-setups-live --modo-stop-alvo desligado
python3 workspace/run.py rodar-setups-live --modo-stop-alvo entrada-no-tp1
python3 workspace/run.py rodar-setups-live --modo-stop-alvo escada
```

- `desligado`/`off`: stop fixo original, comportamento padrao.
- `entrada-no-tp1`/`breakeven_on_tp1`: ao bater TP1, stop vai para o preco de entrada; nos proximos alvos permanece na entrada.
- `escada`/`ladder`: TP1 move stop para entrada; TP2 move para TP1; TP3 move para TP2; ultimo alvo fecha o restante.

Tambem pode ser configurado por env: `SETUP_LIVE_TARGET_STOP_MODE=off|breakeven_on_tp1|ladder`.

Se um TP parcial nativo da Nado ficar abaixo do minimo aceito pela venue, a skill nao deve bloquear a entrada por isso; ela registra o motivo e mantem o alvo no gerenciamento do setup.

Revisao operacional do Low Stoch Storm: manter BTC, ETH, SOL e XRP como universo padrão. Nao usar Low Stoch Storm amplo em todos os ativos sem filtro adicional por ativo/regime.

### Fallback privilegiado

Na Nado, a regra operacional é: se `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a skill usa automaticamente o owner da wallet/conta configurada. Se houver linked signer configurado, mas ele falhar validação/on-chain ou divergir, o fallback para owner continua privilegiado.

Para fallback privilegiado por erro/mismatch de linked signer na Nado ou uso pontual de main account na Kraken, as duas condicoes precisam ser verdadeiras:

```env
DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true
NADO_ALLOW_OWNER_FALLBACK=true
KRAKEN_ALLOW_MAIN_ACCOUNT=true
```

Use essas flags somente na execucao em que o usuario pedir esse comportamento. Sem `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`, as flags de fallback sao ignoradas.

## Instalação manual local

```bash
git clone https://github.com/CodeLab-IntusHub/trade-automatizado-openclaw.git
cd trade-automatizado-openclaw
python3 workspace/run.py setup-check
python3 workspace/run.py bootstrap
python3 workspace/run.py doctor
```

## Validação dev

```bash
python3 -m json.tool skill.json
python3 -m compileall -q workspace test
python3 workspace/run.py setup-check
python3 workspace/run.py bootstrap
python3 workspace/run.py --help
python3 workspace/run.py symbols --help
```

Quando as dependências estiverem instaladas:

```bash
python3 -m pytest -q
```

Para validar o dashboard no navegador com Playwright:

```bash
npm ci
npm run playwright:install
npm run test:e2e
```

O Git versiona `package.json`, `package-lock.json`, `playwright.config.js`, `tests/e2e/` e o workflow. `node_modules/`, browsers baixados, `playwright-report/` e `test-results/` ficam fora do Git e são recriados localmente ou no GitHub Actions.

## Limites conhecidos

- Nado live trade prefere linked signer configurado e validado; se ele estiver ausente, usa owner da wallet/conta configurada. Fallback owner por erro/mismatch exige confirmação explícita.
- Kraken requer API key dedicada/sem saque na conta correta; subconta é opcional e não bloqueia por si só.
- O wrapper não remove risco de mercado; ele só reduz risco operacional.
- Autorização sem private key só é viável com wallet/session externa; automação unattended de trading exige signer/API key limitada em secret manager.

## Changelog

Veja [`CHANGELOG.md`](CHANGELOG.md).

## Licença

Licença proprietária — veja [`LICENSE`](LICENSE).

<!-- OPENCLAW_README_WIZARD_PATHS_START -->

## Wizard: iniciante ou avançado

Esta skill segue o padrão OpenClaw de wizard por caminhos. No início da configuração, o usuário escolhe:

| Caminho | Para quem | Como funciona |
|---|---|---|
| Iniciante | usuário que quer orientação rápida e segura | passo a passo guiado, linguagem simples, defaults conservadores |
| Avançado | usuário/operator que quer controle fino | parâmetros completos, validações/dry-run quando aplicável, rastreabilidade de runtime/release |

O fluxo completo fica em `references/onboarding-questionario.md` e começa pela escolha de DEX/CEX. O guia detalhado em `references/onboarding-detalhado.md` traz passo a passo para Nado, Hyperliquid, Kraken, Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io, outras CEXs via CCXT e outras DEXs via adapter. Segredos nunca devem ser enviados no chat.

<!-- OPENCLAW_README_WIZARD_PATHS_END -->

<!-- OPENCLAW_SECRET_GUIDANCE_START -->

## Chaves e segredos

Por segurança, não envie API keys, tokens, webhooks, OAuth, private keys ou seeds pelo chat.

- Chaves de IA/LLM: `secret manager > Chaves LLM`
- Chaves de serviço/API externa: `secret manager > Chaves de Serviço`
- OAuth Anthropic: `secret manager > OAuth Token`

Depois de configurar, basta dizer que a chave já está salva.

<!-- OPENCLAW_SECRET_GUIDANCE_END -->
