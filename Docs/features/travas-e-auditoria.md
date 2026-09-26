# Travas na exchange e rastro de auditoria

> Última atualização: 25 de setembro de 2026
> Versão: 1.11.0 (não publicada)

## Visão Geral

As travas da skill são instrução ao agente, não fechadura: quem monta o comando
é o próprio agente, e ele tem shell ([ADR 0007](../decisions/0007-autonomia-do-agente.md)).
Esta feature cuida das duas coisas que a skill consegue fazer de útil a partir
daí:

1. **Conferir as travas que valem e avisar.** O `doctor` pergunta à CEX se a
   API key pode sacar, e ao OpenClaw se ele pede aprovação antes de executar.
   É aviso: o operador fica ciente. Bloquear é escolha dele (ver *Bloqueio
   configurável*).
2. **Deixar rastro.** Cada execução real aprovada grava um registro de que o
   agente decidiu operar real, e por qual variável de confirmação.

## Key sem saque (`doctor`)

| Venue | Como verifica | Resultado |
|---|---|---|
| Binance | `GET /sapi/v1/account/apiRestrictions` → `enableWithdrawals` | verificado |
| Bybit | `GET /v5/user/query-api` → `permissions.Wallet` contém `Withdraw` | verificado |
| OKX | `GET /api/v5/account/config` → `perm` contém `withdraw` | verificado |
| Kraken, KuCoin, MEXC, Bitget, Gate.io e outras | a venue não expõe a permissão da própria key | "não verificado: confira no painel" |

- O check `cex_key_sem_saque` **avisa** quando a venue confirma que a key
  saca. "Não verificado" vem com `verificado: false` e o motivo no detalhe: a
  falta de verificação não prova que a key saca, mas o operador fica sabendo
  que ninguém conferiu.
- Resposta que não dá para ler, erro de rede ou de autenticação viram "não
  verificado", **nunca** "sem saque": dúvida não é segurança.
- É a única chamada de rede do `doctor`, e só roda com credencial de CEX
  configurada; timeout de 10 s. A mensagem de erro não é repassada (pode ecoar
  a requisição): só o tipo da exceção.

## Key sem saque na DEX (`dex_key_sem_saque`)

Sem rede: a pergunta é *qual* chave o operador configurou.

