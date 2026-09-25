# Travas na exchange e rastro de auditoria

> Última atualização: 25 de setembro de 2026
> Versão: 1.10.0 (não publicada)

## Visão Geral

As travas da skill são instrução ao agente, não fechadura: quem monta o comando
é o próprio agente, e ele tem shell ([ADR 0007](../decisions/0007-autonomia-do-agente.md)).
Esta feature cuida das duas coisas que a skill consegue fazer de útil a partir
daí:

1. **Conferir a trava que vale.** O `doctor` pergunta à CEX se a API key pode
   sacar e reprova se puder. A key sem saque é o que limita o estrago de um
   agente que errou, alucinou ou foi induzido.
2. **Deixar rastro.** Cada execução real aprovada grava um registro de que o
   agente decidiu operar real, e por qual variável de confirmação.

## Key sem saque (`doctor`)

| Venue | Como verifica | Resultado |
|---|---|---|
| Binance | `GET /sapi/v1/account/apiRestrictions` → `enableWithdrawals` | verificado |
| Bybit | `GET /v5/user/query-api` → `permissions.Wallet` contém `Withdraw` | verificado |
| OKX | `GET /api/v5/account/config` → `perm` contém `withdraw` | verificado |
| Kraken, KuCoin, MEXC, Bitget, Gate.io e outras | a venue não expõe a permissão da própria key | "não verificado: confira no painel" |

- O check `cex_key_sem_saque` é **bloqueante só quando a venue confirma que a
  key saca**. "Não verificado" passa, com `verificado: false` e o motivo no
  detalhe: a falta de verificação não prova que a key saca, mas o operador
  fica sabendo que ninguém conferiu.
- Resposta que não dá para ler, erro de rede ou de autenticação viram "não
  verificado", **nunca** "sem saque": dúvida não é segurança.
- É a única chamada de rede do `doctor`, e só roda com credencial de CEX
  configurada; timeout de 10 s. A mensagem de erro não é repassada (pode ecoar
  a requisição): só o tipo da exceção.
- DEX fica de fora nesta versão. Na Hyperliquid, uma API wallet (agent) não
  saca, e a chave principal saca; na Nado, a owner key saca. Conferir isso é o
  próximo passo.

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
- Falhar ao gravar avisa no stderr e segue: é rastro, não trava. Pelo mesmo
  motivo, o agente pode apagar o arquivo; o rastro que o agente não alcança é
  o histórico de ordens da exchange.

## Componentes

| Componente | Arquivo | Função |
|---|---|---|
| Permissão de saque | `workspace/venues/permissao_de_saque.py` | `interpretar` (puro) e `consultar` (CCXT) |
| Check do `doctor` | `workspace/run.py` (`_check_key_sem_saque`) | liga o veredicto ao relatório |
| Rastro | `workspace/cli.py` (`_record_live_trade_confirmation`) | grava a linha de auditoria |

Testes: `test/test_permissao_de_saque.py` e `test/test_auditoria_trade_real.py`.
O `conftest` desliga a rede dessa consulta em toda a suíte.

## Changelog

| Data | Mudança |
|---|---|
| 25/09/2026 | Check `cex_key_sem_saque` no `doctor` (Binance, Bybit, OKX) e rastro de auditoria da confirmação real |
