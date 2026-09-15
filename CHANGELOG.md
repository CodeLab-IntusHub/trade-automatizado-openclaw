# Changelog

## Nao publicado

### Corrigido

- **A Hyperliquid passa a consumir o resolvedor unico de sandbox.** Ela deriva o valor da rede selecionada (`HYPERLIQUID_NETWORK`: `testnet` implica sandbox), e esse valor entra na **camada de ambiente** -- abaixo de um `HYPERLIQUID_SANDBOX` explicito, acima de qualquer arquivo --, porque e de uma variavel de ambiente que ele vem. O chamador passa `None` quando nenhuma rede foi declarada: `network in {...}` e sempre um bool, e esse `False` incondicional tornaria `venues.dex.*.sandbox` config morta e mandaria para a mainnet quem declarou sandbox no arquivo.
- **A contradicao entre rede e sandbox deixa de ser silenciosa.** `HyperliquidDexTrader.__init__` faz `self.network = "testnet" if self.sandbox else "mainnet"`: a rede declarada nao sobrevive ao construtor. Com `HYPERLIQUID_NETWORK=testnet` e `HYPERLIQUID_SANDBOX=false` -- o par que o `.env.example` distribuia --, quem escolheu testnet operava na mainnet sem nenhum aviso. A precedencia nao muda; o conflito agora sai como `WARNING` nomeando as duas pontas e dizendo onde a ordem vai cair.
- `HYPERLIQUID_SANDBOX` vem comentada no `workspace/.env.example`: ativa, vencia a rede declarada e o settings.
- **A especificidade passa a vir da cadeia da venue, nao do indice da lista.** Quando as grafias alternativas entraram, `keys` ficou maior que `env_names` e o aviso de "env generica engoliu chave especifica" sumia em silencio para todo id normalizado (`kraken_futures`, `hyperliquid_dex`, `binance.us`) -- justamente o caso de migracao que ele existe para cobrir.
- **As duas grafias de um id resolvem nos dois sentidos.** A normalizacao ia so para hifen, entao selecionar `kraken-futures` nao alcancava uma chave escrita `kraken_futures` e a declaracao da venue era descartada pela generica.
- **O veredito do `doctor` sai por nome de check, nao por posicao.** `venues_config` entrou como quinto item e o criterio era `checks[:4]`, entao o comando devolvia `ok` com config que derruba `venues`, `rodar-setups` e o `build_engine`.
- **`kraken_sandbox` segue a variante selecionada.** Cravar o id `kraken` fazia o campo fabricar `"true"` a partir do default enquanto a ordem ia para producao, contradizendo `cex_sandbox` no mesmo payload.
- **Isolamento de teste completo**: o `settings.json` versionado tambem e redirecionado (`config.REPO_ROOT`), os arquivos de env do operador saem do caminho de `setup_check`, e o `os.environ` e restaurado entre testes -- `monkeypatch` so desfaz o que ele mesmo mudou, e codigo de producao chamado de dentro do teste tambem escreve no ambiente.
- **`sandbox` das CEXs passa a ter um resolvedor unico** (`workspace/venues/sandbox.py`). A mesma pergunta -- dinheiro de brinquedo ou dinheiro real -- era respondida em quatro lugares com regras diferentes, e dois defeitos saiam disso: (1) o vocabulario de booleano so definia o lado verdadeiro, entao `CEX_SANDBOX=ture` caia no `else` implicito e o bot operava com dinheiro real achando que estava em sandbox; (2) `_load_cex_sandbox` dava prioridade a variavel generica e `_load_pair_cex_sandbox` a especifica, de modo que `CEX_SANDBOX=false` com `BINANCE_SANDBOX=true` mandava a ordem para sandbox enquanto o resumo exibido ao operador dizia `false`. Ver `Docs/features/sandbox-por-venue.md`.
- Prefixo de variavel por venue deixa de quebrar em id com pontuacao: `binance.us` gerava `BINANCE.US_SANDBOX`, nome que nenhum shell exporta, tornando a variavel especifica inalcancavel em silencio.
- `KRAKEN_SANDBOX` vira variavel de familia declarada, e nao um caso especial no meio do `cli.py`. A familia vale **tambem para as chaves de settings**: `venues.cex.kraken.sandbox` alcanca `krakenfutures` e `kraken-spot`, que de outro modo caiam na chave generica e iam para producao.
- Na varredura dos arquivos de settings, a **camada e o eixo externo**: `settings.local.json` vence `settings.json` mesmo quando o versionado tem a chave mais especifica. Sem isso, uma chave por venue do arquivo do time derrubava a chave generica do arquivo do operador.
- Mensagem de valor invalido nomeia a variavel de ambiente que o operador escreveu (`BINANCE_SANDBOX`), e nao uma chave de arquivo que pode nem existir.