| DEX | Regra | Resultado |
|---|---|---|
| Hyperliquid | endereço derivado da chave (CCXT) = `HYPERLIQUID_WALLET_ADDRESS` → chave principal | pode sacar |
| Hyperliquid | endereço diferente → API wallet (agent) | sem saque ("API wallets [...] without having withdrawal permissions", app.hyperliquid.xyz/API) |
| Nado | só owner key (a skill assina com ela) | pode sacar |
| Nado | com linked signer, mas `NADO_ALLOW_OWNER_FALLBACK` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK` ligados | pode sacar: se o linked signer falhar, a owner key assina |
| Nado | com `NADO_LINKED_SIGNER_PRIVATE_KEY` e sem fallback | não verificado: a doc da Nado diz que o linked signer assina executes, e saque é um execute |
| DEX por adapter | — | não verificado |

Chave e conta da Hyperliquid seguem a precedência do adapter: env, depois
`DEX_CONFIG_JSON`. O endereço é comparado sem o prefixo `0x` nos dois lados.
Chave malformada vira "não verificado" sem repassar o valor. Sem chave
configurada, o check não aparece. Aviso por padrão, bloqueio com
`BLOQUEAR_SAQUE`, como na CEX.

## OpenClaw sem aprovação (`openclaw_aprovacao`)

O `doctor` roda `openclaw exec-policy show --json` e lê a política efetiva de
cada escopo (o pior decide):

| Política efetiva | Resultado |
|---|---|
| `security=full` (ou `mode=full`) | sem aprovação: real autônomo |
| `security=allowlist` com `ask=off` | sem aprovação para o que está na allowlist |
| `mode=auto` | revisor automático antes do operador |
| `allowlist` com `ask=on-miss`/`always`, ou `deny` | protegido |
| comando ausente, erro, JSON inválido | não verificado |

"Protegido" não vê a allowlist: o detalhe lembra de conferir que os comandos
de trade não estão nela.

## Saque automático (`saque_automatico`)

`AUTO_WITHDRAW_ENABLED=true` faz o `workspace/nado/auto_trade_nado.py` sacar
sozinho da Nado. O aviso segue a leitura do script: só `true` liga.

## Bloqueio configurável

Decisão do autor (25/09/2026, adendo do ADR 0007): saque e falta de aprovação
são aviso. Quem quiser bloqueio liga:

| Variável | Transforma em bloqueio |
|---|---|
| `BLOQUEAR_SAQUE=sim` | `cex_key_sem_saque`, `dex_key_sem_saque` e `saque_automatico` |
| `BLOQUEAR_SEM_APROVACAO=sim` | `openclaw_aprovacao` (sem aprovação ou revisor automático) |

Ligado, o check reprova o `doctor` (`blocking_checks` no relatório) e o
`run.py` recusa o comando de trade antes de executá-lo. Não verificado nunca
bloqueia: avisa no stderr e segue. Valor fora do vocabulário de booleano
reprova o `doctor` nomeando a variável. O agente pode desligar a variável:
é escolha do operador, não fechadura.

## Rastro de auditoria

Quando um comando de trade roda em modo real com uma das quatro variáveis de
confirmação (`AUTORIZAR_TRADE_REAL`, `CONFIRMAR_TRADE_REAL`,
`TRADE_AUTOMATIZADO_CONFIRM_LIVE`, `DELTA_NEUTRAL_CONFIRM_LIVE`), a guarda do
`cli.py` acrescenta uma linha JSON em `auditoria-trade-real.jsonl`, no
diretório de log (`DELTA_NEUTRAL_LOG_DIR`):

```json
{"ts": "2026-09-25T18:00:00-03:00", "comando": "abrir", "args": ["ETH/USDT", "--margem-usd", "20"], "variaveis": ["AUTORIZAR_TRADE_REAL"]}
```

- Simulação (`--simular`, `--dry-run`) e comando de leitura não geram registro.
- Um ponto só de registro: o `run.py` chama o `cli.py` como script, e ninguém
  chama `main()` por fora; a guarda do topo do `cli.py` vê toda execução real.
  **Condição para isso continuar valendo:** o watcher, o scanner e o dashboard
  importam `workspace.cli`, e a guarda roda nesse import com o `argv` do
  processo que importou. Hoje eles só usam funções de notificação e leitura, e
  nenhum aceita comando posicional. Um módulo que passe a executar ordem por
  dentro do `cli` escapa do registro.
- Falhar ao gravar avisa no stderr e segue: é rastro, não trava. Pelo mesmo
  motivo, o agente pode apagar o arquivo; o rastro que o agente não alcança é
  o histórico de ordens da exchange.

## Componentes

| Componente | Arquivo | Função |
|---|---|---|
| Permissão de saque | `workspace/venues/permissao_de_saque.py` | `interpretar` (puro) e `consultar` (CCXT) |
| Check do `doctor` | `workspace/run.py` (`_check_key_sem_saque`) | liga o veredicto ao relatório |
| Política do OpenClaw | `workspace/politica_openclaw.py` | `interpretar` (puro) e `consultar` (`exec-policy show --json`) |
| Bloqueio configurável | `workspace/run.py` (`_checks_bloqueados_pelo_operador`, `_motivos_de_bloqueio_do_operador`) | doctor e comando de trade |
| Rastro | `workspace/cli.py` (`_record_live_trade_confirmation`) | grava a linha de auditoria |

Testes: `test/test_permissao_de_saque.py`, `test/test_dex_key_sem_saque.py`, `test/test_politica_openclaw.py`,
`test/test_bloqueios_configuraveis.py` e `test/test_auditoria_trade_real.py`.
O `conftest` desliga a rede e o `openclaw` dessas consultas em toda a suíte.

## Changelog

| Data | Mudança |
|---|---|
| 25/09/2026 | Check `cex_key_sem_saque` no `doctor` (Binance, Bybit, OKX) e rastro de auditoria da confirmação real |
| 25/09/2026 | Saque vira aviso; `openclaw_aprovacao` e `saque_automatico`; bloqueio configurável (`BLOQUEAR_SAQUE`, `BLOQUEAR_SEM_APROVACAO`) |
| 25/09/2026 | `dex_key_sem_saque`: Hyperliquid (chave principal × API wallet) e Nado (owner key × linked signer) |
