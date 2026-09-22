# Questionário curto de onboarding — Trade Automatizado OpenClaw

Use quando o first run disparar ou quando houver demanda autorizada `configurar delta neutro` ou `refazer wizard`.

Nota anti-legado: qualquer menção antiga a colaboradores anteriores neste fluxo é histórica e não tem força operacional. Desde 2026-08-04 ele não é colaborador, validador, owner nem pessoa a ser acionada em trade/desenvolvimento.

Objetivo: coletar só o mínimo para escolher o caminho seguro, começando pela escolha das venues. O wizard deve listar as principais opções (`Nado`, `Hyperliquid`, `Binance`, `Kraken`, `Bybit`, `OKX`, `KuCoin`, `MEXC`, `Bitget`, `Gate.io`) e avisar que também há integração com outras CEXs via CCXT e outras DEXs via adapter Python. Detalhes longos de cada corretora/venue ficam em `references/onboarding-detalhado.md` e só devem ser usados se o usuário pedir ajuda passo a passo.

## Regras obrigatórias

- PT-BR, uma pergunta por vez.
- Explicar o motivo da pergunta em uma frase curta.
- Nunca pedir private key, seed, mnemonic, API secret ou token no chat.
- Pedir apenas confirmação de que as contas/envs/secrets já estão prontas no OpenClaw.
- Perguntar a DEX/CEX desejadas antes de orientar secrets: default seguro é `DEX_ID=nado` e `CEX_ID=kraken`; CEX não-Kraken usa CCXT; DEX fora de Nado/Hyperliquid exige `DEX_ADAPTER_MODULE` antes de live.
- Listar explicitamente as principais venues no wizard: Nado, Hyperliquid, Binance, Kraken, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io. Se o usuário escrever `bibyt`, normalizar para `bybit`.
- Avisar que outras CEXs suportadas pelo CCXT podem ser usadas com `CEX_ID=<exchange_id>` e que outras DEXs podem ser integradas com `DEX_ADAPTER_MODULE=pacote.modulo:Classe`.
- Não perguntar o nome da subconta Nado no wizard curto: usar `NADO_SUBACCOUNT_NAME=default_1` como default operacional e só orientar descoberta se o usuário informar subconta customizada ou se `setup-check`/`doctor` falhar.
- Não tratar subconta como requisito obrigatório por padrão. O wizard deve avisar que o recomendado é operar em subconta, vault ou conta isolada quando a corretora/DEX oferecer esse recurso; a decisão final é do usuário e não deve ser hard-coded; se o usuário não usar esse modelo, exigir no mínimo API key/credencial dedicada sem saque e validar com `doctor`/dry-run.
- Não mandar link de cadastro nem perguntar “você consegue abrir o site?” no wizard curto; isso só entra se o usuário pedir passo a passo.
- Sempre validar com `venues`, `setup-check` e `doctor` antes de qualquer live.
- Live/mainnet só com sizing explícito e confirmação explícita.

## Abertura curta

> Vou configurar o trade automatizado em modo seguro: primeiro escolhemos DEX/CEX, depois diagnóstico/dry-run, sem trade. Só depois de validar as venues escolhidas a gente fala de live. 🔐

## Perguntas essenciais

### 1. Escolha de corretora/venue

**Motivo:** define quais integrações, credenciais e passos de configuração serão necessários.

> Quais venues você quer usar? Principais: DEX `nado` ou `hyperliquid`; CEX `kraken`, `binance`, `bybit`, `okx`, `kucoin`, `mexc`, `bitget` ou `gateio`. Também posso integrar outras CEXs via CCXT e outras DEXs por adapter. Responda, por exemplo: `DEX=nado CEX=kraken`, `CEX=binance`, `DEX=hyperliquid CEX=bybit` ou `outra`.

