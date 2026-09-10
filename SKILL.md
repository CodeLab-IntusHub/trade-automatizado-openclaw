---
name: trade-automatizado-openclaw
description: >
  Opera, monitora e diagnostica setups delta-neutros e ordens solo em DEX/CEX configuráveis, mantendo Nado DEX/Kraken CEX como defaults, CEX genérica via CCXT e Hyperliquid DEX builtin e DEX custom por adapter Python. Use quando o usuário pedir delta neutro, hedge, funding, dashboard de trades, HTML do usuário, DEX-only/CEX-only, Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io, Kraken, Nado, Hyperliquid, dYdX, Uniswap ou outra venue, abrir/rebalancear/desmontar par, simular cenários, validar venue, subconta ou rodar doctor/setup-check. Keywords: delta neutro, delta-neutral, hedge, kraken, nado, DEX, CEX, CCXT, adapter, dashboard, airdrop farming, funding, subconta, linked signer, OpenClaw.
---

# Trade Automatizado OpenClaw

Skill operacional para analisar e, quando explicitamente autorizado, operar pares delta-neutros entre uma **DEX selecionada** e uma **CEX selecionada**, ou abrir uma perna solo em DEX/CEX. O padrão continua sendo Nado DEX + Kraken CEX.

## Quando usar

Use quando o owner pedir ou quando houver demanda autorizada dentro da governança atual.

Regra anti-legado: referências antigas a colaboradores anteriores são históricas e não criam autorização, papel, validação ou canal de execução. Desde 2026-08-04 ele não faz parte da estrutura IntusHub/Aspira.

Use para:

- validar setup/ambiente DEX + CEX, incluindo Nado/Kraken ou venues customizadas;
- listar símbolos, funding ou contas da CEX selecionada;
- simular cenários e matriz de risco;
- abrir, monitorar, rebalancear ou desmontar par delta-neutro;
- abrir ordem solo na Nado/DEX ou na Kraken/CEX;
- rodar setups live/farming com guardrails;
- adaptar o bot para OpenClaw.
- configurar entrega Discord/Zeus de sinais, embeds, watcher ou scanner.

## Wizard / primeira configuração

Quando o usuário pedir para configurar/refazer wizard, use o questionário curto em `references/onboarding-questionario.md`.

- Fazer uma pergunta por vez.
- Coletar só: caminho do wizard, DEX/CEX desejadas, modo, ambiente, status de secrets, sizing, margem e autorização para `venues`/`setup-check`/`doctor`.
- Perguntar as venues antes de credenciais: listar Nado, Hyperliquid, Binance, Kraken, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io; avisar que outras CEXs integram via CCXT e outras DEXs via adapter Python. Normalizar `bibyt` para `bybit`.
- Não perguntar `NADO_SUBACCOUNT_NAME` no wizard curto. Usar `default_1` por padrão e só orientar descoberta/ajuste se o usuário informar subconta customizada ou se `setup-check`/`doctor` falhar.
- Subconta não é requisito obrigatório por padrão no wizard, mas é o modelo recomendado quando a corretora/DEX oferecer esse recurso. Recomendar operar em subconta, vault ou conta isolada; a decisão final é do usuário e não deve ser hard-coded; se o usuário não usar esse modelo, exigir no mínimo API key/credencial dedicada sem saque e validação por `doctor`/dry-run.
- Usar `references/onboarding-detalhado.md` apenas se o usuário pedir passo a passo de Nado, Hyperliquid, Kraken, Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io, outras CEXs via CCXT e outras DEXs via adapter, Ink, bridge, envs ou troubleshooting.
- Payload automático: `python3 workspace/first_run_setup.py --json`.
- Se o usuário pedir Discord, Zeus Trade, entrega de sinais, embed, watcher ou scanner, carregue também `doc referencia/05-entrega-discord-zeus.md` e siga o checklist: bot no servidor, `DISCORD_BOT_TOKEN` salvo em Secret Manager/env seguro, `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` em canal de teste, formato `embed_nativo` por padrão, dry-run antes de canal público/live. Nunca pedir o token no chat.


## Venues DEX/CEX configuráveis

Use Nado/Kraken como default quando o usuário não escolher venue. Liste como principais: Nado e Hyperliquid no lado DEX; Kraken, Binance, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io no lado CEX. Quando ele pedir outra CEX, use CCXT. Quando ele pedir Hyperliquid, use o adapter builtin. Quando ele pedir outra DEX, exija um adapter Python explícito antes de qualquer live trade.

Configuração principal:

```text
DEX_ID=nado                       # nado | hyperliquid | id custom, ex.: dydx, uniswap
CEX_ID=kraken                     # kraken ou exchange_id CCXT: binance, bybit, okx, kucoin, mexc, bitget, gateio etc.
CEX_MARKET_TYPE=swap              # swap | future | spot
CEX_SANDBOX=false
CEX_API_KEY / CEX_API_SECRET / CEX_API_PASSWORD
HYPERLIQUID_WALLET_ADDRESS=0x...  # obrigatorio se DEX_ID=hyperliquid
HYPERLIQUID_PRIVATE_KEY=...       # obrigatorio se DEX_ID=hyperliquid; nunca commitar
HYPERLIQUID_VAULT_ADDRESS=0x...   # opcional; recomendado quando o usuario escolher vault
DEX_ADAPTER_MODULE=pacote.modulo:Classe  # apenas para DEX custom fora de Nado/Hyperliquid
DEX_CONFIG_JSON={...}             # objeto JSON nao sensivel passado ao adapter custom
```