### Adicionado

- `sandbox` configuravel por arquivo em `venues.<tipo>.sandbox` e `venues.<tipo>.<venue>.sandbox`, com exemplo em `settings.example.json`. Antes so existia por variavel de ambiente.
- `Settings.has_env` e `config.FILE_LAYERS`: permitem tratar camada e especificidade como eixos separados sem recodificar a ordem das camadas em dois lugares.
- Aviso quando uma chave de camada mais forte e menos especifica que outra declarada **e os valores divergem** -- um `venues.cex.sandbox: false` do operador engolindo um `venues.cex.kraken.sandbox: true` do time. A ordem continua valendo; perder a declaracao em silencio, nao.
- Teste de guarda que falha se o `.env.example` voltar a trazer uma variavel de sandbox descomentada, e teste que exercita as chaves do `settings.example.json` contra o codigo que as le.

### Mudanca de comportamento (atencao ao atualizar)

- **A precedencia entre as variaveis de sandbox foi invertida.** Antes
  `_load_cex_sandbox` era `CEX_SANDBOX > <PREFIX>_SANDBOX > default`; agora a
  especifica vence a generica, alinhando com os outros tres leitores. A direcao
  benigna e a que motivou a mudanca (`CEX_SANDBOX=false` + `BINANCE_SANDBOX=true`
  passa a ir para sandbox), mas **a direcao oposta tambem mudou**: quem usa
  `CEX_SANDBOX=true` como chave-mestra de seguranca e tem um `<VENUE>_SANDBOX=false`
  esquecido no `.env` passa de sandbox para **producao** so por atualizar.
  Confira as variaveis `*_SANDBOX` do seu `.env` antes de subir esta versao.

### Alterado

- `CEX_SANDBOX` e `KRAKEN_SANDBOX` vem comentadas no `workspace/.env.example`: ativas, venciam o `settings.json` e o deixavam inoperante para quem copiasse o exemplo.
- Os dois comandos de diagnostico deixam de estourar com config invalida: `setup-check` reporta a mensagem em `venues_error` e devolve `cex_sandbox: null` em vez de chutar `"false"`; `venues` termina com a mensagem em vez de traceback. Eles sao rodados justamente quando algo esta errado.
- As fixtures de `test_sandbox_resolution` e `test_config_foundation` isolam o home: `_local_settings_path` devolve o primeiro caminho que existe, entao sem isso a suite lia o `settings.local.json` real do operador em vez da fixture.

## v1.3.0 — 2026-09-14

### Adicionado