Roteamento rápido:
- `Nado`: DEX nativa da skill, usar `DEX_ID=nado`.
- `Hyperliquid`: usar o adapter builtin com `DEX_ID=hyperliquid`, `DEX_MARKET_TYPE=trade` ou `HYPERLIQUID_MARKET_TYPE=trade`, `HYPERLIQUID_WALLET_ADDRESS` e `HYPERLIQUID_PRIVATE_KEY`; `HYPERLIQUID_VAULT_ADDRESS` é opcional quando o usuario escolher vault.
- `Kraken`: default CEX, usar `CEX_ID=kraken` ou aliases legados `KRAKEN_*`.
- `Binance`: CEX via CCXT, usar `CEX_ID=binance`.
- `Bybit`: CEX via CCXT, usar `CEX_ID=bybit`; aceitar typo `bibyt` como `bybit`.
- `OKX`: CEX via CCXT, usar `CEX_ID=okx` e lembrar que normalmente exige password/passphrase.
- `KuCoin`: CEX via CCXT, usar `CEX_ID=kucoin` e lembrar que normalmente exige password/passphrase.
- `MEXC`: CEX via CCXT, usar `CEX_ID=mexc`.
- `Bitget`: CEX via CCXT, usar `CEX_ID=bitget` e lembrar que normalmente exige password/passphrase.
- `Gate.io`: CEX via CCXT, usar `CEX_ID=gateio`.
- Outras: usar `CEX_ID=<exchange_id CCXT>` ou `DEX_ADAPTER_MODULE=pacote.modulo:Classe`.

### 2. Modo de operação

**Motivo:** define quais credenciais e validações são necessárias.

> Qual modo você quer configurar agora: `dex_only` na DEX escolhida, `cex_only` na CEX escolhida ou `hedged` usando as duas venues?

### 3. Ambiente

**Motivo:** separa teste de execução real e evita confusão com mainnet.

> Vai validar em `testnet/sandbox`, `mainnet dry-run` ou já preparar `mainnet live` para depois?

### 4. Contas e credenciais já prontas

**Motivo:** eu não posso cadastrar conta nem receber segredos no chat; só preciso saber se o acesso e as envs já estão prontos no env/secret manager seguro.

> Você já tem conta/acesso nas venues escolhidas e as envs/secrets já estão salvas no env/secret manager seguro? Responda só `sim`, `não` ou `não sei`.

Checklist por modo:
- `dex_only` com Nado: `DEX_ID=nado`, `NADO_OWNER_PRIVATE_KEY`; opcional/recomendado `NADO_LINKED_SIGNER_PRIVATE_KEY`. `NADO_SUBACCOUNT_NAME=default_1` é opcional por padrão; só ajuste se a Nado/runtime usar outro nome.
- `dex_only` com Hyperliquid: `DEX_ID=hyperliquid`, `DEX_MARKET_TYPE=trade` ou `HYPERLIQUID_MARKET_TYPE=trade`, `HYPERLIQUID_WALLET_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, sandbox por `venues.dex.hyperliquid.sandbox` no `settings.json` e `HYPERLIQUID_VAULT_ADDRESS` opcional. Para outra DEX: `DEX_ADAPTER_MODULE=pacote.modulo:Classe`; `DEX_MARKET_TYPE=trade` só vale se o adapter ler esse parâmetro.
- `cex_only` com Kraken: `CEX_ID=kraken`, `KRAKEN_API_KEY_` ou `KRAKEN_API_KEY`, e `KRAKEN_API_SECRET`; subconta é opcional, o requisito é API key dedicada/sem saque na conta correta.
- `cex_only` com Binance: `CEX_ID=binance`, `CEX_MARKET_TYPE=trade|future|spot`, `BINANCE_API_KEY` e `BINANCE_API_SECRET`; aliases `CEX_API_KEY` e `CEX_API_SECRET` também são aceitos.
- `cex_only` com Bybit: `CEX_ID=bybit`, `CEX_MARKET_TYPE=trade|spot`, `BYBIT_API_KEY` e `BYBIT_API_SECRET`; aliases `CEX_API_KEY` e `CEX_API_SECRET` também são aceitos.
- `cex_only` com OKX: `CEX_ID=okx`, `CEX_MARKET_TYPE=trade|future|spot`, `OKX_API_KEY`, `OKX_API_SECRET` e `OKX_API_PASSWORD`; aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` também são aceitos.
- `cex_only` com KuCoin: `CEX_ID=kucoin`, `CEX_MARKET_TYPE=trade|future|spot`, `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` e `KUCOIN_API_PASSWORD`; aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` também são aceitos.
- `cex_only` com MEXC: `CEX_ID=mexc`, `CEX_MARKET_TYPE=trade|spot`, `MEXC_API_KEY` e `MEXC_API_SECRET`; aliases `CEX_API_KEY` e `CEX_API_SECRET` também são aceitos.
- `cex_only` com Bitget: `CEX_ID=bitget`, `CEX_MARKET_TYPE=trade|spot`, `BITGET_API_KEY`, `BITGET_API_SECRET` e `BITGET_API_PASSWORD`; aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` também são aceitos.
- `cex_only` com Gate.io: `CEX_ID=gateio`, `CEX_MARKET_TYPE=trade|spot`, `GATEIO_API_KEY` e `GATEIO_API_SECRET`; aliases `CEX_API_KEY` e `CEX_API_SECRET` também são aceitos.
- `cex_only` com outra CEX via CCXT: `CEX_ID=<exchange_id>`, `CEX_MARKET_TYPE=trade|future|spot`, `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` quando a corretora exigir.
- `hedged`: credenciais da DEX escolhida + credenciais da CEX escolhida. Para Nado, `NADO_SUBACCOUNT_NAME` continua sendo config não sensível opcional, não pergunta obrigatória do wizard curto.