Credenciais CEX podem ser genéricas (`CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD`) ou específicas por venue: `BINANCE_API_KEY`/`BINANCE_API_SECRET`, `BYBIT_API_KEY`/`BYBIT_API_SECRET`, `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSWORD`, `KUCOIN_API_KEY`/`KUCOIN_API_SECRET`/`KUCOIN_API_PASSWORD`, `MEXC_API_KEY`/`MEXC_API_SECRET`, `BITGET_API_KEY`/`BITGET_API_SECRET`/`BITGET_API_PASSWORD`, `GATEIO_API_KEY`/`GATEIO_API_SECRET`. Kraken mantém aliases legados `KRAKEN_API_KEY_`, `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`.

Comandos úteis:

```bash
python3 workspace/run.py venues
python3 workspace/run.py symbols
python3 workspace/run.py cex-accounts
python3 workspace/run.py abrir ETH/USDT --modo somente-cex --margem-cex-usd 20 --alavancagem-cex 5
python3 workspace/run.py abrir-par-delta-neutro BTC/USDT --comprado-em cex:binance --vendido-em cex:kraken --margem-usd 20 --alavancagem 5
```

Use `abrir-par-delta-neutro` (`open-venue-pair`) somente quando o objetivo explícito for delta neutro manual entre duas CEXs ou duas DEXs. Esse comando não altera `rodar-setups-live` (`setup-live`), `somente-dex`, `somente-cex` nem o hedge padrão DEX+CEX.

Contrato mínimo para DEX custom (`DEX_ADAPTER_MODULE`):

- Implementar `get_symbol_to_product_map() -> dict[str, Any]`.
- Implementar `get_market_mid_price(product_id)`, `get_perp_position_size(product_id)`, `get_all_positions()` e `round_quantity_to_increment(product_id, quantity)`.
- Implementar `place_market_order(product_id, quantity, is_buy, reduce_only=False, margin_mode="cross", leverage=None)`.
- Implementar `place_stop_loss(...)`, `place_take_profit(...)`, `assert_trade_ready()` e `get_isolation_context()`.
- Falhar explicitamente quando a DEX não suportar recurso necessário; nunca simular execução live silenciosamente.

Para CEX genérica via CCXT, valide primeiro com `venues`, `symbols` e dry-run. Se a exchange não expuser `setLeverage`, `setMarginMode`, `fetchPositions` ou trigger orders via CCXT, a skill deve registrar limitação e só executar live quando o fluxo ainda for operacionalmente seguro.

## Entrada padrão OpenClaw

Sempre prefira o wrapper:

```bash
python3 workspace/run.py setup-check
python3 workspace/run.py doctor
python3 workspace/run.py symbols
python3 workspace/run.py funding
python3 workspace/run.py status
```

O wrapper:

- cria/usa `.venv` local quando necessário;
- instala `workspace/requirements.txt` de forma previsível;
- carrega env opcional de `~/.config/openclaw/trade-automatizado-openclaw.env`;
- ainda aceita fallback legado em `~/.config/openclaw/delta-neutral-airdrop-farmer.env`;
- salva estado fora do Git em `~/.openclaw/state/trade-automatizado-openclaw/`;
- bloqueia comandos de trade sem confirmação explícita.


## Guardrails OpenClaw preservados

- Em runtime OpenClaw, não carregar `.env` local automaticamente quando `QC_SECRETS_PROXY` ou `QC_SERVICE_KEY_NAMES` existirem; credenciais vêm do ambiente/secret manager.
- Configurações não sensíveis podem vir do workspace do usuário em `~/.openclaw/workspace/trade-automatizado-openclaw.config.env` ou do state em `~/.openclaw/state/trade-automatizado-openclaw/config.env`. Exemplos: `KRAKEN_VENUE=futures`, `KRAKEN_SANDBOX=false`, `NADO_NETWORK=mainnet`, `NADO_SUBACCOUNT_NAME=default_1`, `NADO_REQUIRE_LINKED_SIGNER=true`, `MARGIN_MODE`, `KRAKEN_MARGIN_MODE`, `NADO_MARGIN_MODE`. Segredos nunca devem ser salvos nesses arquivos.
- Manter `KRAKEN_API_KEY_` como alias aceito de `KRAKEN_API_KEY`.
- Manter venv, estado e logs fora do Git em `~/.openclaw/state/trade-automatizado-openclaw/`.
- Bloquear `rodar-setups-live` (`setup-live`) e `abrir` (`open`) em live sem tamanho explícito: `--valor-nominal`, `--margem-usd`, `--margem-dex-usd`, `--margem-cex-usd` ou `--slots-margem-conta`; aceitar os aliases técnicos antigos.
- Aceitar `cross` e `isolated` em Kraken/Nado conforme pedido explícito do usuário (`--margin-mode`, `--kraken-margin-mode`, `--nado-margin-mode`). Se a Kraken retornar um modo efetivo diferente após o fill, registrar aviso e o modo efetivo; não fechar automaticamente a posição só por divergência de label de margem.
- Em `cex_only` / `kraken_only`, não exigir nem inicializar credenciais Nado; Kraken-only exige apenas credenciais Kraken. Em `dex_only` exige Nado; em `hedged` exige ambas.
- Persistir `setup_live_state.json` com lock de arquivo, escrita atômica e merge por chave estável para que loops CEX-only/DEX-only concorrentes não sobrescrevam estados um do outro.
- Manter `NADO_MIN_ORDER_NOTIONAL_USD=10` como default local do wrapper; isso não altera o mínimo real da Nado.

