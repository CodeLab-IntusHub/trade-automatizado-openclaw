# Guia de Instalacao

Passo a passo completo para preparar o projeto, migrar do ambiente antigo e validar o modelo recomendado: subconta/conta isolada quando a corretora/DEX oferecer esse recurso, com decisão final do usuário e sem hard-code; no mínimo API key dedicada sem saque quando não usar subconta.

## 1. Pre-requisitos

- Container OpenClaw ou Linux equivalente
- Python 3.12 com `pip` e `venv`
- acesso a testnet da Nado
- wallet Nado/Ink preparada; `NADO_SUBACCOUNT_NAME` só se usar nome customizado ou se o diagnóstico exigir
- linked signer configurado na Nado quando quiser usar signer limitado; opcional, pois owner fallback e aceito quando não houver linked signer
- conta Kraken Futures Demo ou ambiente equivalente para sandbox
- conta Kraken correta para a estratégia; conta separada/subconta é recomendada para isolamento, mas não obrigatória
- API key Kraken dedicada para trading/leitura, sem permissão de saque; preferencialmente criada na subconta/conta isolada

Checagens uteis:

```bash
python3 --version
python3 -m pip --version
```

## 2. Criar o ambiente Python

```bash
cd trade-automatizado-openclaw
python3 workspace/run.py bootstrap
# dependências instaladas pelo wrapper
# copie as envs para ~/.config/openclaw/trade-automatizado-openclaw.env ou secret manager
```

Calibracao de setup: copie `settings.example.json` para `settings.json` (time) ou
`settings.local.json` (operador). Detalhes em `Docs/features/configuracao-de-setups.md`.

Dependencias-chave:
- `ccxt>=4.5.50`
- `setuptools<81`
- `nado-protocol==0.3.5` — **opcional**, exigido so por `DEX_ID=nado`: `pip install -r workspace/requirements-nado.txt`. Exige toolchain de build nativo (web3 + extensoes C); as demais venues rodam por `ccxt`.

## 3. Configurar o `.env`

Salve as variáveis no secret/env manager do OpenClaw ou em `~/.config/openclaw/trade-automatizado-openclaw.env` fora do Git e preencha o modelo abaixo. O wrapper ainda aceita o arquivo legado `~/.config/openclaw/delta-neutral-airdrop-farmer.env` como fallback.

### Nado

```env
NADO_OWNER_PRIVATE_KEY=0x...
NADO_PRIVATE_KEY=0x...
NADO_LINKED_SIGNER_PRIVATE_KEY=0x...
NADO_NETWORK=testnet
NADO_SUBACCOUNT_NAME=default_1  # opcional; ajuste só se usar nome customizado
NADO_REQUIRE_LINKED_SIGNER=true
NADO_FEE_TIER=entry
NADO_ALLOW_OWNER_FALLBACK=false
```

Regras:
- `NADO_OWNER_PRIVATE_KEY` e o nome canonico
- `NADO_PRIVATE_KEY` continua aceito como alias legado
- `NADO_LINKED_SIGNER_PRIVATE_KEY`, quando configurado, precisa ser o signer vinculado on-chain ao contexto/conta usado pela Nado
- se `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, o projeto usa automaticamente o owner da wallet/conta configurada para trades Nado
- owner fallback por erro/mismatch de linked signer so e permitido com `NADO_ALLOW_OWNER_FALLBACK=true` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`

### Kraken

```env
KRAKEN_API_KEY=***
KRAKEN_API_SECRET=***
KRAKEN_VENUE=futures
# sandbox NAO vai aqui: configure em settings.json (venues.cex.kraken.sandbox).
# KRAKEN_SANDBOX continua sendo lida, mas vence o arquivo -- ver Docs/features/sandbox-por-venue.md.
KRAKEN_ACCOUNT=flex
KRAKEN_ACCOUNT_SYMBOL=
KRAKEN_REQUIRE_SUBACCOUNT=false
KRAKEN_API_IS_SUBACCOUNT=false
KRAKEN_ALLOW_MAIN_ACCOUNT=false
```