### 5. Margem e risco

**Motivo:** comandos live são bloqueados sem sizing explícito.

> Qual tamanho você quer usar para validação: `--margem-usd`, `--valor-nominal` ou `--slots-margem-conta`? Se ainda não souber, responda `simular sem tamanho live`.

### 6. Modo de margem

**Motivo:** cross e isolated têm riscos bem diferentes.

> Prefere margem `cross`, `isolated` ou quer deixar eu sugerir depois do diagnóstico?

### 7. Stop por alvo

**Motivo:** define se o setup só realiza parciais ou se também reposiciona o stop conforme os alvos são atingidos.

> Quer o stop por alvo `desligado`, `entrada-no-tp1` ou `escada`? Recomendo começar com `desligado` no primeiro live; se quiser proteger lucro, `entrada-no-tp1` move o stop para a entrada após o TP1; `escada` move TP1->entrada, TP2->TP1, TP3->TP2. O usuário decide; não é hard-coded.

Roteamento rápido:
- `desligado` / `off`: mantém o stop original do setup ou do `--stop-loss-pct`; comportamento mais conservador para validar integração.
- `entrada-no-tp1` / `breakeven_on_tp1`: depois que TP1 executa parcial, o stop monitorado vai para o preço de entrada; TPs seguintes não sobem mais o stop.
- `escada` / `ladder`: depois de TP1 o stop vai para a entrada; depois de TP2 vai para TP1; depois de TP3 vai para TP2, até o último alvo fechar o restante.
- O stop movido é gerenciado pelo loop do `setup-live`; só afirmar recriação/cancelamento de ordem stop nativa quando a venue tiver suporte explícito implementado.

### 8. Universo de ativos dos setups direcionais

**Motivo:** o runtime bloqueia `all` em live direcional; cada setup usa uma allowlist para evitar analisar/entrar em ativo não aprovado.

> Vamos usar a allowlist padrão segura (`--symbol allowlist`). Quer revisar a lista por setup antes de rodar?

Padrão seguro atual:
- `institutional-strict`: BTC/USDT, BTC/USDC, ETH/USDT, ETH/USDC, TAO/USDT, TAO/USDC, SOL/USDT, SOL/USDC, BCH/USDT, BCH/USDC, XMR/USDT, XMR/USDC, LINK/USDT, LINK/USDC, ZEC/USDT, ZEC/USDC, DOT/USDT, DOT/USDC, HBAR/USDT, HBAR/USDC, TRX/USDT, TRX/USDC, LTC/USDT, LTC/USDC, ADA/USDT, ADA/USDC
- `bollinger-mean-reversion`: BTC/USDT, BTC/USDC, ETH/USDT, ETH/USDC, SOL/USDT, SOL/USDC, BCH/USDT, BCH/USDC, TAO/USDT, TAO/USDC, ZEC/USDT, ZEC/USDC, HBAR/USDT, HBAR/USDC, XMR/USDT, XMR/USDC, AVAX/USDT, AVAX/USDC, XRP/USDT, XRP/USDC, TRX/USDT, TRX/USDC, DOT/USDT, DOT/USDC, UNI/USDT, UNI/USDC, NEAR/USDT, NEAR/USDC, LTC/USDT, LTC/USDC
- `grid-strict`: BTC/USDT, BTC/USDC, ETH/USDT, ETH/USDC, HBAR/USDT, HBAR/USDC, SUI/USDT, SUI/USDC, XMR/USDT, XMR/USDC
- `low-stoch-storm`: BTC/USDT, BTC/USDC, ETH/USDT, ETH/USDC, TRX/USDT, TRX/USDC, LINK/USDT, LINK/USDC, XMR/USDT, XMR/USDC, SOL/USDT, SOL/USDC, AVAX/USDT, AVAX/USDC
- `divergence-and-volume-15m/1h/4h`: BTC/USDT, BTC/USDC, ETH/USDT, ETH/USDC, XMR/USDT, XMR/USDC, XRP/USDT, XRP/USDC

