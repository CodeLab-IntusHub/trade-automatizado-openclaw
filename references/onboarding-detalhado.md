# Questionário de onboarding — Trade Automatizado OpenClaw

Use este arquivo quando o first run obrigatório disparar ou quando o usuário pedir para configurar/refazer o wizard da skill.

Regras do wizard:
- conduzir em PT-BR;
- fazer uma pergunta por vez;
- explicar rapidamente o motivo da pergunta;
- nunca pedir segredo/private key/API secret no chat;
- pedir apenas confirmação de nomes de env/secret configurados;
- não enviar referral, inviteCode, shortlink ou link rastreado; quando precisar orientar cadastro, citar apenas domínio oficial limpo;
- se o secret manager não mostrar área de Secrets/Environment/Service Keys, não insistir em caminho visual inexistente; usar rota operacional por env/secret manager disponível ou pedir habilitação ao operador;
- dry-run sempre antes de live;
- subconta não é requisito obrigatório por padrão, mas é o modelo recomendado quando a corretora/DEX oferecer esse recurso; recomendar operar em subconta, vault ou conta isolada, deixando claro que a decisão final é do usuário e não deve ser hard-coded; se o usuário não usar esse modelo, exigir no mínimo API key/credencial dedicada sem saque e validação por `doctor`/dry-run;
- live/mainnet só com sizing explícito e confirmação explícita.

### Questionário completo sugerido

#### 0. Escolha de corretora/venue e integração

> Primeiro vamos escolher as venues. Principais opções: DEX `Nado` ou `Hyperliquid`; CEX `Kraken`, `Binance`, `Bybit`, `OKX`, `KuCoin`, `MEXC`, `Bitget` ou `Gate.io`. A skill também integra outras CEXs suportadas pelo CCXT e outras DEXs por adapter Python. Qual combinação você quer usar?

**Regras de roteamento:**

1. Se o usuário não escolher, usar default seguro `DEX_ID=nado` e `CEX_ID=kraken`.
2. Se digitar `bibyt`, normalizar para `bybit`.
3. Se escolher CEX não-Kraken, usar `CEX_ID=<exchange_id CCXT>` e credenciais genéricas `CEX_API_KEY`, `CEX_API_SECRET`, `CEX_API_PASSWORD` quando exigido; aceitar envs específicas (`BINANCE_*`, `BYBIT_*`, `OKX_*`, `KUCOIN_*`, `MEXC_*`, `BITGET_*`, `GATEIO_*`).
4. Se escolher Hyperliquid, usar o adapter builtin com `DEX_ID=hyperliquid`, `HYPERLIQUID_WALLET_ADDRESS` e `HYPERLIQUID_PRIVATE_KEY`; `HYPERLIQUID_VAULT_ADDRESS` é opcional quando o usuário escolher vault.
5. Se escolher outra DEX não-Nado/Hyperliquid, exigir `DEX_ADAPTER_MODULE=pacote.modulo:Classe` antes de live; sem adapter validado, orientar configuração e diagnóstico, mas não executar trade real.
6. Antes de orientar qualquer secret, confirmar o modo: `dex_only`, `cex_only` ou `hedged`.
7. Sempre avisar: a integração genérica não garante que todo recurso live exista em toda corretora; validar `setLeverage`, `setMarginMode`, posições, saldo, ordens trigger/SL/TP e símbolos com `venues`, `symbols`, `cex-accounts` e dry-run.

**Checklist rápido por venue principal:**

- **Nado:** `DEX_ID=nado`; exige wallet/Ink e `NADO_OWNER_PRIVATE_KEY` no Secret Manager; `NADO_SUBACCOUNT_NAME` é opcional para nome customizado; linked signer recomendado via `NADO_LINKED_SIGNER_PRIVATE_KEY`.
- **Hyperliquid:** `DEX_ID=hyperliquid`; exige `HYPERLIQUID_WALLET_ADDRESS` com o endereço real da conta/vault e `HYPERLIQUID_PRIVATE_KEY` no Secret Manager; `HYPERLIQUID_VAULT_ADDRESS` é opcional.
- **Kraken:** `CEX_ID=kraken`; usar `KRAKEN_API_KEY_` ou `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`; sem saque/withdraw.
- **Binance:** `CEX_ID=binance`; usar `CEX_MARKET_TYPE=trade` para perps/long-short; a skill normaliza para CCXT `swap`; `BINANCE_API_KEY`/`BINANCE_API_SECRET` ou `CEX_*`.
- **Bybit:** `CEX_ID=bybit`; usar `CEX_MARKET_TYPE=trade`; `BYBIT_API_KEY`/`BYBIT_API_SECRET` ou `CEX_*`; observar restrições regionais/API se aparecer 403.
- **OKX:** `CEX_ID=okx`; usar `CEX_MARKET_TYPE=trade`; exige `OKX_API_PASSWORD`/passphrase além de key/secret.
- **KuCoin:** `CEX_ID=kucoin`; usar `CEX_MARKET_TYPE=trade|future`; exige `KUCOIN_API_PASSWORD`/passphrase além de key/secret.
- **MEXC:** `CEX_ID=mexc`; usar `CEX_MARKET_TYPE=trade`; exige `MEXC_API_KEY` e `MEXC_API_SECRET`.
- **Bitget:** `CEX_ID=bitget`; usar `CEX_MARKET_TYPE=trade`; exige `BITGET_API_PASSWORD`/passphrase além de key/secret.
- **Gate.io:** `CEX_ID=gateio`; usar `CEX_MARKET_TYPE=trade`; exige `GATEIO_API_KEY` e `GATEIO_API_SECRET`.
- **Outras CEXs:** `CEX_ID=<exchange_id CCXT>`, `CEX_MARKET_TYPE=trade|future|spot`, credenciais `CEX_*`, validação de recursos antes de live.
- **Outras DEXs:** `DEX_ID=<id>`, `DEX_ADAPTER_MODULE=pacote.modulo:Classe`, `DEX_CONFIG_JSON` sem segredos e validação de interface antes de live.

#### 1. Abertura segura

> Vou validar primeiro em modo seguro, sem trade, e só depois liberamos execução live com confirmação. 🔐 Você quer operar em qual modo: `dex_only` na DEX escolhida, `cex_only` na CEX escolhida ou `hedged` usando as duas venues?

#### 2. Criar/acessar contas

> Se o usuário pedir passo a passo de conta, oriente de forma neutra: acessar a venue escolhida pelo domínio oficial limpo, criar/verificar a conta por conta própria e depois voltar quando o acesso estiver pronto. ✅ Você já tem acesso às plataformas que vai usar neste setup?

#### 3. Variáveis da Nado

> Para Nado, o caminho é: abrir a Nado, conectar a wallet, selecionar Ink e preparar uma chave operacional. 🔑 Você já salvou no secret/env seguro do OpenClaw a variável `NADO_OWNER_PRIVATE_KEY`? `NADO_SUBACCOUNT_NAME=default_1` é opcional e só deve ser ajustado se você usa outro nome ou se o diagnóstico falhar.

Se o usuário não souber o que salvar, explique sem pedir segredo no chat:

**Passo a passo Nado — baseado na documentação oficial:**

> Fonte operacional: docs da Nado indicam o fluxo **escolher wallet → adicionar INK → obter ETH para gas → obter collateral → Connect Wallet → Portfolio > Deposit → Unified/Isolated Margin → Trade perpetuals**. A Nado usa **assinaturas de wallet**, não API key tradicional. Subcontas não existem até o primeiro depósito de pelo menos **5 USDT0 equivalente**. Linked signer é a função de **1-Click Trading** / chave separada autorizada pela wallet principal.

1. **Escolher a wallet**
   - usar uma wallet compatível com EVM/Ink;
   - opções citadas pela doc: **MetaMask**, **Rabby Wallet** ou **WalletConnect**;
   - para valores maiores, preferir hardware wallet/Ledger via WalletConnect quando fizer sentido;
   - confirmar que a conta escolhida é a conta da estratégia.