Regras:
- a segregacao recomendada vem de subconta/conta isolada; no mínimo use API key dedicada sem saque
- `KRAKEN_ACCOUNT` e `KRAKEN_ACCOUNT_SYMBOL` sao contexto de leitura/organizacao
- `KRAKEN_API_IS_SUBACCOUNT=true` so deve ser usado quando a API key realmente vier da subconta dedicada; por padrao deixe `false`
- para API key real da Kraken Futures, declare `venues.cex.kraken.sandbox: false` no `settings.json` (a venue nasce apontada para sandbox)
- main account fallback so e permitido com `KRAKEN_ALLOW_MAIN_ACCOUNT=true` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`

### Parametros de trade

```env
VOLUME_ORDER=100
DRIFT_BPS=50
MAX_PAIR_LOSS_PCT=0.03
SLIPPAGE_BPS=100
PROTECTIVE_STOP_LOSS_PCT=0.03
PROTECTIVE_TAKE_PROFIT_PCT=0.03
PROTECTIVE_STOP_TRIGGER_SLIPPAGE_PCT=0.01
SETUP_ENTRY_MIN_NADO_BALANCE_RATIO=0.05
SETUP_ENTRY_MIN_KRAKEN_MARGIN_RATIO=0.20
MARGIN_USD=
NADO_MARGIN_USD=
KRAKEN_MARGIN_USD=
```

Notas:
- `MAX_PAIR_LOSS_PCT` continua sendo o stop global correto do par delta-neutral
- `PROTECTIVE_STOP_LOSS_PCT` anexa stop loss reduce-only nas pernas novas abertas pelo bot
- `PROTECTIVE_TAKE_PROFIT_PCT` anexa take profit reduce-only nas pernas novas abertas pelo bot
- `PROTECTIVE_STOP_TRIGGER_SLIPPAGE_PCT` controla a folga de execucao do trigger, principalmente na Nado
- `MARGIN_USD` e os overrides por venue permitem calcular notional como margem * leverage
- o minimo de entrada e validado por ativo/venue, nao por setup; TP/SL parcial nativo abaixo do minimo nao deve impedir entrada

### Parametros por execucao

Prefira passar stop e margem no comando quando precisar de flexibilidade:

```bash
python3 workspace/run.py setup-live --dry-run --setup institutional-strict --symbol all --execution-mode dex_only --margin-mode cross --margin-usd 20 --hybrid-profile moderado --stop-loss-preset 20
python3 workspace/run.py open ETH/USDT --side long --execution-mode cex_only --margin-usd 20 --leverage 5
```

Presets de stop aceitos em `setup-live`: `10`, `20`, `30`, `conservador`, `moderado`, `degen`.

Para usar um `.env` efemero sem salvar no ambiente OpenClaw:

```bash
python3 workspace/run.py --runtime-env /tmp/delta-runtime.env setup-check
python3 workspace/run.py setup-check --runtime-env /tmp/delta-runtime.env
```

### Catalogo de setups

O projeto tambem expõe um catalogo de setups operacionais inspirado no estudo externo monitorado:
- `grid`
- `delta-neutral`

Comandos:

```powershell
python3 workspace/run.py setups
```

## 4. Configurar API key dedicada na Kraken (subconta opcional)

Este fluxo e para ambiente real da Kraken Futures, nao para demo. Subconta e recomendada para isolamento quando a corretora oferecer esse recurso, mas opcional: use este caminho se quiser master + subaccount; caso contrario, crie API key dedicada sem saque na conta correta.

Fontes oficiais:
- [Understanding Derivatives subaccounts](https://support.kraken.com/articles/360042809671-understanding-derivatives-subaccounts)
- [How to unlock Derivatives trading](https://support.kraken.com/articles/360022618012-how-to-unlock-derivatives-trading)
- [How to create an API key for Kraken Derivatives](https://support.kraken.com/articles/360022839451-how-to-create-an-api-key-for-kraken-derivatives)
- [Kraken Futures subaccounts page](https://futures.kraken.com/trade/subaccounts)
- [Kraken Futures support form](https://support.kraken.com/forms/360000286871)

### Passo a passo opcional de subconta

1. Crie uma nova conta Kraken para ser a subconta.
   A Kraken informa que a subconta e uma conta Kraken separada.
2. Verifique essa nova conta.
3. Entre nessa nova conta e habilite Derivatives.
   O fluxo oficial e abrir o Kraken Pro, ir a um mercado de Derivatives e clicar em `Unlock Derivatives`.
4. A partir do email da conta master, abra um ticket no suporte de Futures pedindo o vinculo com a conta da subconta.
   No pedido, informe o email da conta SSO que deve virar subconta.
5. Abra o email da subconta e confirme o vinculo.
6. Depois do vinculo, abra `futures.kraken.com/trade/subaccounts`.
7. Transfira saldo da master para a subconta.
   A Kraken informa que os fundos podem ser movidos entre master e subconta e que positions/margin ficam segregadas por subconta.
8. Agora faca login diretamente na subconta.
   A Kraken informa que o sign-in e separado por subconta.
9. Na subconta, abra `Settings` > `API` > `Create Key`.
10. Gere a chave com:
    - `General API: Full Access`
    - `Withdrawal API: No Access`
11. Salve a `Public key` e a `Private key` na hora.
    A Kraken informa que a private key aparece uma vez so.
12. Ajuste o env seguro fora do Git para o ambiente real:

```env
KRAKEN_API_KEY=***
KRAKEN_API_SECRET=***
KRAKEN_VENUE=futures
# sandbox NAO vai aqui: configure em settings.json (venues.cex.kraken.sandbox).
# KRAKEN_SANDBOX continua sendo lida, mas vence o arquivo -- ver Docs/features/sandbox-por-venue.md.
KRAKEN_ACCOUNT=flex
KRAKEN_ACCOUNT_SYMBOL=
KRAKEN_REQUIRE_SUBACCOUNT=false
KRAKEN_API_IS_SUBACCOUNT=true  # somente porque este caminho usa subconta real
```

13. Valide com:

```powershell
python3 workspace/run.py kraken-accounts
```

O esperado:
- `trading=safe`
- sem indicacao de conta master
- fingerprint novo da API key no log

### Observacoes importantes

- API keys sao geradas e controladas separadamente por subconta.
- Positions sao margined no nivel da subconta.
- Sign-ins sao separados por subconta.
- Withdrawals a partir da subconta sao bloqueados; a Kraken orienta mover fundos de volta para a master para sacar.
- Se voce usar API key real, o projeto precisa estar com `venues.cex.kraken.sandbox: false` no `settings.json`.

## 4A. Conta Kraken separada para o bot também é válida

Se voce quer apenas impedir que o bot opere na conta principal, a alternativa mais simples e usar uma segunda conta Kraken completamente separada, sem pedir o vinculo formal de subconta.

Fonte oficial:
- [Account Management FAQ](https://support.kraken.com/hc/articles/account-management-faq)
- [How to unlock Derivatives trading](https://support.kraken.com/articles/360022618012-how-to-unlock-derivatives-trading)
- [How to create an API key for Kraken Derivatives](https://support.kraken.com/articles/360022839451-how-to-create-an-api-key-for-kraken-derivatives)

### Passo a passo

1. Saia da conta Kraken principal.
2. Crie uma nova conta Kraken com outro email.
3. Verifique essa nova conta.
4. Entre nela pelo [Kraken Pro](https://pro.kraken.com).
5. Abra um mercado de Derivatives e clique em `Unlock Derivatives`.
6. Aceite os termos e finalize a habilitacao.
7. Faca o funding dessa conta separada.
8. Ainda logado nessa conta separada, abra `Settings` > `API` > `Create Key`.
9. Gere a chave com:
   - `General API: Full Access`
   - `Withdrawal API: No Access`
10. Salve a `Public key` e a `Private key`.
11. Ajuste o env seguro fora do Git assim:

```env
KRAKEN_API_KEY=***
KRAKEN_API_SECRET=***
KRAKEN_VENUE=futures
# sandbox NAO vai aqui: configure em settings.json (venues.cex.kraken.sandbox).
# KRAKEN_SANDBOX continua sendo lida, mas vence o arquivo -- ver Docs/features/sandbox-por-venue.md.
KRAKEN_ACCOUNT=flex
KRAKEN_ACCOUNT_SYMBOL=
KRAKEN_REQUIRE_SUBACCOUNT=false
KRAKEN_API_IS_SUBACCOUNT=false
```

12. Valide com:

```powershell
python3 workspace/run.py kraken-accounts
```

O esperado:
- `trading=safe`
- nenhuma indicacao de conta master
- fingerprint novo no log

### Trade-offs

- Esse caminho isola o bot da conta principal de forma pratica e simples.
- A Kraken diz que multiplas contas separadas sao tecnicamente possiveis, mas desencorajadas por complexidade.
- Contas separadas nao compartilham saldo, volume, fee tier, verificacao nem transferencia interna.
- Se no futuro voce quiser transferencia interna e agrupamento de volume, ai vale migrar para o modelo oficial `master + sub-account`.

## 5. Migrar do ambiente antigo

Snapshot conhecido em 22/04/2026:
- Nado ainda referenciado em `default`
- Kraken ainda em `KRAKEN_API_IS_SUBACCOUNT=false`
- operacao anterior validada em testnet/sandbox
- relatorios operacionais em:
  - `workspace/batch-open-20260422-131925.json`
  - `workspace/batch-status-20260422-132159.json`

Passos de migração recomendados:

1. Zere qualquer posicao aberta do ambiente antigo.
2. Troque o `.env` para o owner signer, linked signer quando existir e API key dedicada da Kraken.
3. Ajuste `NADO_SUBACCOUNT_NAME` somente se o runtime/doctor indicar nome diferente do default.
4. Valide a Kraken com `kraken-accounts`.
5. So depois abra uma nova posicao.

Observacao:
- se existir um `state.json` legado, a recomendacao operacional e desmontar o ambiente antigo antes de usar o modo estrito

## 6. Configurar dashboard do usuario do zero

O dashboard e parte padrao da skill. Ele publica `index.html` e `dashboard-data.json` e separa:
- `Monitoradas`: operacoes gerenciadas pelo `setup-live`.
- `Exposicao real`: posicoes abertas detectadas diretamente nas venues escolhidas.

### 6.1 Preparar runtime

```bash
cd trade-automatizado-openclaw
python3 workspace/run.py bootstrap
python3 workspace/run.py setup-check
python3 workspace/run.py doctor
```

### 6.2 Configurar env seguro

Crie o arquivo fora do Git:

```bash
mkdir -p ~/.config/openclaw
cp workspace/.env.example ~/.config/openclaw/trade-automatizado-openclaw.env
```

Preencha as envs das venues escolhidas no arquivo seguro. Para o painel mostrar `Exposicao real`, as credenciais precisam permitir leitura de posicoes. `--no-live-exposure` serve apenas para rebuild offline.

Valide antes de publicar:

```bash
python3 workspace/run.py live-status
python3 workspace/run.py setup-live-status
```

### 6.3 Gerar local

```bash
python3 workspace/run.py dashboard
```

Arquivos esperados:

```text
index.html
dashboard-data.json
```

Valide o JSON local:

```bash
jq '{updated_at, monitoradas:.summary.open_trades, live_exposure:.summary.live_exposure_count, erro:.live_exposures.error}' dashboard-data.json
```

O esperado:
- `updated_at` recente;
- `live_exposure` igual ao total de posicoes abertas visto em `live-status`;
- `erro` vazio;
- `monitoradas` pode ser menor que `live_exposure` quando o setup-live estiver acompanhando menos entradas do que a exposicao real.

### 6.4 Publicacao externa opcional

O publisher nao publica fora por padrao. Para enviar para algum host externo, passe o comando explicitamente:

```bash
python3 workspace/run.py dashboard-publisher --once --deploy-command "<comando-deploy>"
```

### 6.5 Manter atualizacao automatica

Modo foreground local:

```bash
python3 workspace/run.py dashboard-publisher --loop --interval 60 --min-deploy-seconds 60 --no-deploy
```

Modo systemd de usuario:

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

Ative e valide:

```bash
systemctl --user daemon-reload
systemctl --user enable --now delta-dashboard-publisher.service
systemctl --user status delta-dashboard-publisher.service --no-pager
```

### 6.7 Troubleshooting do dashboard

- `live-status` mostra mais ativos que o dashboard: problema no sync de exposicao real.
- `live_exposure` correto mas `monitoradas` baixo: o setup-live esta gerenciando menos operacoes do que a exposicao real aberta.
- `live_exposures.error` preenchido: revise as envs das venues escolhidas e a permissao de leitura.
- HTML atualizado mas dados antigos: confira se `dashboard-data.json` mudou no destino configurado e se o auto-refresh JSON nao foi bloqueado por cache.

## 7. Validar sem abrir trade

Rode estes comandos primeiro:

```powershell
python3 workspace/run.py symbols
python3 workspace/run.py funding
python3 workspace/run.py kraken-accounts
```

O que conferir:
- `symbols` lista os pares comuns
- `funding` responde sem erro de credencial
- `kraken-accounts` precisa sair com `trading=safe`

Se `kraken-accounts` sair `unsafe`, nao siga para `open`.

## 8. Teste controlado de trade

Quando o ambiente estiver `safe`, rode:

```powershell
python3 workspace/run.py open ETH/USDT --side long --notional 20
python3 workspace/run.py status
python3 workspace/run.py unwind
```

O esperado:
- o CLI loga o contexto ativo de Nado e Kraken antes do trade
- `open` so abre com credenciais válidas e sizing aprovado; linked signer e subconta/conta isolada são recomendados para reduzir risco, mas não são requisito global
- `status` mostra notional solicitado e efetivo, mais o contexto salvo
- `unwind` fecha apenas no mesmo contexto em que a posicao foi aberta

## 9. Simulacao e exploracao

Os comandos abaixo nao dependem de abrir posicao:

```powershell
python3 workspace/run.py simulate --symbol all --setup delta --profiles 1x,2x,3x
python3 workspace/run.py scenario-matrix --symbol ETH/USDT --setup funding
```

## 10. Validacao de testes locais

```powershell
.\.venv\Scripts\python.exe -m pytest test\test_v2.py -q
.\.venv\Scripts\python.exe test\test_smoke.py
python3 workspace/run.py --help
```

## 11. Troubleshooting

### `NADO_LINKED_SIGNER_PRIVATE_KEY ausente`

Causa:
- `NADO_LINKED_SIGNER_PRIVATE_KEY` nao esta configurada no `.env`/secret manager

Acao:
- se quiser usar linked signer, preencher `NADO_LINKED_SIGNER_PRIVATE_KEY`
- se nao quiser, manter ausente e usar owner fallback conforme regra local
- quando houver linked signer, confirmar que ele bate com o signer on-chain do contexto usado

### `O linked signer configurado nao bate com o linked signer on-chain`

Causa:
- a chave local nao corresponde ao linked signer real do contexto usado

Acao:
- corrigir/remover a chave
- confirmar `NADO_SUBACCOUNT_NAME` somente se o runtime/doctor indicar nome customizado

### `KRAKEN_API_IS_SUBACCOUNT=false`

Causa:
- informativo: a API atual nao foi declarada como subconta, e isso nao bloqueia por si so

Acao:
- se voce realmente usa subconta dedicada, marque `KRAKEN_API_IS_SUBACCOUNT=true`
- caso contrario, mantenha `false` e valide a API key dedicada/sem saque; prefira conta isolada quando possível

### API real nao funciona no projeto

Causa:
- a Kraken nasce apontada para sandbox e nada declarou o contrario; ou ha uma
  variavel `KRAKEN_SANDBOX`/`CEX_SANDBOX` no `.env` ou no `config.env`, que
  vence o `settings.json` (o carregamento avisa quando isso acontece)

Acao:
- declarar `venues.cex.kraken.sandbox: false` no `settings.json`
- conferir se `KRAKEN_SANDBOX`/`CEX_SANDBOX` nao estao definidas no ambiente:
  enquanto existirem, a chave do arquivo nao tem efeito

### `A API key atual aparenta ser de conta master`

Causa:
- a metadata da Kraken identifica a credencial como conta principal

Acao:
- revisar se essa é a conta correta da estratégia
- para isolamento maior, gerar API key em conta separada/subconta; não habilitar saque

### `Nao foi possivel validar a metadata da Kraken`

Causa:
- falha de endpoint, permissao ou ambiente

Acao:
- rerodar `kraken-accounts`
- confirmar a API key dedicada
- confirmar se o sandbox/demo esta respondendo

### Warning de `pkg_resources`

Causa:
- dependencia upstream `eth_keyfile`

Acao:
- hoje nao bloqueia execucao
- manter `setuptools<81`

## 12. Documentacao complementar

- [README.md](README.md)
- [SKILL.md](SKILL.md)
- [doc referencia](doc%20referencia/)


## Venues configuráveis

Por padrão a skill usa `DEX_ID=nado` e `CEX_ID=kraken`. O wizard lista as principais venues: DEX `nado` e `hyperliquid`; CEX `kraken`, `binance`, `bybit`, `okx`, `kucoin`, `mexc`, `bitget` e `gateio`. Para trocar a CEX, use qualquer `exchange_id` suportado pelo CCXT e configure `CEX_API_KEY`, `CEX_API_SECRET` e, quando necessário, `CEX_API_PASSWORD`.

Para usar Hyperliquid como DEX, defina `DEX_ID=hyperliquid` e salve `HYPERLIQUID_WALLET_ADDRESS`/`HYPERLIQUID_PRIVATE_KEY` no Secret Manager; `HYPERLIQUID_VAULT_ADDRESS` é opcional. Para outras DEXs custom, forneça `DEX_ADAPTER_MODULE=pacote.modulo:Classe` e dados não sensíveis em `DEX_CONFIG_JSON`. O adapter deve implementar a interface de trading usada pela skill (`get_symbol_to_product_map`, preço médio, posições, arredondamento, ordens market, SL/TP e `assert_trade_ready`).

Comandos de diagnóstico:

```bash
python3 workspace/run.py venues
python3 workspace/run.py symbols
python3 workspace/run.py cex-accounts
```

Exemplo CEX-only em Binance Futures:

```bash
CEX_ID=binance CEX_MARKET_TYPE=swap python3 workspace/run.py open ETH/USDT --execution-mode cex_only --cex-margin-usd 20 --cex-leverage 5
```