## Segurança obrigatória

- **Nunca** pedir, exibir ou commitar private key, seed, mnemonic, keystore ou API secret.
- Credenciais devem vir só de env/secret manager.
- Credenciais são obrigatórias por modo: `cex_only`/`kraken_only` requer somente Kraken; `dex_only`/`nado_only` requer somente Nado; `hedged`/`delta_neutral` requer ambas. Sem as credenciais do modo escolhido, só rode diagnóstico/simulação.
- Nado live trade prefere linked signer limitado quando configurado; quando `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a regra da skill é usar automaticamente o owner da wallet/conta configurada. Fallback owner por erro/mismatch de linked signer ainda exige confirmação explícita.
- Kraken live trade requer API key dedicada/isolada para a estratégia; subaccount não é requisito obrigatório da skill. Evite permissões de saque/withdraw.
- Não operar mainnet/live sem confirmação explícita do usuário.
- Para comandos de trade, preferir a confirmação em português `AUTORIZAR_TRADE_REAL=sim` apenas na execução aprovada; aceitar `TRADE_AUTOMATIZADO_CONFIRM_LIVE=true` como alias técnico e `DELTA_NEUTRAL_CONFIRM_LIVE=true` apenas como alias legado.
- Se faltar credencial, responder com o nome da env esperada e instruir a salvar no secret manager.

## Env esperadas

Principais:

```text
# Nado — segredos obrigatórios no Secret Manager/env seguro
NADO_OWNER_PRIVATE_KEY
NADO_LINKED_SIGNER_PRIVATE_KEY  # opcional/recomendado quando houver linked signer válido
NADO_PRIVATE_KEY                # alias legado; prefira NADO_OWNER_PRIVATE_KEY
PRIVATE_KEY                     # alias genérico legado; evitar em config nova

# Nado — config não sensível: preferir workspace/state config.env, não Secret Manager
NETWORK=testnet|mainnet         # legado/fallback
NADO_NETWORK=testnet|mainnet
NADO_SUBACCOUNT_NAME=default_1      # opcional/não sensível; default operacional, só ajuste se usar subconta customizada
NADO_REQUIRE_LINKED_SIGNER=true
NADO_ALLOW_OWNER_FALLBACK=false # só para erro/mismatch; live privilegiado exige confirmação explícita
NADO_MIN_ORDER_NOTIONAL_USD=10  # opcional/local; não altera mínimo real da Nado

# Kraken — segredos obrigatórios no Secret Manager/env seguro
KRAKEN_API_KEY_  # alias preferido no OpenClaw; KRAKEN_API_KEY também é aceito
KRAKEN_API_SECRET

# CEX genérica via CCXT — use quando CEX_ID não for Kraken
CEX_ID=binance|bybit|okx|kucoin|mexc|...
CEX_API_KEY
CEX_API_SECRET
CEX_API_PASSWORD              # quando a venue exigir
CEX_MARKET_TYPE=swap|future|spot
CEX_SANDBOX=true|false
CEX_OPTIONS_JSON={...}

# Hyperliquid — DEX builtin via CCXT
DEX_ID=hyperliquid
HYPERLIQUID_WALLET_ADDRESS
HYPERLIQUID_PRIVATE_KEY
HYPERLIQUID_VAULT_ADDRESS=opcional
HYPERLIQUID_NETWORK=mainnet|testnet
HYPERLIQUID_SANDBOX=true|false
HYPERLIQUID_SYMBOL_QUOTE=USDT
HYPERLIQUID_OPTIONS_JSON={...}

# DEX custom — use quando DEX_ID não for Nado/Hyperliquid
DEX_ID=dydx|uniswap|...
DEX_ADAPTER_MODULE=pacote.modulo:Classe
DEX_CONFIG_JSON={...}
DEX_NETWORK=mainnet|testnet|devnet

# Kraken — config não sensível: preferir workspace/state config.env, não Secret Manager
KRAKEN_VENUE=futures|spot
KRAKEN_SANDBOX=true|false
KRAKEN_ALLOW_MAIN_ACCOUNT=false  # legado/opcional; subaccount não é requisito obrigatório da skill