2. **Adicionar a rede INK na wallet**
   - caminho fácil: abrir [ChainList](https://chainlist.org/), pesquisar **Ink**, clicar **Add to MetaMask** / adicionar à wallet;
   - caminho manual na wallet:
     - abrir configurações de rede;
     - adicionar rede/custom network;
     - **Network Name:** `INK`;
     - **RPC URL:** `https://rpc-gel.inkonchain.com`;
     - **Chain ID:** `57073`;
     - **Currency Symbol:** `ETH`;
     - **Block Explorer:** `https://explorer.inkonchain.com`;
   - depois selecionar a rede **Ink** no seletor de rede da wallet.
3. **Escolher bridge oficial/suportada para chegar na Ink**
   - para **USDT → USDT0 na Ink**, a doc da Nado aponta a bridge nativa **USDT0**: `https://usdt0.to`;
   - para **ETH → Ink**, a doc da Nado cita bridges suportadas/recomendadas:
     - **Superbridge**: `https://superbridge.app/`;
     - **Bungee**: `https://bungee.exchange`;
     - **Relay**: `https://relay.link`;
   - a doc da Ink também lista bridges para Ink:
     - **Across**: Ink Mainnet;
     - **Brid.gg**: Ink Mainnet e Ink Sepolia;
     - **Bungee**: Ink Mainnet;
     - **Gelato Bridge**: Ink Mainnet e Ink Sepolia;
     - **Rhino.fi**: Ink Mainnet;
     - **Reservoir**: bridge/cross-chain relayer;
     - **Superbridge**: Ink Mainnet e Ink Sepolia;
     - **Ink Sepolia Bridge**: Ink Sepolia.
4. **Conferir redes aceitas antes de fazer bridge**
   - destino obrigatório para produção: **Ink Mainnet**;
   - destino de teste: **Ink Sepolia**;
   - fontes citadas pela Nado como exemplos aceitos:
     - **Ethereum**;
     - **Arbitrum**;
     - **Base**;
     - **Polygon**;
     - outras EVM chains podem aparecer conforme a bridge, mas devem ser confirmadas na tela da bridge antes de assinar;
   - regra prática: a chain de origem deve ser exatamente onde o ativo está hoje, e o destino deve ser **Ink**.
5. **Colocar ETH na Ink para gas**
   - a doc recomenda ter ETH na Ink para taxas;
   - opção CEX: sacar ETH diretamente para a rede Ink, quando a corretora oferecer esse recurso;
   - opção bridge: usar uma das bridges acima;
   - no bridge:
     - conectar a wallet;
     - escolher a chain de origem, ex.: Ethereum, Arbitrum, Base ou Polygon;
     - escolher **Ink** como destino;
     - escolher **ETH**;
     - revisar taxa, rota e tempo estimado;
     - confirmar se o endereço de destino é sua própria wallet;
     - assinar na wallet;
     - aguardar confirmação e conferir no bridge/explorer;
   - se der erro de gas, adicionar mais ETH na Ink.
6. **Colocar collateral/trading funds na Ink**
   - para collateral principal, preferir **USDT0 na Ink** quando a estratégia/Nado exigir stable;
   - para USDT0, usar preferencialmente `usdt0.to` quando estiver fazendo USDT → USDT0;
   - assets mencionados nas docs para bridge/depósito incluem **ETH**, **USDT0**, **USDC**, **wETH**, **wBTC** e **kBTC**;
   - se o token não aparecer na wallet, importar token manualmente usando o contrato correto da rede Ink;
   - sempre verificar endereço/contrato no explorer ou fonte oficial;
   - não enviar token de outra rede para endereço errado.
7. **Conectar a wallet na Nado**
   - abrir a Nado pelo domínio oficial `https://app.nado.xyz`;
   - clicar **Connect Wallet** no canto superior direito;
   - escolher MetaMask/Rabby/WalletConnect;
   - confirmar na wallet;
   - garantir que a wallet está na rede **Ink**;
   - conferir se o endereço conectado é o correto.
8. **Fazer o primeiro depósito e validar conta/subconta quando aplicável**
   - na Nado, abrir **Portfolio**;
   - clicar em **Deposit**;
   - escolher o asset, normalmente USDT0;
   - digitar valor de pelo menos **5 USDT0 equivalente**;
   - confirmar approve/allowance se a UI pedir;
   - confirmar o depósito na wallet;
   - aguardar a confirmação;
   - se a Nado criar/exibir subconta automaticamente no primeiro depósito, tratar isso como detalhe da venue, não como pergunta obrigatória do wizard;
   - se o runtime precisar de nome diferente do default, salvar exatamente o nome validado pelo `doctor`/runtime em `NADO_SUBACCOUNT_NAME`; caso contrário, não perguntar nem alterar.
9. **Confirmar margem e produto antes de operar**
   - abrir o terminal de trading/perpetuals;
   - escolher mercado perp disponível, ex.: BTC-PERP/ETH-PERP ou equivalente;
   - entender que **Unified Margin** é o padrão da Nado: depósitos, posições e PnL ficam em um pool de collateral;
   - para limitar risco por posição, usar **Isolated Margin** no order panel ou configurar `--margin-mode isolated` na skill;
   - em Unified Margin, o seletor de leverage controla sizing visual/máximo, mas a margem real é calculada pelo risk engine da Nado.
10. **Configurar 1-Click Trading / linked signer pela UI, se disponível**
   - abrir a Nado UI;
   - conectar wallet;
   - abrir **Settings** / ícone de engrenagem;
   - procurar **1-Click Trading**;
   - clicar **Enable**;
   - a UI gera uma chave aleatória, linka na subconta e guarda criptografada no navegador;
   - isso facilita trading na UI, mas se depois linkar outro signer via API, o 1-Click da UI pode parar de bater com o signer antigo.
11. **Configurar linked signer via API/dev, se for trading automatizado**
   - gerar uma chave nova e separada para trading;
   - guardar essa private key com segurança;
   - pegar o endereço público dessa chave;
   - assinar a ação **LinkSigner** com a **main wallet/owner**, não com o linked signer;
   - conferir se o linked signer atual bate com o endereço esperado;
   - salvar a private key do linked signer como `NADO_LINKED_SIGNER_PRIVATE_KEY` no secret/env seguro;
   - lembrar: se houver subconta/linked signer na venue, cada contexto pode ter exatamente um linked signer.
12. **Revogar linked signer, se necessário**
    - usar a main wallet/owner;
    - executar a revogação/link para endereço zero;
    - depois remover `NADO_LINKED_SIGNER_PRIVATE_KEY` do OpenClaw ou substituir por uma nova;
    - rodar `doctor` para confirmar.
13. **Owner fallback — só quando não usar linked signer**
    - Nado permite assinar com a main wallet ou com linked signer;
    - se não houver linked signer, a skill pode usar owner fallback conforme regra local;
    - nesse caso, exportar a private key pela própria wallet, não pela Nado:
      - abrir a extensão/app da wallet;
      - selecionar a conta conectada na Nado;
      - abrir **Account details** / **Detalhes da conta**;
      - clicar **Export private key** / **Exportar chave privada**;
      - confirmar senha/biometria;
      - salvar como `NADO_OWNER_PRIVATE_KEY` no secret/env seguro;
    - **nunca colar private key no chat, arquivo, print ou Git**.
14. **Troubleshooting Nado antes do live**
    - wallet não troca para Ink: selecionar Ink no dropdown ou re-adicionar a rede;
    - `Insufficient Gas Fee`: falta ETH na Ink;
    - token não aparece: importar token custom com contrato da Ink;
    - subconta/contexto não existe/`exists=false`: fazer depósito inicial >= 5 USDT0 equivalente e aguardar 30-60s; não transformar isso em requisito do wizard curto;
    - depósito travado: conferir transação no Ink Explorer e no bridge usado;
    - linked signer mismatch: relinkar signer correto ou remover env inválida;
    - depois de qualquer ajuste, rodar `setup-check` e `doctor` sem exibir segredo.

**Variáveis Nado:**

- `NADO_OWNER_PRIVATE_KEY`: private key da wallet/owner operacional da Nado; salvar somente no secret/env seguro do OpenClaw.
- `NADO_SUBACCOUNT_NAME`: config não sensível e opcional; default operacional `default_1`. Só perguntar/alterar se o usuário usa nome/subconta customizada ou se `setup-check`/`doctor` indicar falha.
- `NADO_NETWORK`: `mainnet` ou `testnet`.
- `NADO_REQUIRE_LINKED_SIGNER`: normalmente `true` quando quiser exigir linked signer.
- `NADO_LINKED_SIGNER_PRIVATE_KEY`: opcional/recomendado quando houver linked signer limitado válido.
- `NADO_ALLOW_OWNER_FALLBACK`: manter `false` por padrão; só usar fallback privilegiado com confirmação explícita quando aplicável.
- Se `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a skill pode usar owner fallback conforme regra operacional local; se estiver presente mas inválido, orientar a corrigir/remover no secret/env antes do live.

#### 4. Variáveis da Kraken

> Para Kraken, acesse a Kraken Pro pelo domínio oficial. O recomendado é operar em subconta ou conta isolada com API key dedicada sem saque; subconta não é requisito obrigatório da skill. 🦑 Você já salvou `KRAKEN_API_KEY_` e `KRAKEN_API_SECRET`?

Se o usuário não souber o que salvar, explique:

**Passo a passo Kraken Pro — baseado na documentação oficial:**

> Fonte operacional: suporte da Kraken orienta criar API key via **Kraken Pro → profile icon/top right → Settings → API tab → Create API key**. A Kraken diferencia **API Key** pública e **Private key/API Secret** privada. A private key/secret nunca deve ser enviada no chat.

1. **Entrar na Kraken Pro**
   - abrir a Kraken Pro pelo domínio oficial;
   - fazer login na conta que será usada pela estratégia;
   - completar 2FA/e-mail se a Kraken pedir.
2. **Abrir a área correta de API**
   - clicar no **ícone de perfil/conta no canto superior direito**;
   - clicar em **Settings** / **Configurações**;
   - abrir a aba **API**;
   - clicar em **Create API key** / **Criar API key**.
3. **Nomear a chave**
   - no campo de descrição/nome, usar algo único e claro;
   - sugestão: `delta-trade-bot`;
   - não reutilizar uma API key antiga de outro agente/app.
4. **Permissões para diagnóstico/dry-run**
   - habilitar **Query Funds** para saldo/balanço;
   - habilitar **Query Open Orders & Trades** para ordens abertas e posições;
   - habilitar **Query Closed Orders & Trades** se quiser histórico/fechamentos;
   - opcional: **Query Ledger Entries** para histórico contábil;
   - não habilitar permissões de saque.
5. **Permissões adicionais para live**
   - habilitar **Modify Orders** para criar/editar ordens;
   - habilitar **Cancel/Close Orders** para cancelar/fechar ordens;
   - manter **Withdraw Funds** desligado;
   - manter **Deposit Funds** desligado salvo se houver motivo específico externo à skill.
6. **Configurações opcionais**
   - **Nonce Window**: deixar padrão, salvo erro recorrente de nonce;
   - **IP whitelist**: usar só se souber o IP fixo da execução;
   - **Key Expiration**: opcional; pode deixar sem expiração se for operação recorrente;
   - **API key 2FA**: só ativar se o cliente/sistema suportar enviar `otp` nas chamadas privadas.
7. **Gerar a key**
   - clicar em **Generate key** / **Gerar chave**;
   - se a Kraken pedir confirmação 2FA/e-mail, concluir a confirmação;
   - aguardar a tela que mostra a key pública e a private key/secret.
8. **Salvar os dois valores corretos no OpenClaw**
   - copiar **API Key** pública e salvar como `KRAKEN_API_KEY_`;
   - copiar **Private key** / **API Secret** e salvar como `KRAKEN_API_SECRET`;
   - tratar o secret como senha: a Kraken avisa para salvar com segurança e não guardar sem criptografia.
9. **Salvar parâmetros da skill**
   - `KRAKEN_VENUE=futures` para futuros/perpetuals — salvar preferencialmente no arquivo de configuração não sensível do workspace/state;
   - `venues.cex.kraken.sandbox: false` no `settings.json` para conta real — **não** salvar `KRAKEN_SANDBOX` no arquivo de configuração: a variável de ambiente vence o `settings.json` e o deixa sem efeito;
   - `KRAKEN_ALLOW_MAIN_ACCOUNT=false` como legado/conservador, sem exigir subaccount.
10. **Validar sem exibir segredo**
   - pedir para rodar `kraken-accounts`;
   - depois `setup-check`;
   - depois `doctor`;
   - se aparecer `Permission denied`, revisar permissões na Kraken em **Settings → API**;
   - se aparecer `Invalid key`, revisar se a key está ativa/correta;
   - se aparecer `Invalid signature`, revisar se o `KRAKEN_API_SECRET` foi copiado corretamente;
   - se aparecer `Invalid nonce`, evitar usar a mesma API key em múltiplos agentes/processos ao mesmo tempo.

**Variáveis Kraken:**

- `KRAKEN_API_KEY_`: chave pública/API key da Kraken; no OpenClaw usamos este alias por compatibilidade local.
- `KRAKEN_API_SECRET`: secret da API key; nunca colar no chat.
- `KRAKEN_VENUE`: `futures` por padrão quando for perp/futuros; não é segredo, use o arquivo `~/.openclaw/workspace/trade-automatizado-openclaw.config.env` ou `~/.openclaw/state/trade-automatizado-openclaw/config.env`.
- sandbox: configure em `settings.json`, na chave `venues.cex.kraken.sandbox` (`false` para mainnet/live, `true` para sandbox). A chave vale para a família inteira — `kraken-spot` e `krakenfutures` herdam dela. A variável `KRAKEN_SANDBOX` continua sendo lida, mas entra na camada de ambiente e **vence o arquivo**; se ela existir, o carregamento avisa qual chave foi encoberta.
- `KRAKEN_ALLOW_MAIN_ACCOUNT`: legado/opcional; subaccount não é requisito obrigatório da skill.
- Subaccount/conta isolada continua recomendada para organização de risco, mas não deve bloquear execução por si só.

**Permissões Kraken recomendadas:**

- Para diagnóstico/dry-run: leitura de conta, saldos, posições, mercados e ordens.
- Para live: leitura + criação/cancelamento de ordens.
- Nunca habilitar saque/withdraw para esta skill.

#### 4A. Variáveis da Binance

**Referência CCXT para CEXs:** use `CEX_MARKET_TYPE=trade` como valor amigável para perps/long-short em Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io e outras CEXs via CCXT. A skill normaliza `trade` para `swap` antes de chamar CCXT. Para Kraken builtin, `trade` normaliza para `futures`. Use `spot` ou `future` somente quando o produto/venue exigir explicitamente.


> Para Binance, o recomendado é operar em subconta/conta isolada quando a corretora oferecer esse recurso e usar uma API key dedicada para a estratégia, com leitura e trading, sem saque. Você já salvou `BINANCE_API_KEY` e `BINANCE_API_SECRET` ou os aliases `CEX_API_KEY` e `CEX_API_SECRET` no secret/env seguro do OpenClaw?

**Passo a passo Binance:**

1. Definir `CEX_ID=binance`.
2. Definir `CEX_MARKET_TYPE=trade` para perps/futures USDT-margined e long-short; a skill normaliza para CCXT `swap`; usar `future` ou `spot` só se o setup exigir.
3. Entrar na conta Binance pelo domínio oficial e abrir a área de gerenciamento de API.
4. Criar uma API key exclusiva para `trade-automatizado-openclaw`.
5. Habilitar leitura de conta/mercados/saldos.
6. Habilitar trading apenas se for executar live; manter saque/withdraw desabilitado.
7. Se usar whitelist de IP, confirmar que o runtime tem IP fixo; se não souber, deixar sem whitelist até o operador definir o ambiente correto.
8. Salvar `BINANCE_API_KEY` e `BINANCE_API_SECRET` no Secret Manager/OpenClaw, ou usar `CEX_API_KEY` e `CEX_API_SECRET` se essa for a única CEX ativa.
9. Declarar `venues.cex.<venue>.sandbox: true` no `settings.json` apenas se estiver usando testnet/sandbox compatível; manter `false` para conta real só depois de validar.
10. Rodar `python3 workspace/run.py venues`, `cex-accounts`, `symbols` e dry-run antes de live.

**Variáveis Binance:**

- `CEX_ID=binance`
- `CEX_MARKET_TYPE=trade|future|spot`
- `BINANCE_API_KEY` ou `CEX_API_KEY`
- `BINANCE_API_SECRET` ou `CEX_API_SECRET`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)
- `CEX_OPTIONS_JSON={...}` quando precisar passar opção CCXT não sensível.

#### 4B. Variáveis da Bybit

> Para Bybit, prefira subconta/conta isolada quando a corretora oferecer esse recurso e use uma API key dedicada de leitura/trade e sem saque. Se o usuário escreveu `bibyt`, trate como `bybit`. Você já salvou `BYBIT_API_KEY` e `BYBIT_API_SECRET` ou os aliases `CEX_API_KEY` e `CEX_API_SECRET`?

**Passo a passo Bybit:**

1. Definir `CEX_ID=bybit`.
2. Definir `CEX_MARKET_TYPE=trade` para contratos perp/long-short; a skill normaliza para CCXT `swap`.
3. Entrar na Bybit pelo domínio oficial ou testnet oficial quando for sandbox.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Habilitar leitura de conta, saldos, ordens e posições.
6. Habilitar trade apenas para live; manter saque/withdraw desabilitado.
7. Observar que a API pode ter restrições regionais; se retornar `403 Forbidden`, não insistir no live e escolher outra venue permitida/operacional.
8. Salvar `BYBIT_API_KEY` e `BYBIT_API_SECRET` no OpenClaw, ou `CEX_API_KEY` e `CEX_API_SECRET` se for a CEX ativa.
9. Declarar `venues.cex.<venue>.sandbox: true` no `settings.json` para testnet quando aplicável.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run.

**Variáveis Bybit:**

- `CEX_ID=bybit`
- `CEX_MARKET_TYPE=trade|spot`
- `BYBIT_API_KEY` ou `CEX_API_KEY`
- `BYBIT_API_SECRET` ou `CEX_API_SECRET`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4C. Variáveis da OKX

> Para OKX, além de API key e secret, normalmente há uma password/passphrase da API. Você já salvou `OKX_API_KEY`, `OKX_API_SECRET` e `OKX_API_PASSWORD`, ou os aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`?

**Passo a passo OKX:**

1. Definir `CEX_ID=okx`.
2. Definir `CEX_MARKET_TYPE=trade` para perps/long-short; a skill normaliza para CCXT `swap`.
3. Entrar na OKX pelo domínio oficial e abrir a área de API.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Definir uma passphrase/password da API e salvar somente no Secret Manager.
6. Habilitar leitura e trading quando for live; manter saque/withdraw desabilitado.
7. Se houver IP whitelist, usar apenas quando o runtime tiver IP fixo confirmado.
8. Salvar `OKX_API_KEY`, `OKX_API_SECRET` e `OKX_API_PASSWORD`; aliases genéricos `CEX_*` também são aceitos.
9. Declarar `venues.cex.<venue>.sandbox: true` no `settings.json` apenas quando estiver em demo/sandbox compatível.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run.

**Variáveis OKX:**

- `CEX_ID=okx`
- `CEX_MARKET_TYPE=trade|future|spot`
- `OKX_API_KEY` ou `CEX_API_KEY`
- `OKX_API_SECRET` ou `CEX_API_SECRET`
- `OKX_API_PASSWORD` ou `CEX_API_PASSWORD`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4D. Variáveis da KuCoin

> Para KuCoin, normalmente a API exige key, secret e passphrase/password. Prefira subconta/conta isolada quando a corretora oferecer esse recurso e use uma API key dedicada de leitura/trade e sem saque. Você já salvou `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` e `KUCOIN_API_PASSWORD`, ou os aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`?

**Passo a passo KuCoin:**

1. Definir `CEX_ID=kucoin`.
2. Definir `CEX_MARKET_TYPE=trade`, `future` ou `spot` conforme o produto usado; `trade` normaliza para CCXT `swap`.
3. Entrar na KuCoin pelo domínio oficial e abrir a área de API.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Gerar/definir a passphrase/password da API e salvar somente no secret manager.
6. Habilitar leitura de conta, saldos, ordens e posições.
7. Habilitar trading apenas para live; manter saque/withdraw desabilitado.
8. Se houver IP whitelist, usar apenas quando o runtime tiver IP fixo confirmado.
9. Salvar `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` e `KUCOIN_API_PASSWORD`; aliases genéricos `CEX_*` também são aceitos.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run antes de live.

**Variáveis KuCoin:**

- `CEX_ID=kucoin`
- `CEX_MARKET_TYPE=trade|future|spot`
- `KUCOIN_API_KEY` ou `CEX_API_KEY`
- `KUCOIN_API_SECRET` ou `CEX_API_SECRET`
- `KUCOIN_API_PASSWORD` ou `CEX_API_PASSWORD`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4E. Variáveis da MEXC

> Para MEXC, prefira subconta/conta isolada quando a corretora oferecer esse recurso e use uma API key dedicada de leitura/trade e sem saque. Você já salvou `MEXC_API_KEY` e `MEXC_API_SECRET`, ou os aliases `CEX_API_KEY` e `CEX_API_SECRET`?

**Passo a passo MEXC:**

1. Definir `CEX_ID=mexc`.
2. Definir `CEX_MARKET_TYPE=trade` para perps/long-short; a skill normaliza para CCXT `swap`; usar `spot` só se o setup exigir.
3. Entrar na MEXC pelo domínio oficial e abrir a área de API.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Habilitar leitura de conta, saldos, ordens e posições.
6. Habilitar trading apenas para live; manter saque/withdraw desabilitado.
7. Se houver IP whitelist, usar apenas quando o runtime tiver IP fixo confirmado.
8. Salvar `MEXC_API_KEY` e `MEXC_API_SECRET`; aliases genéricos `CEX_*` também são aceitos.
9. Declarar `venues.cex.<venue>.sandbox: true` no `settings.json` somente se a conta/API estiver em ambiente sandbox compatível.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run antes de live.

**Variáveis MEXC:**

- `CEX_ID=mexc`
- `CEX_MARKET_TYPE=trade|spot`
- `MEXC_API_KEY` ou `CEX_API_KEY`
- `MEXC_API_SECRET` ou `CEX_API_SECRET`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4F. Variáveis da Bitget

> Para Bitget, normalmente a API exige key, secret e passphrase/password. Prefira subconta/conta isolada quando a corretora oferecer esse recurso e use uma API key dedicada de leitura/trade e sem saque. Você já salvou `BITGET_API_KEY`, `BITGET_API_SECRET` e `BITGET_API_PASSWORD`, ou os aliases `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`?

**Passo a passo Bitget:**

1. Definir `CEX_ID=bitget`.
2. Definir `CEX_MARKET_TYPE=trade` para contratos perp/long-short; a skill normaliza para CCXT `swap`.
3. Entrar na Bitget pelo domínio oficial e abrir a área de API.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Gerar/definir a passphrase/password da API e salvar somente no secret manager.
6. Habilitar leitura de conta, saldos, ordens e posições.
7. Habilitar trading apenas para live; manter saque/withdraw desabilitado.
8. Se houver IP whitelist, usar apenas quando o runtime tiver IP fixo confirmado.
9. Salvar `BITGET_API_KEY`, `BITGET_API_SECRET` e `BITGET_API_PASSWORD`; aliases genéricos `CEX_*` também são aceitos.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run antes de live.

**Variáveis Bitget:**

- `CEX_ID=bitget`
- `CEX_MARKET_TYPE=trade|spot`
- `BITGET_API_KEY` ou `CEX_API_KEY`
- `BITGET_API_SECRET` ou `CEX_API_SECRET`
- `BITGET_API_PASSWORD` ou `CEX_API_PASSWORD`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4G. Variáveis da Gate.io

> Para Gate.io, prefira subconta/conta isolada quando a corretora oferecer esse recurso e use uma API key dedicada de leitura/trade e sem saque. Você já salvou `GATEIO_API_KEY` e `GATEIO_API_SECRET`, ou os aliases `CEX_API_KEY` e `CEX_API_SECRET`?

**Passo a passo Gate.io:**

1. Definir `CEX_ID=gateio`.
2. Definir `CEX_MARKET_TYPE=trade` para perps/long-short; a skill normaliza para CCXT `swap`; usar `spot` só se o setup exigir.
3. Entrar na Gate.io pelo domínio oficial e abrir a área de API.
4. Criar API key dedicada para esta skill, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso.
5. Habilitar leitura de conta, saldos, ordens e posições.
6. Habilitar trading apenas para live; manter saque/withdraw desabilitado.
7. Se houver IP whitelist, usar apenas quando o runtime tiver IP fixo confirmado.
8. Salvar `GATEIO_API_KEY` e `GATEIO_API_SECRET`; aliases genéricos `CEX_*` também são aceitos.
9. Declarar `venues.cex.<venue>.sandbox: true` no `settings.json` somente se a conta/API estiver em ambiente sandbox compatível.
10. Validar com `venues`, `cex-accounts`, `symbols` e dry-run antes de live.

**Variáveis Gate.io:**

- `CEX_ID=gateio`
- `CEX_MARKET_TYPE=trade|spot`
- `GATEIO_API_KEY` ou `CEX_API_KEY`
- `GATEIO_API_SECRET` ou `CEX_API_SECRET`
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

#### 4H. Variáveis da Hyperliquid e outras DEXs via adapter

> Para Hyperliquid, a skill usa adapter builtin via CCXT. Para outra DEX fora da Nado/Hyperliquid, aí sim é necessário adapter Python validado.

**Passo a passo Hyperliquid builtin para mainnet/operação real:**

**Links oficiais para análise:**

- App principal: `https://app.hyperliquid.xyz/trade`
- Onboarding Hyperliquid: `https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/how-to-start-trading`
- API Hyperliquid: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api`
- API wallets e nonces: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets`
- CCXT Hyperliquid: `https://docs.ccxt.com/#/exchanges/hyperliquid`
- Testnet/faucet, somente se o usuário decidir simular fora do fluxo real: `https://app.hyperliquid-testnet.xyz/drip`

**Referência CCXT de market type:** a skill usa o adapter CCXT da Hyperliquid. Nesse contexto, `DEX_MARKET_TYPE=trade` ou `HYPERLIQUID_MARKET_TYPE=trade` é o valor amigável para o usuário. A skill normaliza internamente para `swap`, que é o market type técnico do CCXT para perpetual swaps/perps, ou seja, o mercado de trade long/short com collateral USDC. Se estiver depurando CCXT diretamente, `swap` também continua aceito. Nado não usa esse env; DEX custom só usa se o adapter implementar.

1. **Fixar ambiente mainnet.**
   - Definir `DEX_ID=hyperliquid`.
   - Deixar `venues.dex.hyperliquid.sandbox: false` no `settings.json` (esse ja e o default da venue). Nao definir `HYPERLIQUID_NETWORK` nem `HYPERLIQUID_SANDBOX`: elas vencem o arquivo, e o adapter deriva a rede do sandbox -- declarar `testnet` com sandbox `false` faz operar na mainnet.
   - Definir `DEX_MARKET_TYPE=trade` como fallback DEX amigável ou `HYPERLIQUID_MARKET_TYPE=trade` como alias específico para trade long/short; a skill converte para `swap` antes do CCXT. Manter `HYPERLIQUID_SYMBOL_QUOTE=USDT` para compatibilidade de símbolo comum; o adapter converte internamente para mercados USDC da Hyperliquid.
2. **Criar ou conectar wallet.**
   - Acessar `https://app.hyperliquid.xyz/trade`.
   - Conectar uma wallet EVM ou login suportado pela Hyperliquid.
   - Acionar **Enable Trading** no app e assinar a transação gas-less quando o app solicitar.
3. **Preparar collateral real.**
   - Para perpetuals, a Hyperliquid usa USDC como collateral.
   - Para depósito via USDC, a documentação oficial orienta ter USDC e ETH para gas na rede Arbitrum, depois depositar pelo app da Hyperliquid.
   - Confirmar que o valor depositado é compatível com o risco definido para a estratégia antes de qualquer live.
4. **Criar API wallet/agent wallet dedicada.**
   - Criar uma API wallet/agent wallet exclusiva para esta skill.
   - A master account deve aprovar essa API wallet para assinar em nome da conta, subconta ou vault.
   - Usar uma API wallet separada por bot, processo, subconta ou vault para reduzir colisão de nonce.
5. **Salvar os segredos somente no Secret Manager/OpenClaw.**
   - `HYPERLIQUID_WALLET_ADDRESS`: endereço real da conta, subconta ou master/vault que será consultado; não usar o endereço da agent wallet aqui.
   - `HYPERLIQUID_PRIVATE_KEY`: private key da API wallet/agent wallet; aliases aceitos: `HYPERLIQUID_API_PRIVATE_KEY` ou `HYPERLIQUID_AGENT_PRIVATE_KEY`.
   - `HYPERLIQUID_VAULT_ADDRESS`: opcional, somente se o usuário escolher operar por vault.
   - Nunca colar private key, seed phrase, API secret ou token no chat, Git ou arquivo de config não sensível.
6. **Salvar config não sensível.**
   - `DEX_ID=hyperliquid`
   - `DEX_MARKET_TYPE=trade`
   - sandbox/rede: `venues.dex.hyperliquid.sandbox` no `settings.json`
   - `HYPERLIQUID_MARKET_TYPE=trade`
   - `HYPERLIQUID_SYMBOL_QUOTE=USDT`
   - `HYPERLIQUID_OPTIONS_JSON={...}` apenas com parâmetros sem segredo
7. **Validar leitura pública e integração local.**
   - Rodar `venues`, `symbols` e `setup-check --json`.
   - Se `symbols` listar mercados comuns Hyperliquid/Kraken, a camada pública está funcionando.
8. **Validar credenciais antes de qualquer ordem.**
   - Rodar `setup-check --json`, `doctor` e dry-run com símbolo único.
   - Confirmar que a conta, vault opcional, saldo, posições e símbolos batem com o esperado.
   - Se a consulta de conta voltar vazia, revisar se `HYPERLIQUID_WALLET_ADDRESS` recebeu o endereço real da conta, não o endereço da API wallet/agent.
9. **Liberar live apenas com confirmação explícita.**
   - Exigir símbolo/par, lado ou estratégia, tamanho máximo por ordem, limite de perda, margem/leverage e stop/target ou stop desligado explicitamente.
   - Exigir `AUTORIZAR_TRADE_REAL=sim` ou confirmação equivalente antes de qualquer execução real.
   - Manter saque/withdraw fora do escopo da chave operacional.

**Comandos de validação local antes do live:**

```bash
cd <CAMINHO_DO_REPOSITORIO>
python3 workspace/run.py setup-check --json
python3 workspace/run.py venues
python3 workspace/run.py symbols
python3 workspace/run.py rodar-setups-live --dry-run --max-iter 1
```

**Variáveis Hyperliquid:**

- `DEX_ID=hyperliquid`
- `HYPERLIQUID_WALLET_ADDRESS` com endereço real da conta/vault, não o endereço da agent wallet
- `HYPERLIQUID_PRIVATE_KEY` ou `HYPERLIQUID_API_PRIVATE_KEY`/`HYPERLIQUID_AGENT_PRIVATE_KEY`
- `HYPERLIQUID_VAULT_ADDRESS` opcional
- sandbox/rede: `venues.dex.hyperliquid.sandbox` no `settings.json`
- `DEX_MARKET_TYPE=trade` como fallback DEX amigável; para Hyperliquid a skill normaliza para CCXT `swap` em perpetual swaps/perps
- `HYPERLIQUID_MARKET_TYPE=trade` como alias específico e prioritário da Hyperliquid
- `HYPERLIQUID_SYMBOL_QUOTE=USDT`
- `HYPERLIQUID_OPTIONS_JSON={...}` sem segredos

**Outras DEXs custom:**

- `DEX_ID=dydx|uniswap|custom`
- `DEX_ADAPTER_MODULE=pacote.modulo:Classe`
- `DEX_CONFIG_JSON={...}` sem segredos
- `DEX_NETWORK` (mainnet/testnet/devnet conforme o adapter; com `DEX_ID=hyperliquid` ela decide sandbox e vence o `settings.json`)
- `DEX_MARKET_TYPE=trade` somente se o adapter customizado ler esse parâmetro; Nado ignora
- secrets específicos do adapter no OpenClaw, com nomes definidos pelo adapter.

#### 4I. Outras CEXs via CCXT

> A skill pode usar outras corretoras suportadas pelo CCXT, desde que a exchange implemente os recursos necessários para o modo escolhido. Qual `exchange_id` você quer usar?

**Passo a passo CEX genérica:**

1. Confirmar o `exchange_id` exato do CCXT, por exemplo `kucoin`, `mexc`, `bitget`, `gateio`, `coinbase`, `deribit` ou outro.
2. Definir `CEX_ID=<exchange_id>`.
3. Definir `CEX_MARKET_TYPE=trade|future|spot` conforme produto que será operado.
4. Criar API key dedicada na corretora, preferencialmente em subconta/conta isolada quando a corretora oferecer esse recurso, com leitura e trade apenas quando for live; manter saque/withdraw desabilitado.
5. Salvar `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` quando exigido.
6. Se houver env específica já suportada pela skill, pode usar `<PREFIX>_API_KEY`, `<PREFIX>_API_SECRET`, `<PREFIX>_API_PASSWORD`.
7. Rodar `python3 workspace/run.py venues` para confirmar adapter/credenciais.
8. Rodar `python3 workspace/run.py cex-accounts` quando a corretora oferecer leitura de saldo/conta via CCXT.
9. Rodar `symbols` para validar mapeamento de mercados.
10. Rodar dry-run; se faltar posição, leverage, margin mode ou trigger order no CCXT para aquela exchange, registrar limitação e não seguir para live sem alternativa operacional segura.

**Variáveis CEX genérica:**

- `CEX_ID=<exchange_id>`
- `CEX_MARKET_TYPE=trade|future|spot`
- `CEX_API_KEY`
- `CEX_API_SECRET`
- `CEX_API_PASSWORD` quando exigido
- sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)
- `CEX_OPTIONS_JSON={...}` sem segredos