Fluxo padrão do usuário: `--symbol allowlist`. Para operação delta neutra/`hedged`, pode usar `--symbol all` quando quiser avaliar todos os pares comuns das venues escolhidas; Nado/Kraken é apenas o default. Para `dex_only`/`cex_only`, não sugerir `--symbol all`; usar allowlist ou símbolo explícito aprovado. Entrada real ainda depende de existir par comum e sinal válido. Cada setup novo precisa declarar uma allowlist própria com os ativos mais lucrativos/validados naquele setup antes de ser sugerido para live.

### 9. Próximo passo seguro

**Motivo:** confirma que vamos validar antes de operar.

> Posso rodar primeiro `venues`, `setup-check` e `doctor` sem exibir segredo e sem trade?

## Confirmação final

> Plano: DEX `{dex_id}`, CEX `{cex_id}`, modo `{execution_mode}`, ambiente `{environment}`, secrets `{account_and_secrets_status}`, sizing `{sizing}`, margem `{margin_mode}`, stop por alvo `{target_stop_mode}`. Próximo passo seguro: `venues` + `setup-check` + `doctor`, sem trade. Confirmo?

## Payload esperado para runtime

```json
{
  "venue_selection": "DEX=nado CEX=kraken|DEX=hyperliquid CEX=bybit|CEX=binance|outra",
  "dex_id": "nado|hyperliquid|custom",
  "cex_id": "kraken|binance|bybit|okx|kucoin|mexc|bitget|gateio|custom",
  "dex_adapter_status": "builtin|required|configured|not_applicable",
  "cex_market_type": "trade|future|spot|unknown",
  "execution_mode": "dex_only|cex_only|hedged",
  "environment": "testnet|sandbox|mainnet_dry_run|mainnet_live_later",
  "account_and_secrets_status": "yes|no|unknown",
  "sizing": "margin_usd|notional|account_margin_slots|dry_run_only",
  "margin_mode": "cross|isolated|suggest_after_diagnostics",
  "target_stop_mode": "desligado|entrada-no-tp1|escada",
  "setup_live_symbol_scope": "allowlist|review_allowlist|explicit_symbol",
  "next_safe_step": "venues+setup-check+doctor",
  "questionnaire_completed": true
}
```

## Quando usar o guia detalhado

Leia `references/onboarding-detalhado.md` somente se o usuário pedir:
- como descobrir ou ajustar uma subconta/nome Nado não padrão, quando o usuário realmente usar esse modelo;
- como configurar Ink/bridge/collateral;
- como criar API key Kraken, Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io ou outra CEX;
- onde salvar envs no OpenClaw;
- configurar Hyperliquid builtin em mainnet/operação real, API wallet/agent wallet, vault ou outra DEX via adapter;
- troubleshooting detalhado.

<!-- OPENCLAW_WIZARD_PATHS_START -->

## Escolha inicial do wizard — Caminho iniciante ou avançado

Antes da primeira pergunta operacional, ofereça explicitamente os dois caminhos ao usuário:

> Como você quer configurar/usar **Trade Automatizado OpenClaw** agora?
> 1. **Caminho iniciante** — eu te guio passo a passo, com linguagem simples e só as decisões essenciais.
> 2. **Caminho avançado** — configuração completa, parâmetros, validações/dry-run quando aplicável e rastreabilidade operacional.

