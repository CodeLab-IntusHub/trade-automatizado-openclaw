# Entrega de mensagens

> Última atualização: 25 de setembro de 2026
> Versão: 1.9.0

## Visão Geral

Os avisos de entrada, de alvo, de stop e de fechamento saem pelos **canais do
OpenClaw do próprio operador**: Telegram, WhatsApp, Discord ou qualquer outro
que ele tenha configurado. A skill chama `openclaw message send`. Ela não fala
com a API de mensageria nenhuma e não lê nem guarda token de bot.

A entrega é **opcional**. Sem canal configurado, a skill opera e não envia nada.

**Por quê.** Até a v1.8.0, o Discord ia direto pela API REST, com um token de
bot que a skill lia do ambiente e até do `~/.openclaw/openclaw.json`. O
fallback para o OpenClaw vinha desligado, então uma falha descartava a mensagem
sem aviso. O canal padrão era `telegram`, e a conta padrão, `default`: escolhas
da instância original, impostas a quem não escolheu.

## Opções

| Necessidade | Como |
|---|---|
| Canal principal | `SETUP_NOTIFY_ENTRY_CHANNEL` + `SETUP_NOTIFY_ENTRY_TARGET` (sem padrão; destino sem canal não é enviado, e o log avisa) |
| Tópico de um grupo do Telegram | `SETUP_NOTIFY_ENTRY_THREAD_ID` ou `--notify-entry-thread-id`, que vira `--thread-id` |
| Bot dedicado | uma conta dedicada configurada no OpenClaw, informada em `SETUP_NOTIFY_ENTRY_ACCOUNT` (vazio = conta padrão do OpenClaw) |
| Cópia extra no Discord | `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` (e `_ACCOUNT`), também pelo OpenClaw |
| Cópia extra no WhatsApp | `SETUP_NOTIFY_WHATSAPP_ENABLED` + `SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET` (e `_ACCOUNT`) |

As atualizações de uma posição saem como **resposta** à mensagem de entrada no
Discord e no WhatsApp. O id dessa mensagem, devolvido pelo `openclaw message
send --json`, fica guardado no estado da posição. As menções no Discord seguem
a configuração do OpenClaw.

## Componentes

| Componente | Arquivo | Estado |
|---|---|---|
| `setup-live` e `notify-monitored` | `workspace/cli.py` (`_send_setup_trade_notice`, `_send_entry_notification`) | só pelo OpenClaw |
| Scanner de sinais (analysis-only) | `workspace/ccxt_entry_scanner.py` | **ainda envia ao Discord direto**, com token próprio |
| Watcher do log | `workspace/discord_signal_watcher.py` | **ainda envia ao Discord direto**, com token próprio |

A migração do scanner e do watcher, a audiência e a marca como configuração, e
o onboarding perguntando canal, destino, conta e tópico estão no
[ROADMAP, passo 1.8](../ROADMAP.md).

Testes: `test/test_entrega_pelo_openclaw.py`. O teste proíbe chamada de rede
direta e trava a ausência da API do Discord e do token no `cli.py`.

## Changelog

| Data | Mudança |
|---|---|
| 25/09/2026 | `setup-live` só pelo OpenClaw; sem canal nem conta padrão; tópico do Telegram com flag (#40) |