#### 5. Onde salvar no OpenClaw

> Salve as variáveis no secret/env seguro do OpenClaw. Se estiver usando o painel, vá em **secret manager > Chaves de Serviço**. Depois disso, eu rodo `venues`, `setup-check` e `doctor` sem exibir nenhum segredo. ✅ Você salvou as envs por lá?

**Processo OpenClaw para salvar envs — onde clicar:**

1. Abrir `OpenClaw` no navegador.
2. Fazer login na conta do OpenClaw.
3. No dashboard, entrar em **Meu Assistente**.
4. Abrir a aba **Chaves**.
5. Entrar em **Chaves de Serviço**.
6. Clicar em **Adicionar chave**, **Nova chave** ou botão equivalente.
7. No campo de nome, colocar exatamente o nome da variável esperada pela skill, por exemplo `KRAKEN_API_KEY_`.
8. No campo de valor do secret manager, preencher a secret correspondente diretamente no site — nunca no chat.
9. Salvar.
10. Repetir uma entrada separada para cada variável necessária.
11. Conferir apenas os nomes salvos; nunca ler/enviar os valores no chat.
12. Aguardar o ambiente reiniciar/sincronizar se a plataforma fizer isso automaticamente.
13. Voltar ao chat e pedir para rodar `venues`, `setup-check` e `doctor`.