Regras obrigatórias:
- explicar a diferença entre os dois caminhos em uma frase antes de continuar;
- aceitar respostas como `iniciante`, `1`, `guiado`, `avançado`, `avancado`, `2` ou `completo`;
- permitir trocar de caminho durante o fluxo quando isso não quebrar segurança, configuração ou rastreabilidade;
- manter uma pergunta por vez;
- nunca pedir API key, secret, token, webhook, seed, private key ou qualquer segredo no chat;
- se precisar de credencial, pedir apenas confirmação de que ela já está salva em env/Secret Manager/OpenClaw e orientar pelo nome da variável quando necessário;
- antes de execução real, resumir escolhas e pedir confirmação explícita;
- quando existir comando seguro, usar diagnóstico/dry-run antes de ação live.

### Caminho iniciante — passo a passo guiado

1. **Explicar o resultado esperado.** Dizer em termos simples o que a skill entrega e em quais casos usar.
2. **Coletar o mínimo seguro.** Perguntar só objetivo, ativo/wallet/chain/fonte pública, horizonte e tolerância a risco quando aplicável.
3. **Usar defaults conservadores.** Evitar parâmetros técnicos se o usuário não pedir; priorizar leitura segura e educativa.
4. **Confirmar plano.** Resumir escolhas, limitações e próximo passo antes de rodar qualquer análise ou configuração.
5. **Entregar leitura acionável.** Mostrar resultado, riscos, próximos passos e como refazer/trocar para o modo avançado.

Foco deste caminho: validar modo, ambiente, secrets salvos e rodar setup-check/doctor sem trade.

### Caminho avançado — passo a passo completo

1. **Validar runtime e pré-requisitos.** Checar path da skill, versão, PROJECT.md/RELEASE_NOTES quando existirem, credenciais já salvas e cobertura real.
2. **Coletar parâmetros completos.** Perguntar filtros, exchanges/chains/fontes, thresholds, frequência, destino de saída e overrides compatíveis com o runtime.
3. **Rodar validações seguras.** Usar doctor/setup-check/dry-run/preview/simulação quando a skill oferecer; reportar bloqueios sem expor segredo.
4. **Executar ou preparar automação.** Só seguir para ação externa/live após confirmação explícita e com guardrails ativos.
5. **Registrar rastreabilidade.** Atualizar PRD/README/SKILL/PROJECT/RELEASE_NOTES quando houver mudança de UX, config, release/tag/commit ou path runtime.

Foco deste caminho: configurar hedge, sizing, margem, conta/subconta customizada quando necessário, dry-run, TP/SL e guardrails live.

<!-- OPENCLAW_WIZARD_PATHS_END -->

<!-- OPENCLAW_SECRET_GUIDANCE_START -->

## Padrão OpenClaw para chaves e segredos

Quando a skill precisar de API key, token, webhook, OAuth, private key, seed phrase ou qualquer segredo:

- **não pedir, receber, colar, repetir nem salvar o valor no chat**;
- explicar que chaves e segredos devem ser configurados pelo secret manager disponivel quando possível;
- para **chaves de provider de IA/LLM**: orientar `secret manager > Chaves LLM`;
- para **chaves de serviço/API externa** como `GEMINI_API_KEY`, `DUNE_API_KEY`, GitHub, SERPER, webhooks e integrações: orientar `secret manager > Chaves de Serviço`;
- para **OAuth Anthropic**: orientar `secret manager > OAuth Token`;
- no chat, pedir no máximo confirmação de status: `já está salvo`, `não está salvo` ou `não sei`;
- se precisar referenciar uma credencial, usar apenas o **nome da variável/env**, nunca o valor;
- se a skill rodar fora do OpenClaw, orientar um cofre/secret manager ou arquivo local seguro fora do Git, com permissão restrita.

Frase padrão para o wizard:

> Essa skill precisa de `{NOME_DA_ENV}`. Por segurança, não cole a chave aqui. Configure em `secret manager > Chaves de Serviço` e me diga apenas se já está salvo.

<!-- OPENCLAW_SECRET_GUIDANCE_END -->