- **Fonte unica de configuracao** (`workspace/config.py`): precedencia `env -> settings.local.json -> settings.json -> default`, vocabulario de booleano com os dois lados explicitos (valor desconhecido levanta erro em vez de virar `false`), segredo declarado apenas pelo *nome* da variavel de ambiente, e origem rastreavel por chave. Ver `Docs/features/configuracao-de-setups.md`.
- **Parametros de setup configuraveis por arquivo**: cada setup expoe as suas vars em `setups.<chave>.<parametro>`. Destrava calibracao por timeframe no `divergence-and-volume` (as variaveis de ambiente sao unicas para 15m/1h/4h) e torna `fibonacci_levels`, `target_levels` e `target_weights` ajustaveis — antes so mudavam editando codigo, apesar de decidirem onde o capital sai da posicao. Exemplo em `settings.example.json`.
- **Validacao da config de setup no boot** (`validate_setup_settings`): valor invalido derruba o comando antes do primeiro ciclo. Dentro do loop de scan a excecao seria capturada como `WARNING`, deixando o bot de pe sem abrir nada.
- **Pipeline de CI que executa a suite** (`.github/workflows/tests.yml`): pytest em ubuntu x windows x Python 3.12/3.13, ruff, mypy, pip-audit e cobertura, mais `dependabot.yml`. A CI anterior passava sem rodar teste nenhum.

### Corrigido

- **Resposta da corretora ao anexar SL/TP passa a ser validada** nos tres adapters (`workspace/venues/order_validation.py`). Antes, qualquer objeto nao-`None` contava como "protecao anexada" — inclusive uma rejeicao estruturada —, porque os chamadores so testam `if order is None`. Ver `Docs/features/protecao-de-ordens.md`.
- `replace_stop_loss` cancela o stop vivo antes de criar o novo nos tres adapters; a falha agora diz explicitamente que a posicao ficou sem stop, e a referencia da ordem morta e limpa do estado.
- `place_market_order_with_tp_sl` (Kraken) deixa de engolir a falha de protecao: devolve `protected`, `protection_error` e os ids de SL/TP.
- Escada de alvos passa a ser invariante de `DivergenceVolumeConfig`: escada vazia, contagem divergente de pesos e soma nao positiva sao recusadas na construcao. Antes o mesmo estado invalido era fatal vindo do settings e silenciosamente reparado vindo do construtor.
- Dois nomes indefinidos expostos pelo gate de lint: `_first_float` sem import em `cli.py` (o `NameError` era engolido por um `except Exception` e virava "saldo indisponivel") e `BacktestResult` num fake de teste que nunca era exercitado.
- Bit de execucao restaurado em `render_trade_chart.js` e `tradingview_session.js`.

### Alterado

- `workspace/.env.example` comenta as variaveis de calibracao de setup: elas continuam funcionando e **tem precedencia** sobre o `settings.json`, entao mante-las ativas no exemplo tornava o settings inoperante para quem copiasse o arquivo. O boot avisa quando uma chave de settings esta encoberta pela env.
- `settings.local.json` e procurado fora da arvore primeiro (`DELTA_NEUTRAL_SETTINGS_DIR`, depois `~/.config/openclaw/<skill>/`), porque a skill e reinstalada por cima do proprio diretorio.

## v1.2.0 — 2026-09-09

### Corrigido

- Substitui `import fcntl` por um lock de arquivo cross-platform (`workspace/file_lock.py`): o CLI nao importava no Windows, o que derrubava a coleta de 3 dos 4 arquivos de teste. Consolida a estrategia PID + `O_EXCL` que ja existia no `dashboard_publisher`, agora com espera por timeout.
- Corrige a sonda de liveness do lock: no Windows `os.kill(pid, 0)` **nao levanta** para um PID que ja morreu (o sinal 0 e `CTRL_C_EVENT`, que cai no ramo de evento de console), entao qualquer processo morto era reportado como vivo e o lock orfao nunca seria recuperado. Passa a usar `OpenProcess`/`GetExitCodeProcess`. *(Corrigido em 14/09/2026: a versao original desta nota afirmava que `os.kill(pid, 0)` executaria `TerminateProcess` — verificado por execucao que nao e o caso.)*
- `setup-check` deixa de disparar `pip install` de rede a cada execucao em maquinas sem o SDK da Nado, e deixa de gastar um startup de interpretador por modulo sondado (24s -> 0,28s nesta maquina).

### Alterado