**Exemplo de entradas separadas no OpenClaw:**

- Nome: `NADO_OWNER_PRIVATE_KEY` / Valor: private key da wallet owner.
- Nome: `NADO_LINKED_SIGNER_PRIVATE_KEY` / Valor: private key do linked signer, quando existir.
- Nome: `NADO_SUBACCOUNT_NAME` / Valor: `default_1` ou nome exibido na Nado.
- Nome: `NADO_NETWORK` / Valor: `mainnet` ou `testnet`.
- Nome: `KRAKEN_API_KEY_` / Valor: API Key pública da Kraken.
- Nome: `KRAKEN_API_SECRET` / Valor: API Secret da Kraken.
- Nome: `BINANCE_API_KEY` / Valor: API Key pública da Binance.
- Nome: `BINANCE_API_SECRET` / Valor: API Secret da Binance.
- Nome: `BYBIT_API_KEY` / Valor: API Key pública da Bybit.
- Nome: `BYBIT_API_SECRET` / Valor: API Secret da Bybit.
- Nome: `OKX_API_KEY` / Valor: API Key pública da OKX.
- Nome: `OKX_API_SECRET` / Valor: API Secret da OKX.
- Nome: `OKX_API_PASSWORD` / Valor: passphrase/password da API OKX.
- Nome: `KUCOIN_API_KEY` / Valor: API Key pública da KuCoin.
- Nome: `KUCOIN_API_SECRET` / Valor: API Secret da KuCoin.
- Nome: `KUCOIN_API_PASSWORD` / Valor: passphrase/password da API KuCoin.
- Nome: `MEXC_API_KEY` / Valor: API Key pública da MEXC.
- Nome: `MEXC_API_SECRET` / Valor: API Secret da MEXC.
- Nome: `BITGET_API_KEY` / Valor: API Key pública da Bitget.
- Nome: `BITGET_API_SECRET` / Valor: API Secret da Bitget.
- Nome: `BITGET_API_PASSWORD` / Valor: passphrase/password da API Bitget.
- Nome: `GATEIO_API_KEY` / Valor: API Key pública da Gate.io.
- Nome: `GATEIO_API_SECRET` / Valor: API Secret da Gate.io.
- Nome: `CEX_API_KEY` / Valor: API Key pública da CEX genérica ativa.
- Nome: `CEX_API_SECRET` / Valor: API Secret da CEX genérica ativa.
- Nome: `CEX_API_PASSWORD` / Valor: password/passphrase quando a CEX exigir.

