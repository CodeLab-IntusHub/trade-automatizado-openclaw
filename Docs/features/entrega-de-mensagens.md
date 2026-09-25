# Entrega de mensagens

> Última atualização: 25 de setembro de 2026
> Versão: 1.10.0 (não publicada)

## Visão Geral

Os avisos de entrada, de alvo, de stop e de fechamento saem pelos **canais do
OpenClaw do próprio operador**: Telegram, WhatsApp, Discord ou qualquer outro
que ele tenha configurado. A skill chama `openclaw message send`. Ela não fala
com a API de mensageria nenhuma e não lê nem guarda token de bot. O
`setup-live`, o scanner e o watcher passam pela mesma função
(`_send_setup_trade_notice`) e leem a mesma configuração.

A entrega é **opcional**. Sem canal configurado, a skill opera e não envia nada.

**Por quê.** Até a v1.8.0, o Discord ia direto pela API REST, com um token de
bot que a skill lia do ambiente e até do `~/.openclaw/openclaw.json`. O
fallback para o OpenClaw vinha desligado, então uma falha descartava a mensagem
sem aviso. O canal padrão era `telegram`, e a conta padrão, `default`: escolhas
da instância original, impostas a quem não escolheu. O scanner e o watcher
tinham cópias próprias, com defaults diferentes (WhatsApp ligado só por haver
destino, audiência "@Intus Club Member" fixa).

## Opções

| Necessidade | Como |
|---|---|
| Canal principal | `SETUP_NOTIFY_ENTRY_CHANNEL` + `SETUP_NOTIFY_ENTRY_TARGET` (sem padrão; destino sem canal não é enviado, e o log avisa) |
| Tópico de um grupo do Telegram | `SETUP_NOTIFY_ENTRY_THREAD_ID` ou `--notify-entry-thread-id`, que vira `--thread-id` |
| Bot dedicado | uma conta dedicada configurada no OpenClaw, informada em `SETUP_NOTIFY_ENTRY_ACCOUNT` (vazio = conta padrão do OpenClaw) |
| Cópia extra no Discord | `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID` (e `_ACCOUNT`), também pelo OpenClaw |
| Cópia extra no WhatsApp | `SETUP_NOTIFY_WHATSAPP_ENABLED=true` + `SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET` (e `_ACCOUNT`); sem o opt-in, nada vai |
| Linha de audiência no topo | `SETUP_NOTIFY_DISCORD_AUDIENCE` (vazio = sem linha) |

As atualizações de uma posição saem como **resposta** à mensagem de entrada no
Discord e no WhatsApp. O id dessa mensagem, devolvido pelo `openclaw message
send --json`, fica guardado no estado da posição. As menções no Discord seguem
a configuração do OpenClaw.

## Componentes

| Componente | Arquivo | Estado |
|---|---|---|
| Entrega | `workspace/cli.py` (`_send_setup_trade_notice`, `_send_entry_notification`) | caminho único, pelo OpenClaw |
| `setup-live` e `notify-monitored` | `workspace/cli.py` | chamam a entrega |
| Scanner de sinais (analysis-only) | `workspace/ccxt_entry_scanner.py` (`_send_signals`) | fila assíncrona; cada item chama a entrega com o gráfico já renderizado e grava o resultado no outbox |
| Watcher do log | `workspace/discord_signal_watcher.py` (`_send`) | chama a entrega |
| Onboarding | `workspace/first_run_setup.py` (`DELIVERY_GUIDANCE`) | pergunta canal, destino, conta e tópico; nunca token |
| `config.env` | `workspace/run.py` (`NON_SECRET_CONFIG_ENV`) | aceita as dez variáveis de entrega |

O nome `discord_signal_watcher.py` é histórico: o watcher entrega em qualquer
canal configurado.

Testes: `test/test_entrega_pelo_openclaw.py` e
`test/test_entrega_scanner_watcher.py`. Eles proíbem chamada de rede direta e
travam a ausência da API do Discord e do token nos três componentes.

## Changelog

| Data | Mudança |
|---|---|
| 25/09/2026 | `setup-live` só pelo OpenClaw; sem canal nem conta padrão; tópico do Telegram com flag (#40) |
| 25/09/2026 | Scanner e watcher pela mesma entrega; sem audiência fixa; onboarding sem token; allowlist do `config.env` completa |
