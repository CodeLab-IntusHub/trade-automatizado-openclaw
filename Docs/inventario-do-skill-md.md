# Inventário do `SKILL.md` — o que é de uma instância só

> Última atualização: 24/09/2026 · ROADMAP, passo **1.1** · base: `SKILL.md` no
> commit `f474f96` (438 linhas)

O `SKILL.md` é o que o agente de cada bot lê. Hoje ele mistura regra do produto
com o jeito de operar de **uma** instância, a do autor. Este inventário
classifica cada trecho para os passos seguintes da Fase 1:

| Grupo | O que é | Destino |
|---|---|---|
| **G** — regra geral | vale para qualquer bot que instale a skill | fica |
| **I** — preferência de instância | escolha de um operador, ou valor de configuração repetido no texto | vira configuração (passo 1.2) ou referência à chave |
| **H** — histórico | data, nome ou decisão passada de uma instância | sai, ou vai para o `OPENCLAW-SOURCE.md` (passo 1.4) |

Além do grupo, duas marcas que não dependem dele:

- **1.3** — aponta para arquivo que não está no pacote.
- **⚠** — contradição com outro trecho do próprio `SKILL.md` ou com o código.
  Precisa de decisão antes da reescrita do passo 1.4, porque reescrever sem
  decidir só escolhe um dos lados em silêncio.

## Resumo

- **G:** a maior parte — venues, env, guardrails, segurança, modos, sizing,
  proteção de ordens, dashboard, first run, wizard, bloco de segredos da
  plataforma.
- **I:** 11 trechos. Os de maior peso: a entrega Discord no formato da
  instância (268), o fluxo "Hyperliquid top 50" (286) e o padrão de relatório de
  backtest inteiro (290–301).
- **H:** 6 trechos, quase todos nomes (Aspira, Zeus) e datas de decisão.
- **1.3:** 3 trechos (39, 263, 303) — os mesmos do ROADMAP.
- **⚠:** 2 contradições (39 × 268; 124 × 145–146).

## Classificação, trecho a trecho