Não salve `KRAKEN_VENUE` e `KRAKEN_SANDBOX` como segredo/chave de serviço quando puder usar config local. Eles devem ir preferencialmente em:

```env
# ~/.openclaw/workspace/trade-automatizado-openclaw.config.env
KRAKEN_VENUE=futures
# sandbox: settings.json -> venues.cex.kraken.sandbox (KRAKEN_SANDBOX vence o arquivo)
```

Também trate `DEX_ID`, `CEX_ID`, `CEX_MARKET_TYPE`, `CEX_SANDBOX`, `DEX_NETWORK`, `NADO_NETWORK` e `NADO_SUBACCOUNT_NAME` como configuração não sensível quando o ambiente permitir separar config de segredo.

**Nomes mínimos por modo:**

- Nado-only / `dex_only`:
  - `DEX_ID=nado`
  - `NADO_OWNER_PRIVATE_KEY`
  - `NADO_SUBACCOUNT_NAME`
  - `NADO_NETWORK`
  - opcional: `NADO_LINKED_SIGNER_PRIVATE_KEY`

- DEX custom / `dex_only`:
  - `DEX_ID=<id>`
  - `DEX_ADAPTER_MODULE=pacote.modulo:Classe`
  - `DEX_NETWORK`, quando aplicável
  - secrets específicos do adapter no OpenClaw