- O SDK `nado-protocol` passa a ser dependencia **opcional**, exigida apenas por `DEX_ID=nado`. `requirements.txt` agora instala em qualquer maquina; a Nado vive em `requirements-nado.txt`. Kraken, Hyperliquid e as demais CEXs sempre rodaram por CCXT e nao precisam do toolchain de build nativo.
- `core/delta_neutral.py` nao importa mais `NadoTrader` em runtime — era usado so como anotacao de tipo, e agora vai sob `TYPE_CHECKING`.
- `workspace/nado/__init__.py` resolve simbolos sob demanda; usar a Nado sem o SDK falha alto no ponto de uso, com instrucao explicita.

### Adicionado

- `workspace/nado/units.py` com as conversoes `from_x18`/`from_x6` (aritmetica pura, sem dependencia do SDK), reexportadas por `nado_integration`.

## v1.1.22 — 2026-06-16

### Adicionado

- Adiciona `setup-live --modo-stop-alvo desligado|entrada-no-tp1|escada` e env `SETUP_LIVE_TARGET_STOP_MODE` para escolher se o stop fica fixo, vai para entrada no TP1 ou sobe em escada a cada alvo.
- Documenta no wizard/skill que o stop movido é gerenciado pelo loop do `setup-live`; a recriação de ordem stop nativa depende de suporte explícito da venue.

## v1.1.20 — 2026-06-16

### Alterado

- Atualiza o wizard de configuração para perguntar DEX/CEX antes de secrets, modo, sizing e margem.
- Lista as principais venues no onboarding: Nado, Hyperliquid, Binance, Kraken, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io.
- Adiciona passo a passo por corretora/venue e reforça que outras CEXs integram via CCXT e outras DEXs via adapter Python.
- Deixa explícito no wizard e guias que subconta/conta isolada é recomendada quando a corretora/DEX oferecer esse recurso, mas não obrigatória por padrão; a decisão final é do usuário e não deve ser hard-coded; o requisito mínimo é API key/credencial dedicada sem saque e validação por `doctor`/dry-run.

## v1.1.19 — 2026-06-01

### Alterado

- Restringe `low-stoch-storm` para BTC/ETH/SOL/XRP na allowlist padrão, com base em validação operacional real.
- Restringe `divergence-and-volume-*` para ETH/XMR na allowlist padrão e no whitelist default do setup experimental.
- Atualiza símbolos padrão das validações reais para refletir os ativos validados por setup.

### Corrigido

- Corrige o label do ranking operacional para manter `Divergence and Volume 15m`, `1h` e `4h` separados.

## v1.1.18 — 2026-05-26

### Corrigido

- Corrige nomes publicos/documentacao dos setups para `low-stoch-storm` e `divergence-and-volume-*`.
- Corrige comandos/manifesto das validações reais dedicadas de Low Stoch Storm e Divergence and Volume.
- Corrige runtime/config por timeframe do Divergence and Volume e allowlists relacionadas.

### Tracking

- Issue: #1

## 1.1.9 - 2026-05-12

- Nova release correta para validação do wizard curto final.
- Mantém correção que remove link/cadastro externo do wizard.


## 1.1.8 - 2026-05-12

- Ajusta wizard curto para não enviar link/cadastro externo.
- Troca `secrets_status` por `account_and_secrets_status`.
- Remove links/referrals diretos do guia detalhado operacional.

## 1.1.7 - 2026-05-12

- Encurta o wizard principal para 6 perguntas essenciais.
- Move o onboarding longo Nado/Kraken para `references/onboarding-detalhado.md`.
- Adiciona payload JSON em `workspace/first_run_setup.py --json` para first-run automático.



## 1.1.6 - 2026-05-12

- Ajusta fallback Nado para TP parcial abaixo do mínimo nativo: fecha 100% no primeiro alvo gerenciado por padrão (`SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`).
- `live-status` passa a marcar exposições reais como `managed` ou `ORPHAN`, sem fechar posições automaticamente.
- Registra `PNL potencial max` por entrada e avança múltiplos TPs cruzados na mesma iteração do loop.
- Reforça que `setup-live --dry-run` não executa TP/SL real nem libera slot como live.

