# Env E Credenciais

## Variaveis Nado

```env
NADO_OWNER_PRIVATE_KEY=0x...
NADO_PRIVATE_KEY=0x...
NADO_LINKED_SIGNER_PRIVATE_KEY=0x...
NADO_NETWORK=testnet
NADO_SUBACCOUNT_NAME=default_1
NADO_REQUIRE_LINKED_SIGNER=true
NADO_ALLOW_OWNER_FALLBACK=false
```

Notas:
- `NADO_PRIVATE_KEY` e alias legado
- o valor canonico agora e `NADO_OWNER_PRIVATE_KEY`
- `NADO_LINKED_SIGNER_PRIVATE_KEY` precisa ser o signer vinculado on-chain a `default_1`
- fallback para owner key exige `NADO_ALLOW_OWNER_FALLBACK=true` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`

## Variaveis Kraken

```env
KRAKEN_API_KEY=***
KRAKEN_API_SECRET=***
KRAKEN_VENUE=futures
# sandbox: settings.json -> venues.cex.kraken.sandbox
# (KRAKEN_SANDBOX ainda e lida, mas vence o arquivo e o deixa sem efeito)
KRAKEN_ACCOUNT=flex
KRAKEN_ACCOUNT_SYMBOL=
KRAKEN_REQUIRE_SUBACCOUNT=false
KRAKEN_API_IS_SUBACCOUNT=false
KRAKEN_ALLOW_MAIN_ACCOUNT=false
PROTECTIVE_STOP_LOSS_PCT=0.03
PROTECTIVE_STOP_TRIGGER_SLIPPAGE_PCT=0.01
MARGIN_USD=
NADO_MARGIN_USD=
KRAKEN_MARGIN_USD=
```

Notas:
- a Kraken nao usa roteamento de subconta por ordem neste projeto
- subconta/conta isolada e recomendada quando a corretora/DEX oferecer esse recurso, mas nao obrigatoria por padrao; a decisao final e do usuario e nao deve ser hard-coded
- se o usuario nao usar esse modelo, mantenha no minimo API key dedicada sem saque e valide com `doctor`/dry-run
- `KRAKEN_ACCOUNT` continua sendo contexto de leitura/organizacao
- para API key real da Kraken Futures, declare `venues.cex.kraken.sandbox: false` no `settings.json`
- `PROTECTIVE_STOP_LOSS_PCT` adiciona stop loss reduce-only nas novas pernas abertas pelo bot
- `PROTECTIVE_STOP_TRIGGER_SLIPPAGE_PCT` controla a folga de execucao do trigger, especialmente na Nado
- `MARGIN_USD` calcula notional operacional como margem * leverage
- `KRAKEN_REQUIRE_SUBACCOUNT=true` so deve ser usado se o usuario decidir ativar a validacao estrita de subconta; nesse caso, `KRAKEN_API_IS_SUBACCOUNT=true` apenas quando a API key realmente vier da subconta
- fallback para main account em modo estrito exige `KRAKEN_ALLOW_MAIN_ACCOUNT=true` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`

## Runtime env efemero

Quando nao quiser salvar env no OpenClaw, passe um arquivo temporario no wrapper:

```powershell
python3 workspace/run.py --runtime-env /tmp/delta-runtime.env setup-check
python3 workspace/run.py setup-check --runtime-env /tmp/delta-runtime.env
```

O arquivo pode conter private keys e API secrets, mas nao deve ser commitado.

## Sizing e protecao

Regras atuais:
- `--notional` define o tamanho nominal.
- `--margin-usd` define margem e calcula `notional = margem * leverage`.
- `--nado-margin-usd` e `--kraken-margin-usd` permitem overrides por DEX/CEX.
- o minimo de entrada e validado pelo minimo real do ativo/venue.
- take profit vem do setup.
- stop em `setup-live` aceita `--stop-loss-pct` ou presets `10`, `20`, `30`.

Exemplo:

```powershell
python3 workspace/run.py setup-live --dry-run --setup institutional --symbol all --execution-mode dex_only --margin-mode cross --margin-usd 20 --hybrid-profile moderado --stop-loss-preset 20
```

## Como configurar a subconta real da Kraken (opcional recomendado)

Subconta nao e obrigatoria por padrao. O recomendado e operar em subconta ou conta isolada quando a corretora/DEX oferecer esse recurso, mas o usuario decide e a skill nao deve hard-code essa exigencia.


Fluxo oficial resumido:

1. Criar uma nova conta Kraken para funcionar como subconta.
2. Verificar essa nova conta.
3. Habilitar Derivatives nessa conta.
4. Abrir ticket de suporte a partir da conta master pedindo o vinculo com a conta da subconta.
5. Confirmar o email enviado para a subconta.
6. Transferir saldo para a subconta em `futures.kraken.com/trade/subaccounts`.
7. Fazer login diretamente na subconta.
8. Gerar a API key em `Settings` > `API` > `Create Key`.
9. Usar `General API: Full Access` e `Withdrawal API: No Access`.
10. Salvar as chaves no `.env` com `KRAKEN_API_IS_SUBACCOUNT=true` e declarar `venues.cex.kraken.sandbox: false` no `settings.json`; use `KRAKEN_REQUIRE_SUBACCOUNT=true` somente se o usuario decidir ativar a validacao estrita de subconta.

Pontos importantes da Kraken:
- API keys sao geradas e controladas separadamente por subconta
- sign-ins sao separados por subconta
- positions sao margined no nivel da subconta
- withdrawals da subconta sao bloqueados

Links oficiais:
- [Understanding Derivatives subaccounts](https://support.kraken.com/articles/360042809671-understanding-derivatives-subaccounts)
- [How to unlock Derivatives trading](https://support.kraken.com/articles/360022618012-how-to-unlock-derivatives-trading)
- [How to create an API key for Kraken Derivatives](https://support.kraken.com/articles/360022839451-how-to-create-an-api-key-for-kraken-derivatives)
- [Kraken Futures support form](https://support.kraken.com/forms/360000286871)
- [Kraken Futures subaccounts page](https://futures.kraken.com/trade/subaccounts)

## Alternativa mais simples: conta Kraken separada

Se a prioridade for so isolar o bot da conta principal, a forma mais simples e criar uma segunda conta Kraken separada e usar essa conta para o projeto.

Passos:

1. sair da conta Kraken principal
2. criar outra conta Kraken com outro email
3. verificar essa nova conta
4. habilitar Derivatives nela pelo Kraken Pro
5. gerar a API key nessa conta separada
6. usar a API no projeto com `venues.cex.kraken.sandbox: false` no `settings.json`

Trade-offs:
- continua isolando os trades da principal
- nao depende do vinculo formal de subconta
- nao compartilha saldo, volume, fee tier, verificacao nem transferencia interna

Fonte oficial:
- [Account Management FAQ](https://support.kraken.com/hc/articles/account-management-faq)

## Diagnostico

```powershell
python3 workspace/run.py kraken-accounts
```

Esperado:
- em modo padrao, `trading=safe` sem exigir subconta
- em modo estrito escolhido pelo usuario, motivo dizendo que a API key dedicada foi validada
- sem indicacao de conta master quando o usuario optar por subconta