- Kraken-only / `cex_only`:
  - `CEX_ID=kraken`
  - `KRAKEN_API_KEY_` ou `KRAKEN_API_KEY`
  - `KRAKEN_API_SECRET`
  - arquivo de configuração não sensível carregado com `KRAKEN_VENUE`/`CEX_MARKET_TYPE` e `KRAKEN_SANDBOX`/`CEX_SANDBOX`, quando aplicável

- Binance / `cex_only`:
  - `CEX_ID=binance`
  - `CEX_MARKET_TYPE=trade|future|spot`
  - `BINANCE_API_KEY` e `BINANCE_API_SECRET`; ou `CEX_API_KEY` e `CEX_API_SECRET`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- Bybit / `cex_only`:
  - `CEX_ID=bybit`
  - `CEX_MARKET_TYPE=trade|spot`
  - `BYBIT_API_KEY` e `BYBIT_API_SECRET`; ou `CEX_API_KEY` e `CEX_API_SECRET`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- OKX / `cex_only`:
  - `CEX_ID=okx`
  - `CEX_MARKET_TYPE=trade|future|spot`
  - `OKX_API_KEY`, `OKX_API_SECRET` e `OKX_API_PASSWORD`; ou `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- KuCoin / `cex_only`:
  - `CEX_ID=kucoin`
  - `CEX_MARKET_TYPE=trade|future|spot`
  - `KUCOIN_API_KEY`, `KUCOIN_API_SECRET` e `KUCOIN_API_PASSWORD`; ou `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- MEXC / `cex_only`:
  - `CEX_ID=mexc`
  - `CEX_MARKET_TYPE=trade|spot`
  - `MEXC_API_KEY` e `MEXC_API_SECRET`; ou `CEX_API_KEY` e `CEX_API_SECRET`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- Bitget / `cex_only`:
  - `CEX_ID=bitget`
  - `CEX_MARKET_TYPE=trade|spot`
  - `BITGET_API_KEY`, `BITGET_API_SECRET` e `BITGET_API_PASSWORD`; ou `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- Gate.io / `cex_only`:
  - `CEX_ID=gateio`
  - `CEX_MARKET_TYPE=trade|spot`
  - `GATEIO_API_KEY` e `GATEIO_API_SECRET`; ou `CEX_API_KEY` e `CEX_API_SECRET`
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- Outra CEX via CCXT / `cex_only`:
  - `CEX_ID=<exchange_id>`
  - `CEX_MARKET_TYPE=trade|future|spot`
  - `CEX_API_KEY` e `CEX_API_SECRET`
  - `CEX_API_PASSWORD` quando exigido pela corretora
  - sandbox: `venues.cex.<venue>.sandbox` no `settings.json` (a env `CEX_SANDBOX` ainda e lida e vence o arquivo)

- Hedge / `hedged`:
  - todas as variáveis da DEX escolhida;
  - todas as variáveis da CEX escolhida;
  - sizing explícito antes de live.

**Depois de salvar:**

- Não exibir valores.
- Validar apenas presença/formato.
- Se algo falhar, responder com o nome da env esperada e o próximo passo seguro.

#### 6. Diagnóstico inicial

> Vou rodar `venues`, `setup-check` e `doctor` em modo seguro para validar venues, paths, dependências e presença das envs, sem abrir trade. 🧪 Posso rodar o diagnóstico agora?

**Passo a passo do diagnóstico:**

1. Rodar `python3 workspace/run.py venues`.
2. Rodar `python3 workspace/run.py setup-check`.
3. Conferir se `env_file_loaded=false` em runtime OpenClaw quando as envs vêm de service keys/secret manager.
4. Conferir se os paths estão em `~/.openclaw/state/trade-automatizado-openclaw/`.
5. Conferir em `venues` se `DEX_ID`, `CEX_ID`, adapters e credenciais esperadas batem com a escolha do wizard.
6. Conferir se `KRAKEN_API_KEY_` aparece como configurada quando a Kraken estiver em uso, ou se `CEX_API_KEY`/env específica aparece para CEX genérica.
7. Conferir se `NADO_OWNER_PRIVATE_KEY`/`NADO_SUBACCOUNT_NAME` aparecem como presentes quando a Nado estiver em uso.
8. Para DEX custom, conferir se `DEX_ADAPTER_MODULE` está configurado e validado.
9. Rodar `python3 workspace/run.py doctor`.
10. Se faltar algo, responder só com o nome da variável ausente e o próximo passo; nunca pedir o valor no chat.
11. Se `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver presente mas inválida, orientar a corrigir/remover no secret/env antes do live.
12. Se CEX estiver em uso, confirmar que a API key é dedicada à estratégia e sem permissão de saque/withdraw.
13. Só avançar para dry-run quando `venues`, `setup-check` e `doctor` estiverem OK ou quando o usuário aceitar explicitamente a limitação apontada.