## v1.0.20 — 2026-05-06

### Adicionado

- Portados os setups `low-stoch-storm` e `divergence-and-volume-4h` para o catálogo operacional da skill.
- `low-stoch-storm` agora entra no ranking operacional com regra LONG 4h por Stoch/EMA/RSI, stop estrutural/ATR e alvos 1R/1.5R/2R/3R.
- `divergence-and-volume-4h` entra no ranking operacional e mantém validação real dedicada por divergência RSI + volume + zona Fibonacci + candle de reversão.

### Alterado

- Separados os filtros `normal` vs `strict` de `momentum` e `institutional`: as versões normais preservam a calibração anterior, enquanto as versões strict exigem RSI mais estreito, volume `>SMA20x1.15` e gaps de tendência mais fortes.

### Validação

- Validação sintética registrada para `divergence-and-volume-4h`; `low-stoch-storm` permaneceu sem trades nessa amostra, com execução observada tratada como amostra pequena.

## v1.0.19 — 2026-05-06

### Adicionado

- Entrega extra de aviso de entrada confirmada no Discord via `--notify-entry-discord-channel-id` ou `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID`, sem substituir o destino principal como Telegram.
- O aviso agora cobre todas as entradas confirmadas do `setup-live`, incluindo DEX-only, CEX-only e hedged.

## v1.0.18 — 2026-05-01

### Alterado