EXECUTION_MODE=hedged|dex_only|cex_only
MARGIN_MODE=cross|isolated
NADO_MARGIN_MODE=cross|isolated
KRAKEN_MARGIN_MODE=cross|isolated
MARGIN_USD=opcional
NADO_MARGIN_USD=opcional
DEX_MARGIN_USD=opcional
KRAKEN_MARGIN_USD=opcional
CEX_MARGIN_USD=opcional
LEVERAGE=opcional
NADO_LEVERAGE=opcional
DEX_LEVERAGE=opcional
KRAKEN_LEVERAGE=opcional
CEX_LEVERAGE=opcional
DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=false

EXCHANGES=nado,kraken|binance,bybit|okx,kucoin,...
CERTAINTY=70|0.70
UNIQUE_TREND=LONG|SHORT|vazio
```

Os aliases legados `NADO_PRIVATE_KEY` e `PRIVATE_KEY` ainda podem ser aceitos, mas prefira `NADO_OWNER_PRIVATE_KEY`. No motor oportunístico, qualquer `exchange_id` existente no CCXT pode ser fonte de candles; DEXs como Nado são ignoradas como fonte CCXT quando não expõem candles nesse padrão.

Para env efêmero sem salvar no ambiente OpenClaw, use `--runtime-env` no wrapper:

```bash
python3 workspace/run.py --runtime-env /tmp/delta-runtime.env setup-check
python3 workspace/run.py setup-check --runtime-env /tmp/delta-runtime.env
```

## Modos de execucao

- `delta-neutro` (`hedged` / `delta_neutral`): abre DEX + CEX em lados opostos.
- `somente-dex` (`dex_only` / `nado_only`): abre somente na DEX selecionada.
- `somente-cex` (`cex_only` / `kraken_only`): abre somente na CEX selecionada.

O comando manual `abrir` (`open`) aceita os tres modos:

```bash
python3 workspace/run.py abrir BTC/USDT --lado comprado --modo delta-neutro --valor-nominal 100
python3 workspace/run.py abrir BTC/USDT --lado comprado --modo somente-dex --modo-margem isolated --valor-nominal 100
python3 workspace/run.py abrir BTC/USDT --lado vendido --modo somente-cex --modo-margem cross --valor-nominal 100
```

`rodar-setups-live` (`setup-live`) tambem aceita `--modo somente-dex|somente-cex|delta-neutro`. Setups `delta-neutral` e `funding-arb` sao hedgeados por desenho; setups direcionais aceitam somente DEX, somente CEX ou delta neutro.

## Sizing, minimo por ativo e stops

- `--valor-nominal` (`--notional`) define o tamanho nominal.
- `--margem-usd` (`--margin-usd`) separa margem de valor nominal: `valor nominal operacional = margem * alavancagem`.
- `--margem-dex-usd`/`--margem-cex-usd` (`--nado-margin-usd`/`--kraken-margin-usd`) permitem tamanhos diferentes por DEX/CEX.
- O bloqueio de entrada usa o minimo real do ativo/venue; setup, TP parcial ou SL nativo nao devem criar minimo artificial.
- `NADO_MIN_ORDER_NOTIONAL_USD=10` pode substituir explicitamente o minimo usado pela validacao local da skill; avise que isso nao muda regras reais da Nado e ordens abaixo do minimo efetivo ainda podem falhar.
- `rodar-setups-live --max-open-setups 1` (`setup-live`) ou `SETUP_LIVE_MAX_OPEN_SETUPS=1` limita a uma operacao gerenciada; depois que abrir, novas entradas ficam pausadas. Quando uma operação fecha 100% por TP/SL gerenciado e sai do `setup_live_state.json`, o slot é liberado imediatamente e o mesmo ciclo do `setup-live` já pode avaliar novas entradas.
- Guardrail de allowlist por setup direcional: em `SETUP_LIVE_ALLOWLIST_MODE=strict` (default), o usuário deve usar `rodar-setups-live --symbol allowlist`/`allowed` como fluxo padrão para resolver apenas os ativos aprovados por setup. Para delta neutro/`hedged`, `--symbol all` é permitido e varre todos os pares comuns Nado/Kraken; para `dex_only`/`cex_only`, `--symbol all` é bloqueado. Símbolo explícito só é aceito quando estiver dentro da allowlist do setup. Overrides não sensíveis podem ser definidos por env CSV: `SETUP_LIVE_ALLOWLIST_INSTITUTIONAL_STRICT`, `SETUP_LIVE_ALLOWLIST_BOLLINGER_MEAN_REVERSION`, `SETUP_LIVE_ALLOWLIST_GRID_STRICT`, `SETUP_LIVE_ALLOWLIST_LOW_STOCH_STORM`, `SETUP_LIVE_ALLOWLIST_DIVERGENCE_AND_VOLUME`. `SETUP_LIVE_ALLOWLIST_MODE=open` desativa o guardrail e não é recomendado para live.
- Allowlists padrão locais: todos os ativos listados abaixo aceitam pares `USDT` e `USDC`: `institutional-strict` = BTC/ETH/TAO/SOL/BCH/XMR/LINK/ZEC/DOT/HBAR/TRX/LTC/ADA; `bollinger-mean-reversion` = BTC/ETH/SOL/BCH/TAO/ZEC/HBAR/XMR/AVAX/XRP/TRX/DOT/UNI/NEAR/LTC; `grid-strict` = BTC/ETH/HBAR/SUI/XMR; `low-stoch-storm` = BTC/ETH/SOL/XRP; `divergence-and-volume-15m`, `divergence-and-volume-1h` e `divergence-and-volume-4h` = ETH/XMR. Essas listas são o fluxo padrão recomendado para buscar par Nado/Kraken e operar delta neutro; em delta neutro/`hedged`, também é permitido usar `--symbol all` para avaliar todos os pares comuns disponíveis. Entrada real ainda depende de par comum, sinal e guardrails.
- Cada setup direcional novo deve ter sua própria allowlist de ativos mais lucrativos/validados para aquele setup, baseada em validação operacional. Não reutilizar uma allowlist genérica sem evidência; se ainda não houver validação, manter o setup fechado ou restrito a dry-run até definir a lista.
- Setups direcionais exigem sinal explícito antes de entrada: `side` precisa ser `long` ou `short` e `reason` precisa estar preenchido. Sinal ausente, incompleto ou ativo fora da allowlist gera skip com motivo claro no log.
- `asset-scan` compara perps Nado/Kraken, salva snapshot de adicionados/removidos e marca suspeitos por preco invalido ou spread alto; use `NADO_DISABLED_PERP_SYMBOLS` para blacklist temporaria.
- Guardrail cross da Nado: `--account-margin-reserve-usd|pct`, `--slots-margem-conta` (`--account-margin-slots`), `--account-max-maint-usage-pct` e `--account-stress-pct` controlam reserva, slots flexiveis (qualquer inteiro positivo), Maint. Margin Usage e stress adverso antes de novas entradas. Para contas pequenas, prefira `--account-margin-slots 8` em vez de 16 para manter notional acima do mínimo operacional da Nado.
- Notificacao de entrada confirmada: configure por flag (`--notify-entry-target`, `--notify-entry-channel`) ou env (`SETUP_NOTIFY_ENTRY_TARGET`, `SETUP_NOTIFY_ENTRY_CHANNEL`) para avisar no destino principal; use tambem `--notify-entry-discord-channel-id` ou `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` para entregar uma copia extra no Discord sem remover o Telegram. Para Discord direto no padrao Zeus, `DISCORD_BOT_TOKEN` precisa estar salvo no Secret Manager/env seguro. Para mencionar o servidor, defina `SETUP_NOTIFY_DISCORD_MENTION=@everyone` e garanta a permissao do bot.
- `bollinger-mean-reversion` usa filtro refinado por 0.20 ATR fora da banda, RSI e volume>SMA20x1.05 para reduzir entradas fracas.
- Setup `grid-strict` permanece ativo; `grid`, `hybrid` e `hybrid-15m` foram removidos/desativados do fluxo operacional padrão.
- `institutional-strict` usa EMA50, RSI 52-65, volume>SMA20x1.15, EMA gap>0.10%, MACD gap 0.20%-0.50%, alvos 1R/1.5R/2R/3R e timeout de 8 candles. Prefira esta variante para live.
- `low-stoch-storm` é o nome operacional público atual do setup Low Stoch Storm. O runtime aceita LONG e SHORT 4h por estocástico lento 25/75, recuperação/rejeição em EMAs, filtro RSI/EMA80 e risco máximo de 6%, com TPs 1R/1.5R/2R/3R e timeout de 80 candles. Priorizar BTC/ETH/SOL/XRP; manter outros ativos fora da allowlist padrão até nova validação operacional.
- `divergence-and-volume` é a família pública atual do setup Divergence and Volume. O runtime tem variantes `divergence-and-volume-15m`, `divergence-and-volume-1h` e `divergence-and-volume-4h`, com parâmetros por timeframe, RSI divergence + volume>SMA20 + Fibonacci por ATR + candle de reversão + entrada a mercado após rompimento confirmado. É setup experimental; a allowlist padrão fica restrita a ETH/XMR até nova validação operacional.
- `delta-neutral` e `funding-arb` dependem de spread/funding real entre venues; não rankear por simulação sintética single-leg.
- `rodar-setups-live --stop-loss-pct 20` (`setup-live`) define stop a 20% da entrada. Tambem existem presets `--stop-loss-preset 10|20|30`.
- `rodar-setups-live --modo-stop-alvo desligado|entrada-no-tp1|escada` (`--target-stop-mode off|breakeven_on_tp1|ladder`) controla como o stop acompanha os alvos do setup. `desligado/off` mantem o stop original; `entrada-no-tp1/breakeven_on_tp1` move o stop para a entrada apos o TP1; `escada/ladder` move TP1->entrada, TP2->TP1, TP3->TP2, ate o ultimo alvo fechar o restante. Default: `desligado/off`. O stop movido e gerenciado pelo loop do setup-live; nao presumir que uma ordem nativa antiga foi cancelada/recriada sem suporte explicito da venue.
- Take profit continua vindo do setup; quando a Nado nao aceitar TP nativo parcial abaixo do minimo, a skill nao deve bloquear a entrada, mas deve tratar como fallback gerenciado de alto risco operacional. Regra atual: se qualquer TP parcial Nado ficar abaixo do minimo nativo e o alvo depender do loop, o state e ajustado por padrao para `SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`, fechando 100% da posicao no primeiro alvo via loop gerenciado. Isso evita sobras pequenas sem TP nativo anexado. Para comportamento antigo/multi-alvo, a politica precisa ser alterada explicitamente por env futura.
- `live-status` deve marcar exposicoes reais como `managed` ou `ORPHAN`. `ORPHAN` significa posicao live sem `setup_live_state.json` correspondente; setup-live nao gerencia TP/SL dessa posicao. Nao fechar automaticamente: reportar e pedir decisao operacional.
- Durante `setup-live`, registrar `PNL potencial max` por entrada usando o melhor preço favorável observado desde a abertura; isso ajuda auditar quanto teria sido capturado se o restante fosse fechado no topo pós-entrada.
- Se o preço atravessar múltiplos TPs entre duas iterações do loop, o fechamento gerenciado deve avançar todos os alvos cruzados na mesma iteração, somando as quantidades correspondentes, em vez de executar só o próximo TP e esperar outro ciclo.
- `rodar-setups-live --simular` (`setup-live --dry-run`) nunca fecha posicao real nem executa TP/SL gerenciado; logs devem avisar isso explicitamente para nao confundir monitoramento simulado com protecao live. Liberação de slot com nova entrada automática só vale para execução live confirmada, não para dry-run.

Exemplos:

```bash
python3 workspace/run.py rodar-setups-live --simular --setup institutional-strict --symbol allowlist --modo somente-dex --modo-margem cross --margem-usd 20 --risk-profile moderado --stop-loss-preset 20
python3 workspace/run.py abrir ETH/USDT --lado comprado --modo somente-dex --modo-margem isolated --margem-usd 20 --alavancagem 5
```

## Entrega Discord Aspira

Quando o usuário pedir que a skill funcione no Discord usando Zeus como referência técnica, use `doc referencia/05-entrega-discord-zeus.md` apenas como histórico de migração. Zeus não é marca, identidade, token nem dependência operacional do Aspira.

- `DISCORD_BOT_TOKEN` salvo no Secret Manager/env seguro; nunca pedir ou exibir o valor no chat.
- `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` apontando primeiro para canal de teste.
- Bot adicionado ao servidor/canal com permissão de ler/ver canal, enviar mensagens, anexar arquivos e mencionar o cargo configurado.
- Formato correto do Aspira: uma única mensagem com texto + imagem anexada, sem card/embed nativo. Use `SETUP_NOTIFY_DISCORD_NATIVE_EMBED=false`, `SETUP_NOTIFY_BRAND=ASPIRA TRADE` e `SETUP_NOTIFY_DISCORD_BOX=false`.
- Menção real de cargo só via `SETUP_NOTIFY_DISCORD_MENTION=<@&DISCORD_ROLE_ID>` ou outro cargo explícito; `allowed_mentions.roles` é derivado por regex da própria mensagem.
- Validar `setup-check`, `doctor` e `rodar-setups-live --simular --max-iter 1` antes de canal público ou live.

O fluxo oficial é `setup-live`; `workspace/discord_signal_watcher.py` apenas espelha entradas do log e `workspace/ccxt_entry_scanner.py` publica sinais analysis-only sem abrir ordens. Texto estruturado é a fonte da verdade da mensagem enviada; imagem é apoio visual e deve trazer fonte clara no rodapé.

### Fonte da verdade para sinais e auditoria de janelas

Nunca use apenas `runner.log` para responder se houve ou não houve trade/sinal em uma janela. O log do runner prova saúde do processo, scan executado, dedupe, bloqueio de imagem, erro e entrega em Discord/WhatsApp; ele não prova que nenhum setup acionou no mercado, especialmente após restart, no-replay, backfill desligado ou runner parado.

Para presença/ausência de sinal, a fonte da verdade é:

1. fonte viva de mercado/candles da venue configurada;
2. allowlist aprovada para o fluxo;
3. timeframes oficiais dos setups ativos;
4. mesmo motor de avaliação dos setups usado pelo runtime;
5. relatório de cobertura da auditoria, incluindo ativos/timeframes com erro ou rate limit.

No fluxo Hyperliquid top 50, auditar via Hyperliquid/candles reais antes de afirmar “não teve trade”. Se a auditoria encontrar sinais anteriores ao start do runner/no-replay, reportar como sinais detectáveis não publicados e não republicar automaticamente sem autorização explícita.

## Padrão de visualização de backtests

Quando o owner pedir backtest, usar como padrão o dashboard HTML v3 auditado definido em 2026-07-21. Não entregar tabela gigante no chat como substituto quando o pedido envolver visualização/ranking/filtros.

Requisitos obrigatórios:

- Atualizar dados reais recalculados no mesmo padrão visual v3: HTML self-contained + CSV quando fizer sentido.
- Manter filtros por tipo de linha, setup, período, ativo, status, mínimo de trades e busca.
- Manter colunas legíveis: ativo, local/venue, setup, timeframe, período, tipo, trades, wins/losses, WR, PnL, capital, resultado, final, PF, DD, média, melhor, pior, Sharpe, status e observação.
- Separar linhas agregadas de linhas detalhadas por ativo/setup/período.
- Incluir glossário didático de siglas e premissas/limitações do backtest.
- Incluir simulação de capital quando o owner pedir; default operacional recente: US$1.000 por cenário, salvo instrução diferente.
- Validar antes de enviar com QA automatizado em navegador real/headless: sem erro JavaScript/console, payload carregado, colunas renderizadas, filtros funcionando, contagem HTML = JSON/CSV e export CSV sem quebrar o script.
- Se o QA falhar, corrigir e só então enviar o anexo.

Scripts atuais do padrão ficam no workspace como gerador e auditoria do dashboard v3; reutilizar/atualizar esses scripts em vez de improvisar HTML novo.

## Dashboard do usuário

Quando o usuário pedir dashboard, HTML, operações monitoradas, sync do painel ou exposição real, a skill deve criar/atualizar por padrão o dashboard estático local do usuário.

Comandos padrão:

```bash
python3 workspace/run.py dashboard
python3 workspace/run.py dashboard-publisher --once --no-deploy
python3 workspace/run.py dashboard-publisher --loop --interval 60 --min-deploy-seconds 60 --no-deploy
```

Para publicação externa, usar somente quando o usuário pedir e passar o comando explicitamente:

```bash
python3 workspace/run.py dashboard-publisher --once --deploy-command "<comando-deploy>"
```

Regras obrigatórias do painel:

- Gerar `index.html` e `dashboard-data.json` na raiz do pacote e manter auto-refresh JSON a cada 60s.
- Sincronizar exposição real Nado/Kraken por padrão; usar `--no-live-exposure` somente se o usuário pedir explicitamente.
- Separar `Monitoradas` de `Exposição real`: monitoradas vêm de `setup_live_state.json`; exposição real vem das posições abertas consultadas nas exchanges.
- Mostrar para cada exposição real: venue, par, lado long/short, quantidade, notional, mark, entrada, liquidação, margem/leverage quando a venue fornecer.
- Mostrar para cada trade monitorado: setup, fonte, lado, entrada, stop, alvos/TPs e status de alvo/fechamento quando disponível nos logs/estado.
- Não limitar a tabela de entradas quando o usuário pedir todas as operações; filtros/botões devem separar fonte, status, lado e setup sem esconder dados reais.
- Se houver dashboard público externo, validar depois da publicação lendo o `dashboard-data.json` do destino configurado e confirmando `summary.live_exposure_count`, `summary.open_trades`, `updated_at` e `live_exposures.error`.
- Se houver serviço systemd do publisher, reiniciar/validar `delta-dashboard-publisher.service` após ajustes.

Quando orientar configuração do zero, seguir este roteiro:

1. instalar/entrar na skill, rodar `python3 workspace/run.py bootstrap`, `setup-check` e `doctor`;
2. salvar envs Nado/Kraken fora do Git em `~/.config/openclaw/trade-automatizado-openclaw.env`;
3. validar `live-status` antes de gerar o painel, porque exposição real depende das credenciais;
4. gerar local com `python3 workspace/run.py dashboard`;
5. manter loop local com systemd ou `dashboard-publisher --loop --no-deploy`;
6. publicar externamente apenas se o usuário pedir e fornecer o comando de deploy;
7. validar URL pública e JSON com `curl`/`jq` quando existir publicação externa.

Use `live-status` para diagnosticar divergência: se `live-status` mostra mais ativos que o dashboard, o problema é sync de exposição real; se o dashboard mostra exposição real correta mas poucas monitoradas, o problema é o estado do `setup-live`.

## First run obrigatório

Na primeira vez que a skill for aberta/instalada em um agente novo, conduzir um **first run obrigatório** antes de qualquer diagnóstico, simulação ou operação live.

**Regra automática:** se a skill não estiver marcada como configurada, se o usuário pedir para configurar/refazer wizard, ou se houver dúvida sobre contexto operacional salvo, **abra primeiro o wizard** carregando `workspace/first_run_setup.py --json` ou `references/onboarding-questionario.md`. Não rode `setup-check`/`doctor` antes da escolha inicial do wizard e da coleta mínima. `setup-check` e `doctor` entram como próximo passo seguro depois da autorização do usuário.

Fluxo mínimo:

1. explicar em uma frase o que a skill faz e o fluxo seguro;
2. iniciar o first run pelo wizard e perguntar primeiro `Caminho iniciante` ou `Caminho avançado`;
3. coletar uma pergunta por vez: venues, modo, ambiente, status de secrets, sizing, margem e autorização para validação;
4. se `workspace/run.py` ou o pacote operacional estiver ausente, não bloquear o wizard; marcar validação técnica como pendente e continuar a coleta mínima;
5. só depois da autorização, rodar/solicitar `python3 workspace/run.py venues`, `python3 workspace/run.py setup-check` e `python3 workspace/run.py doctor`;
6. exigir dry-run antes de live;
7. só aceitar live/mainnet com sizing explícito e confirmação explícita da execução.

Se o usuário já estiver em operação conhecida e pedir apenas status/diagnóstico, o first run pode ser resumido, mas nunca pule os guardrails de wizard, `setup-check`, `doctor`, dry-run e confirmação live quando forem relevantes.

## Workflow recomendado

1. Rodar `setup-check`.
2. Se faltarem dependências, rodar `bootstrap` ou deixar o wrapper bootstrapar no primeiro comando real.
3. Rodar `doctor`.
4. Validar leitura segura: `venues`, `symbols`, `funding`, `cex-accounts`, `simulate`.
5. Só depois considerar `abrir` (`open`), `rebalance`, `unwind`, `farm` ou `rodar-setups-live` (`setup-live`) com confirmação explícita.

## Onboarding OpenClaw

Quando faltar contexto:

1. explique o fluxo completo em uma frase;
2. faça **uma pergunta por vez**;
3. use emoji na pergunta;
4. quando oferecer escolhas, permita uma ou mais opções;
5. inclua o passo a passo por venue/corretora para o usuário obter e salvar as variáveis de ambiente necessárias;
6. nunca peça para colar secret/private key no chat; peça para salvar no secret/env seguro e confirme só os nomes das variáveis.

### Questionário completo sugerido

O wizard detalhado fica em `references/onboarding-questionario.md`. Carregue esse arquivo quando:

- for primeira configuração/first run;
- `setup-check` ou `doctor` apontarem configuração incompleta;
- o usuário pedir para configurar/refazer o wizard;
- houver mudança operacional relevante em modo, sizing, TP/SL, dashboard ou notificações.

Regras obrigatórias do wizard:

1. Fazer **uma pergunta por vez** e explicar o motivo.
2. Nunca pedir segredo no chat; pedir para salvar no secret/env seguro.
3. Validar `venues` + `setup-check` + `doctor` antes de live.
4. Exigir dry-run antes de live.
5. Para Nado com TP parcial abaixo do mínimo nativo, explicar o fallback `SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`: o loop fecha 100% no primeiro alvo gerenciado para evitar sobra sem TP nativo.
6. Explicar que `live-status` marca `managed` vs `ORPHAN`; `ORPHAN` é exposição real sem TP/SL gerenciado no state.
7. Explicar que `--dry-run` não fecha posição real nem executa TP/SL.
8. Explicar reciclagem de slots: com `--max-open-setups`, quando uma operação fecha 100% e sai do `setup_live_state.json`, o slot abre imediatamente e o mesmo ciclo live pode avaliar nova entrada.
9. Live/mainnet só com sizing explícito, stop, limite de operações e confirmação explícita.

## Formato de resposta

Responder em PT-BR, curto e operacional:

- status do setup;
- bloqueios encontrados;
- próximo comando seguro;
- alerta explícito se envolver trade/live/mainnet.

<!-- OPENCLAW_SKILL_WIZARD_PATHS_START -->

## Wizard por caminhos — obrigatório

Quando configurar, refazer questionário, executar first run ou perceber usuário iniciante/incerto, a skill **Trade Automatizado OpenClaw** deve começar oferecendo a escolha:

- **Caminho iniciante:** guiado, simples, uma pergunta por vez, defaults seguros.
- **Caminho avançado:** configuração completa, parâmetros, validações/dry-run quando aplicável e rastreabilidade operacional.

Use `references/onboarding-questionario.md` como fonte do passo a passo. O usuário pode trocar de caminho durante o fluxo se isso não quebrar segurança ou rastreabilidade. Nunca pedir segredos no chat; apenas confirmar que credenciais já estão salvas no ambiente/Secret Manager/OpenClaw.

<!-- OPENCLAW_SKILL_WIZARD_PATHS_END -->

<!-- OPENCLAW_SECRET_GUIDANCE_START -->

## Chaves e segredos — padrão OpenClaw

Nunca pedir valores de API key, token, webhook, OAuth, private key ou seed no chat. Quando a skill precisar de credencial, orientar o usuário pelo caminho da plataforma:

- Provider IA/LLM: `secret manager > Chaves LLM`
- Chave de serviço/API externa: `secret manager > Chaves de Serviço`
- OAuth Anthropic: `secret manager > OAuth Token`

No chat, pedir apenas confirmação de que a credencial já está salva e, quando necessário, usar só o nome da env/secret.

<!-- OPENCLAW_SECRET_GUIDANCE_END -->