#### 7. Escopo de ativos

> Quais símbolos analisar? Opções: `all`, um ativo como `SUI/USDT`, ou lista CSV como `SUI/USDT,HYPE/USDT`.

**Passo a passo para escolher ativos:**

1. Perguntar se o usuário quer analisar um ativo, uma lista curta ou todos.
2. Para primeira execução, recomendar um ativo único ou lista curta.
3. Se o usuário disser `dex_only`, preferir símbolos disponíveis na DEX escolhida.
4. Se o usuário disser `hedged`, usar símbolos que existam nas duas venues escolhidas.
5. Se o usuário disser `all`, avisar que a execução pode demorar mais e gerar mais logs/sinais.
6. Para símbolos CSV, normalizar em maiúsculas e manter formato `BASE/USDT`.
7. Se houver ativo suspeito, sem perp ativo ou com spread/preço inválido, orientar usar blacklist temporária em `DEX_DISABLED_PERP_SYMBOLS`/`DEX_EXCLUDE_SYMBOLS`; aliases Nado legados ainda são aceitos para Nado.
8. Antes de live, validar o universo com `symbols`, `asset-scan` ou dry-run.

#### 8. Setups

> Quais setups quer rodar? Opções: `all`, `grid-strict`, `institutional-strict`, `bollinger-mean-reversion`, `low-stoch-storm` ou `divergence-and-volume-4h`.

**Passo a passo para escolher setups:**

1. Explicar que setups são filtros de entrada; eles não substituem sizing, stop e confirmação live.
2. Para primeira execução, recomendar `institutional-strict` ou uma lista curta.
3. Se o usuário quiser amplo rastreamento, permitir `all`, mas sugerir `--max-open-setups 1` no primeiro live.
4. Para `dex_only`/Nado-only, ignorar setups exclusivamente hedgeados como `delta-neutral` e `funding-arb`.
5. Explicar que `low-stoch-storm` é setup 4h de pullback/tendência, mais lento.
6. Explicar que `divergence-and-volume-4h` é reversão 4h por divergência RSI + volume + Fibonacci + candle; respeita whitelist strict por padrão.
7. Se `divergence-and-volume-4h` não analisar muitos ativos, explicar `DIVERGENCE_AND_VOLUME_WHITELIST_MODE`/`DIVERGENCE_AND_VOLUME_ALLOWED_SYMBOLS` antes de alterar.
8. Rodar dry-run antes de qualquer live para ver quais setups realmente geram plano.

#### 9. Dry-run obrigatório antes do live

> Recomendo rodar primeiro em `dry-run`, sem trade real. 🧯 Posso executar o dry-run com os parâmetros escolhidos?

**Passo a passo do dry-run:**

1. Montar comando com modo, símbolo, setup, margin mode, sizing e stop.
2. Incluir sempre `--dry-run`.
3. Para somente DEX, usar `--modo somente-dex`.
4. Para somente CEX, usar `--modo somente-cex`.
5. Para delta neutro/hedge, usar `--modo delta-neutro`.
6. Usar sizing explícito mesmo em dry-run para validar plano realista.
7. Rodar o comando.
8. Ler os logs de `setup-live prontidao`, bloqueios e setups gerenciados.
9. Se o comando ficar longo com `all`, repetir com um símbolo único para isolar comportamento.
10. Só sugerir live depois de dry-run sem bloqueios críticos.

**Exemplo Nado-only dry-run:**

```bash
python3 workspace/run.py rodar-setups-live \
  --dry-run \
  --setup institutional-strict \
  --symbol SUI/USDT \
  --modo somente-dex \
  --modo-margem cross \
  --slots-margem-conta 8 \
  --risk-profile moderado \
  --stop-loss-preset 20
```

#### 10. Sizing obrigatório para live

> Qual tamanho você quer para live? Escolha um: `--valor-nominal 20`, `--margem-usd 5`, `--margem-dex-usd 5 --margem-cex-usd 5` ou `--slots-margem-conta 8`.

**Passo a passo para definir sizing:**

1. Explicar que live é bloqueado sem sizing explícito.
2. Perguntar qual modelo o usuário prefere.
3. Se quiser valor nominal fixo, usar `--valor-nominal`.
4. Se quiser controlar margem, usar `--margem-usd`.
5. Se DEX e CEX tiverem tamanhos diferentes, usar `--dex-margin-usd` e `--cex-margin-usd`; aliases legados `--nado-margin-usd` e `--kraken-margin-usd` continuam aceitos.
6. Se quiser dividir saldo operacional em partes, usar `--account-margin-slots`.
7. Explicar que `--margem-usd` vira valor nominal aproximado de `margem * alavancagem`.
8. Para conta pequena, recomendar `--account-margin-slots 8` em vez de 16 para evitar ordem abaixo do mínimo operacional.
9. Verificar se o notional resultante fica acima do mínimo real da DEX/CEX escolhida.
10. Confirmar sizing em texto antes de live.

**Modelos aceitos:**

- `--valor-nominal 20`: tamanho nominal fixo de aproximadamente 20 USD.
- `--margem-usd 5`: margem de 5 USD multiplicada pela alavancagem do perfil.
- `--dex-margin-usd 5 --cex-margin-usd 5`: margens separadas por venue; aliases Nado/Kraken continuam aceitos.
- `--account-margin-slots 8`: divide o orçamento da conta em 8 slots.

#### 11. Margin mode, perfil de risco e alavancagem

> Qual margin mode e perfil de risco? Ex.: `cross` + `moderado`, `isolated` + `conservador`, ou outro combo. ⚖️ O perfil define a alavancagem padrão: `conservador` = 1x, `moderado` = 5x, `degen` = 10x.

**Passo a passo para risco/alavancagem:**