- Default recomendado de `SETUP_ACCOUNT_MARGIN_SLOTS` atualizado de 16 para 8 para evitar entradas abaixo do mínimo operacional da Nado em contas pequenas.
- Regra operacional Nado: quando `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a skill usa automaticamente o owner da subconta em vez de bloquear trade.
- Fallback owner por erro/mismatch de linked signer continua exigindo `NADO_ALLOW_OWNER_FALLBACK=true` + `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`.
- Atualizados `setup-check`/`doctor`, `.env.example`, README/INSTALL/SKILL.md e testes para refletir a regra.

## v1.0.17 — 2026-04-30

### Adicionado

- Novos setups calibrados `momentum-strict`, `grid-strict` e `institutional-strict` para substituir variantes menos robustas.
- Validação operacional registrada para `momentum-strict`, `grid-strict` e `institutional-strict`.

### Operacional

- `triangle-breakout` continua fora das novas entradas até nova calibração.

## v1.0.16 — 2026-04-30

### Adicionado

- Novo setup `bollinger-mean-reversion-strict`, calibrado com distância de 0.20 ATR fora da banda e RSI 35/72.

## v1.0.15 — 2026-04-30

### Corrigido

- Saídas parciais solo (`partial_exit`) agora atualizam quantidade/notional restantes no state gerenciado, evitando status e stress guardrail superestimarem exposição após TP parcial.

## v1.0.14 — 2026-04-30

### Adicionado

- Flags no `setup-live` para notificação de entrada confirmada: `--notify-entry-target`, `--notify-entry-channel`, `--notify-entry-account` e `--no-notify-entry`.

## v1.0.13 — 2026-04-30

### Adicionado

- Notificação best-effort de entrada confirmada no `setup-live` via `openclaw message send`, configurável por `SETUP_NOTIFY_ENTRY_*`.

## v1.0.12 — 2026-04-30

### Adicionado

- Guardrail de margem cross da Nado para `setup-live`: `--account-margin-reserve-usd`, `--account-margin-reserve-pct`, `--account-margin-slots`, `--account-max-maint-usage-pct` e `--account-stress-pct`.
- Cálculo de `Maint. Margin Usage` a partir dos healths da subconta e log de orçamento/slot por entrada.
- Quando não há `--margin-usd` explícito, `--account-margin-slots` divide o orçamento operacional da conta em slots e calcula a margem por entrada automaticamente.

## v1.0.11 — 2026-04-30

### Adicionado

- Novo comando `asset-scan` para comparar perps/ativos entre Nado e Kraken, detectar símbolos adicionados/removidos, salvar snapshot em `state/asset_scan_state.json` e marcar mercados suspeitos por preço inválido ou spread alto Nado/Kraken.
- Env `NADO_DISABLED_PERP_SYMBOLS`/`NADO_EXCLUDE_SYMBOLS` documentadas no manifesto para blacklist temporária de perps ainda não operacionais.

## v1.0.10 — 2026-04-30

### Corrigido

- `setup-live` não bloqueia mais entrada por uma liquidação teórica derivada de `1/leverage` antes da ordem existir.
- O stop configurado por `--stop-loss-pct` continua sendo a regra de saída/gestão negativa, sem ser confundido com preço de liquidação.
- Após entrada real, o log registra `liq_corretora` com a liquidação lida da venue quando disponível; enquanto a corretora não retornar o dado, fica `corretora_pendente`.
- `setup-live --symbol all` agora exclui por padrão `ADA/USDT` e `ARB/USDT` na Nado, pois não há perp ativo; pode ser sobrescrito por `NADO_DISABLED_PERP_SYMBOLS`/`NADO_EXCLUDE_SYMBOLS`.

## v1.0.9 — 2026-04-30

### Adicionado

- `setup-live --max-open-setups` e env `SETUP_LIVE_MAX_OPEN_SETUPS` para limitar o número global de setups gerenciados abertos.
- Com `--max-open-setups 1`, a skill abre no máximo uma operação e pausa novas entradas enquanto ela estiver ativa.

## v1.0.8 — 2026-04-30

### Adicionado

- `NADO_MIN_ORDER_NOTIONAL_USD` permite substituir explicitamente o mínimo de notional usado pela validação local da skill em entradas Nado-only/setup-live.

### Observação

- O override não altera regras reais da Nado; ordens abaixo do mínimo efetivo da venue ainda podem ser rejeitadas durante a execução.

## v1.0.7 — 2026-04-29

### Adicionado

- `open` e `setup-live` aceitam `--margin-usd`, `--nado-margin-usd` e `--kraken-margin-usd`; o notional operacional passa a ser `margem * leverage`.
- `setup-live` aceita stop por execução com `--stop-loss-pct` e presets `--stop-loss-preset 10|20|30|conservador|moderado|degen`.
- Wrapper aceita `.env` efêmero com `--runtime-env`, antes ou depois do comando.
- Flags explícitas para fallback privilegiado: `NADO_ALLOW_OWNER_FALLBACK`, `KRAKEN_ALLOW_MAIN_ACCOUNT` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK`.

### Corrigido

- Entrada solo Nado/DEX agora bloqueia pelo mínimo real do ativo/venue, não por mínimo artificial de setup, SL ou TP parcial.
- TP parcial nativo da Nado abaixo do mínimo não bloqueia a entrada; o alvo permanece no gerenciamento do setup e o skip nativo fica registrado.
- Guardrail padrão de saldo Nado para setup-live foi reduzido para 5% do notional quando margem explícita não é usada.

## v1.0.6 — 2026-04-29

### Adicionado

- `open` agora aceita `--execution-mode hedged|dex_only|cex_only` com aliases `nado_only` e `kraken_only`.
- `open` agora aceita `--margin-mode`, `--nado-margin-mode`, `--kraken-margin-mode`, `--leverage`, `--nado-leverage` e `--kraken-leverage`.
- Defaults por env para execução/margem/leverage: `EXECUTION_MODE`, `MARGIN_MODE`, `NADO_MARGIN_MODE`, `KRAKEN_MARGIN_MODE`, `LEVERAGE` e aliases DEX/CEX.

### Corrigido

- `status`, `unwind`, `rebalance` e `farm` agora reconhecem estados solo Nado/DEX ou Kraken/CEX.
- `setup-live` aceita aliases `dex_only` e `cex_only` e pode ler `EXECUTION_MODE`/margens do env.