| Linhas | Trecho | Grupo | Observação |
|---|---|---|---|
| 1–5 | frontmatter (`name`, `description`) | G | |
| 7–9 | título e escopo | G | |
| 13 | "Use quando o **owner** pedir ou quando houver demanda autorizada dentro da **governança atual**" | I | "owner" e "governança atual" são da instância; genérico é "quando o usuário pedir" |
| 15 | regra anti-legado: colaboradores anteriores, "desde 2026-08-04 … IntusHub/Aspira" | H | decisão de organização de uma instância; sai |
| 17–25 | "Use para" | G | |
| 26 | "configurar entrega **Discord/Zeus**" | G + H | a entrega Discord é do produto; "Zeus" é nome histórico |
| 30–38 | wizard curto: uma pergunta por vez, venues antes de credenciais, `default_1`, subconta recomendada e opcional | G | |
| 39 | Discord: carregar `doc referencia/05-entrega-discord-zeus.md`; "formato `embed_nativo` por padrão" | G + **1.3** + **⚠** | o arquivo não existe no pacote; e "embed nativo por padrão" contradiz a linha 268 ("sem card/embed nativo") |
| 42–82 | venues configuráveis, env de venue, comandos, contrato de DEX custom, CCXT | G | |
| 84–103 | wrapper `run.py`: venv, env opcional, fallback legado `delta-neutral-airdrop-farmer.env`, estado fora do Git | G | o fallback é compatibilidade, não histórico: o código ainda lê |
| 106–117 | guardrails OpenClaw: `.env` sob secret proxy, `config.env`, sandbox no `settings.json`, tamanho explícito, `cross`/`isolated`, credencial por modo, lock do state, mínimo Nado local | G | |
| 121–128 | segurança obrigatória | G | |
| 124 | "quando `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a regra da skill é usar automaticamente o owner" | G + **⚠** | **está certa:** `workspace/cli.py` passa `allow_owner_fallback=True` quando a chave falta. O que engana são as linhas 145–146: `NADO_REQUIRE_LINKED_SIGNER=true` não bloqueia sem linked signer, e `NADO_ALLOW_OWNER_FALLBACK=false` só vale para linked signer configurado e inválido. Se esse default é o desejado — assinar com a owner key sem avisar — é decisão do autor |
| 130–198 | env esperadas | G | |
| 200–207 | aliases legados, `--runtime-env` | G | |
| 209–223 | modos de execução | G | |
| 227–232 | sizing, mínimo por ativo, `--max-open-setups` | G | |
| 233 | allowlist `strict` por setup, overrides por env CSV | G | |
| 234 | **valores** das allowlists padrão por setup | I | os valores vivem no código (`cli.py`, `_quote_pairs`); repetidos aqui, derivam. Referenciar a fonte, não copiar a lista |
| 235–237 | allowlist própria por setup novo; sinal explícito; `asset-scan` | G | |
| 238 | guardrail cross da Nado; "para contas pequenas, prefira 8 slots" | G | recomendação com motivo, não preferência de instância |
| 239 | notificação de entrada; "Discord direto no **padrao Zeus**" | G + H | "padrão Zeus" é nome histórico |
| 240, 242–244 | parâmetros dos setups (ATR, RSI, EMA, alvos, timeout) e "prefira esta variante para live" | I | parâmetros de setup são configuração (`settings.json`, ver `Docs/features/configuracao-de-setups.md`); o texto deve apontar a chave, não fixar o valor |
| 241 | "`grid`, `hybrid` e `hybrid-15m` foram removidos/desativados" | H | |
| 245 | `delta-neutral`/`funding-arb` dependem de spread real | G | |
| 246–252 | stop, modo de stop por alvo, TP gerenciado da Nado, `ORPHAN`, `PNL potencial max`, TPs cruzados, dry-run | G | 248 diz "por env futura" — redação envelhecida, conferir na reescrita |
| 254–259 | exemplos | G | |
| 263 | "use `doc referencia/05-entrega-discord-zeus.md` apenas como histórico de migração. Zeus não é marca…" | H + **1.3** | arquivo ausente do pacote |
| 265–267 | token do bot, canal de teste, permissões | G | |
| 268 | "Formato correto do **IntusCripto**: uma única mensagem com texto + imagem anexada, sem card/embed nativo. Use `SETUP_NOTIFY_DISCORD_NATIVE_EMBED=false`, `SETUP_NOTIFY_BRAND=INTUSCRIPTO` e `SETUP_NOTIFY_DISCORD_BOX=false`." | I + **⚠** | formato e marca da entrega são escolha de quem opera — já são variáveis; o texto deve descrever as opções, não impor a da instância. Contradiz a linha 39 |
| 269–272 | menção de cargo, validação antes de canal público, `setup-live` como fluxo oficial | G | |
| 276–284 | fonte da verdade para presença/ausência de sinal | G | |
| 286 | "No fluxo **Hyperliquid top 50**, auditar via Hyperliquid…" | I | fluxo de uma instância; a regra geral já está em 278–284 |
| 290 | "Quando o **owner** pedir backtest, usar como padrão o **dashboard HTML v3** auditado **definido em 2026-07-21**" | I + H | preferência de instância com data de decisão |
| 292–301 | requisitos do relatório de backtest (filtros, colunas, glossário, QA em navegador) | I | "padrão visual do relatório de backtest", citado no ROADMAP 1.2 |
| 299 | "default operacional recente: **US$1.000** por cenário" | I | capital de simulação padrão, citado no ROADMAP 1.2 |
| 303 | "Scripts atuais do padrão ficam **no workspace**" | **1.3** | fora do pacote |
| 307–331 | dashboard do usuário: comandos, regras do painel, validação de publicação externa | G | |
| 332 | reiniciar `delta-dashboard-publisher.service` | I | nome de serviço systemd de uma máquina |
| 334–344 | roteiro de configuração do zero; diagnóstico por `live-status` | G | |
| 346–362 | first run obrigatório | G | |
| 364–370 | workflow recomendado | G | |
| 374–377, 379–381 | onboarding: uma pergunta por vez, escolhas múltiplas, nunca segredo no chat | G | |
| 378 | "use emoji na pergunta" | I | estilo de conversa da instância |
| 383–402 | questionário e regras do wizard | G | |
| 406–411 | "Responder em **PT-BR**, curto e operacional" | I | idioma e tom de quem opera; o formato (status, bloqueios, próximo comando, alerta de live) é G |
| 413–424 | bloco gerado `OPENCLAW_SKILL_WIZARD_PATHS` | G | bloco da plataforma OpenClaw; repete o wizard de 30–38 e 350 |
| 426–438 | bloco gerado `OPENCLAW_SECRET_GUIDANCE` | G | caminhos do secret manager da plataforma |

## O que isto alimenta

- **1.2** — os trechos **I** com valor (234, 240 e 242–244, 268, 292–301, 299) viram
  chave de configuração com o valor atual como default.
- **1.3** — 39, 263 e 303 esperam a decisão do autor, item a item.
- **1.4** — os trechos **H** saem; as duas **⚠** são decididas antes da
  reescrita; os **I** sem valor (13, 286, 290, 332, 378, 406) viram texto
  genérico.