1. Explicar diferença entre `cross` e `isolated`.
2. `cross`: usa margem compartilhada da conta; pode ser mais flexível, mas exige atenção ao risco global.
3. `isolated`: isola margem por posição; reduz contágio, mas pode exigir margem/notional mínimo por posição.
4. Explicar os perfis antes da escolha:
   - `conservador`: usa **1x**; menor risco, menor exposição, indicado para primeiro teste ou conta pequena.
   - `moderado`: usa **5x**; risco intermediário, padrão recomendado quando o usuário entende margem e stop.
   - `degen`: usa **10x**; risco alto, maior chance de liquidação/stop rápido, só usar com confirmação explícita.
5. Se o usuário escolher `--margem-usd`, calcular e explicar o valor nominal aproximado.
6. Exemplo: `--margem-usd 5` com `moderado` = cerca de `$25` de valor nominal.
7. Se for primeiro live, recomendar `cross + moderado` ou `isolated + conservador`, conforme tamanho da conta.
8. Para `degen`, exigir confirmação explícita de risco alto.

#### 12. Stop e limite de operações

> Qual stop e limite de operações? Recomendo `--stop-loss-preset 20` e `--max-open-setups 1` no primeiro live.

**Passo a passo para stop/limite:**

1. Explicar que stop é obrigatório como regra operacional de risco.
2. Oferecer presets: `10`, `20`, `30`, `conservador`, `moderado`, `degen`.
3. Se o usuário quiser percentual manual, usar `--stop-loss-pct`.
4. Para primeiro live, recomendar `--stop-loss-preset 20`.
5. Explicar que TP vem do setup, mas stop pode ser definido por execução.
6. Recomendar `--max-open-setups 1` no primeiro live para evitar múltiplas entradas simultâneas.
7. Se o usuário quiser mais de uma operação, confirmar número máximo e justificar risco.
8. Validar no dry-run se o stop/TP aparece no plano.
9. Se o usuario quiser stop seguindo alvos, explicar `--modo-stop-alvo desligado|entrada-no-tp1|escada`: `desligado` mantem stop fixo; `entrada-no-tp1` move o stop para entrada apos TP1; `escada` move TP1->entrada, TP2->TP1, TP3->TP2. Default seguro: `desligado`.

#### 13. Take profit, fallback Nado e reciclagem de slots

> Se a Nado não aceitar TP nativo parcial por mínimo, quer manter a política segura padrão? Recomendo `SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`: fecha 100% no primeiro alvo gerenciado e libera o slot. 🎯

**Passo a passo para TP/fallback:**

1. Explicar que a Nado pode rejeitar/invalidar triggers nativos abaixo do mínimo operacional.
2. Explicar que, nesses casos, a skill não deve deixar sobras pequenas dependentes de vários TPs gerenciados.
3. Confirmar a política padrão `first_target_full`: se TP parcial nativo Nado ficar abaixo do mínimo, o loop gerenciado fecha 100% da posição no primeiro alvo.
4. Explicar que isso reduz risco de posição órfã ou sobra sem TP nativo anexado.
5. Explicar que, se o preço atravessar múltiplos TPs entre duas iterações, o fechamento gerenciado deve avançar todos os alvos cruzados na mesma iteração, somando as quantidades correspondentes.
6. Explicar que o `setup-live` registra `PNL potencial max` por entrada com o melhor preço favorável observado desde a abertura, útil para auditar lucro potencial vs lucro capturado.
7. Explicar que, ao fechar 100%, o estado sai do `setup_live_state.json`.
8. Explicar que, com `--max-open-setups`, esse fechamento libera slot imediatamente.
9. Explicar que o mesmo ciclo live do `setup-live` já pode avaliar nova entrada se houver sinal válido e guardrails OK.
10. Reforçar que isso só vale em execução live confirmada; em `--dry-run`, nada real é fechado ou reaberto.
11. Rodar/consultar `live-status` quando houver dúvida: posições `ORPHAN` são exposição real sem state e sem TP/SL gerenciado ativo.
12. Nunca fechar ou reanexar posição órfã automaticamente sem decisão explícita do usuário.

#### 14. Notificações e dashboard

> Quer aviso de entrada confirmada e dashboard? Opções: Telegram, Discord extra, ambos, nenhum; dashboard local ou publicação externa configurada.

**Passo a passo para notificações:**

1. Perguntar se quer notificação de entrada confirmada.
2. Se Telegram, pedir apenas o destino/canal quando já conhecido pelo ambiente; não alterar controle de acesso do OpenClaw pelo chat.
3. Se Discord extra, pedir `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` ou `--notify-entry-discord-channel-id`.
4. Se quiser mencionar servidor no Discord, explicar `SETUP_NOTIFY_DISCORD_MENTION=@everyone` e necessidade de permissão do agente.
5. Se não quiser notificações, usar `--no-notify-entry`.
6. Testar preferencialmente com dry-run/monitoradas antes de live.

**Passo a passo para dashboard:**

1. Rodar `python3 workspace/run.py live-status` para exposição real.
2. Rodar `python3 workspace/run.py setup-live-status` para operações monitoradas.
3. Rodar `python3 workspace/run.py dashboard` para gerar `index.html` e `dashboard-data.json`.
4. Se for publicar externamente, confirmar o comando de deploy escolhido pelo usuário.
5. Publicar uma vez com `dashboard-publisher --once --deploy-command "<comando-deploy>"`.
6. Validar o `dashboard-data.json` público após publicação.
7. Conferir `summary.live_exposure_count`, `summary.open_trades`, `updated_at` e `live_exposures.error`.
8. Se exposição real e monitoradas divergirem, explicar a diferença antes de mexer no live.

#### 15. Confirmação final live

> Confirma live/mainnet com estes parâmetros? Só executo ordem real com confirmação explícita, tamanho definido e `AUTORIZAR_TRADE_REAL=sim` apenas na execução aprovada.

**Passo a passo antes do live:**

1. Repetir o resumo dos parâmetros escolhidos:
   - modo de execução;
   - símbolo(s);
   - setup(s);
   - sizing;
   - margin mode;
   - perfil/alavancagem;
   - stop;
   - limite de operações;
   - notificações;
   - dashboard, se aplicável.
2. Confirmar que `venues`, `setup-check` e `doctor` passaram.
3. Confirmar que dry-run passou sem bloqueios críticos.
4. Confirmar que não há linked signer inválido.
5. Confirmar que a API key da CEX escolhida é dedicada à estratégia e não possui permissão de saque/withdraw quando for operar live.
6. Confirmar que o tamanho explícito está no comando.
7. Confirmar que `--max-open-setups` está definido quando recomendado.
8. Pedir confirmação explícita do usuário para live/mainnet.
9. Só na execução aprovada, setar `AUTORIZAR_TRADE_REAL=sim` no ambiente do processo.
10. Nunca persistir `AUTORIZAR_TRADE_REAL=sim` como env fixa. `TRADE_AUTOMATIZADO_CONFIRM_LIVE=true` ainda é aceito como alias técnico e `DELTA_NEUTRAL_CONFIRM_LIVE=true` apenas como alias legado.
11. Após execução, rodar `setup-live-status`/`live-status` para validar estado.

**Exemplo live Nado-only após confirmação:**

```bash
AUTORIZAR_TRADE_REAL=sim python3 workspace/run.py rodar-setups-live \
  --setup institutional-strict \
  --symbol SUI/USDT \
  --modo somente-dex \
  --modo-margem cross \
  --slots-margem-conta 8 \
  --risk-profile moderado \
  --stop-loss-preset 20 \
  --max-open-setups 1
```


## Venues customizadas

Use `DEX_ID=nado` e `CEX_ID=kraken` quando o usuário não escolher venues. Para CEXs como Binance, Bybit, OKX, KuCoin, MEXC, Bitget ou Gate.io, defina `CEX_ID=<exchange_id CCXT>`, `CEX_MARKET_TYPE=trade|future|spot`, credenciais específicas da venue ou `CEX_API_KEY`, `CEX_API_SECRET` e `CEX_API_PASSWORD` quando exigido.

Para Hyperliquid, defina `DEX_ID=hyperliquid` e use o adapter builtin. Para outras DEXs fora da Nado/Hyperliquid, defina `DEX_ID=<id>` e `DEX_ADAPTER_MODULE=pacote.modulo:Classe`. O adapter precisa expor a interface de execução documentada no `SKILL.md`; sem adapter, a skill só pode orientar configuração e diagnóstico, não operar live nessa DEX.

Sempre valide com `python3 workspace/run.py venues`, `symbols` e dry-run antes de qualquer execução real.