## v1.0.5 — 2026-04-29

### Corrigido

- Aceito `PRIVATE_KEY` como alias legado opcional depois de `NADO_OWNER_PRIVATE_KEY` e `NADO_PRIVATE_KEY`.
- `NETWORK` agora é fallback para `NADO_NETWORK`.
- `CERTAINTY` aceita inteiro, porcentagem ou decimal (`75`, `75%`, `0.75`).
- `UNIQUE_TREND` ignora valores booleanos e só aplica `LONG` ou `SHORT`.
- `MAX_OPPORTUNITIES` passa a ser respeitado no comando `opportunistic`.
- `EXCHANGES=nado,kraken` agora é tolerado: `nado` é ignorado como fonte CCXT e `kraken` é mapeado para Kraken Futures.

## v1.0.4 — 2026-04-29

### Corrigido

- Declarado `setuptools<81` no manifesto para refletir o bootstrap real da skill.
- Permitido `--help` e `--dry-run` em comandos protegidos sem exigir confirmação live.
- Atualizados scripts auxiliares Nado para usar envs canônicas (`NADO_OWNER_PRIVATE_KEY`, `NADO_LINKED_SIGNER_PRIVATE_KEY`) e bloquear execução direta sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`.
- Ajustado teste de linked signer para refletir o bloqueio seguro por `RuntimeError`.

### Documentação

- Esclarecido que as envs de Nado/Kraken são obrigatórias para operação real e devem vir do env/secret manager.
- Alinhados README/INSTALL ao repositório OpenClaw.

## v1.0.3 — 2026-04-29

### Corrigido

- Manifest agora declara `live-status`, `live-hedge` e `live-sync`, que já existiam no CLI.
- Smoke test cobre a paridade desses comandos no `skill.json`.

## v1.0.2 — 2026-04-29

### Alterado

- Alinhado o identificador runtime da skill para `trade-automatizado-openclaw`.
- Paths padrão de env/state/log agora usam o nome OpenClaw da skill.
- Mantido fallback para env/state legados de `delta-neutral-airdrop-farmer`, evitando quebra de instalações antigas.

## v1.0.1 — 2026-04-28

### Corrigido

- Reativada trava de linked signer em `NadoTrader.assert_trade_ready()`.
- Reativada trava de subconta/conta master em `KrakenTrader.validate_entry_subaccount_rule()`.
- `workspace/cli.py` agora também bloqueia comandos de trade sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`, evitando bypass do wrapper.
- Removido fallback genérico `PRIVATE_KEY`; a skill aceita apenas `NADO_OWNER_PRIVATE_KEY` e o alias explícito `NADO_PRIVATE_KEY`.
- `backup_project.py` não copia mais `.env`, `.env.*`, state, batch artifacts, dist ou caches.
- Removidos `workspace/batch-*.json` do repo e adicionado ignore para novos artefatos operacionais.
- Dependências principais pinadas e `pytest` incluído para validação dev.

### Segurança

- Não usar live/mainnet sem validar `doctor`, linked signer Nado e subconta Kraken dedicada.

## v1.0.0 — 2026-04-28

### Adicionado

- Release inicial da skill OpenClaw no repositório dedicado.
- Entrada `workspace/run.py` com `setup-check`, `doctor` e `bootstrap`.
- Bootstrap previsível de dependências Python em `.venv` local quando o runtime suporta `venv/pip`.
- Carregamento opcional de env seguro via `~/.config/openclaw/delta-neutral-airdrop-farmer.env`.
- Estado/logs fora do Git em `~/.openclaw/state/delta-neutral-airdrop-farmer/` e `~/.openclaw/logs/delta-neutral-airdrop-farmer/`.
- Bloqueio de comandos live/trade sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`.

### Segurança

- Secrets apenas em env/secret manager, nunca no Git.
- Live trading exige confirmação explícita por execução.
- `workspace/cli.py` preservado como motor principal; wrapper adiciona guardrails sem reescrever estratégia.
