## v1.1.22 — 2026-06-16

> Bump: PATCH
> Compatibilidade: sem quebra. Adiciona stop por alvo configurável e hardening de validação sem alterar aliases históricos.

### Added
- `setup-live --modo-stop-alvo desligado|entrada-no-tp1|escada` e env `SETUP_LIVE_TARGET_STOP_MODE`.
- Capacidades de venue para indicar suporte a SL/TP nativo, cancelamento de trigger e reduce-only.

### Changed
- Stop movido por alvo fica documentado como gerenciamento do loop `setup-live`; recriação de ordem stop nativa depende de suporte explícito da venue.
- `skill.json.version` atualizado para `1.1.22`.

### Validation
- [x] `python3 build.py` (`trade-automatizado-openclaw-1.1.22.skill`).
- [x] `quick_validate.py` (`Skill is valid!`).
- [x] `python3 -m py_compile` dos módulos principais.
- [x] `workspace/run.py setup-check --json` fora do sandbox por falha `bwrap` no sandbox.
- [x] `pytest -q` pela venv operacional relacionada (`115 passed`).

### Rollback
- Voltar para o commit anterior ao `58c6b75` ou publicar novo PATCH se o modo de stop por alvo causar regressão operacional.

## v1.1.20 — 2026-06-16

> Bump: PATCH
> Compatibilidade: sem quebra. Amplia venues configuráveis mantendo Nado DEX + Kraken CEX como defaults.

### Added
- Wizard pergunta DEX/CEX antes de secrets, modo, sizing e margem.
- Onboarding lista Nado, Hyperliquid, Binance, Kraken, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io.
- Suporte operacional a CEX genérica via CCXT, Hyperliquid DEX builtin e DEX custom por `DEX_ADAPTER_MODULE`.

### Changed
- Subconta/conta isolada fica recomendada quando a venue oferecer, mas não obrigatória por padrão; o mínimo exigido é credencial dedicada sem saque e validação por `doctor`/dry-run.

### Validation
- [x] Validado no ciclo local de retomada de 2026-06-17 junto com `v1.1.22`.

## v1.1.19 — 2026-06-01

> Bump: PATCH
> Compatibilidade: sem quebra. Ajusta guardrails e labels operacionais sem remover aliases historicos.

### Changed
- `low-stoch-storm` agora usa BTC/ETH/SOL/XRP como allowlist padrão, refletindo validação operacional real.
- `divergence-and-volume-*` agora usa ETH/XMR como allowlist padrão e whitelist estrita default.
- Defaults das validações reais dedicadas passam a focar os símbolos validados por setup.
- `skill.json.version` atualizado para `1.1.19`.

### Fixed
- O ranking operacional preserva labels separados para `Divergence and Volume 15m`, `1h` e `4h`.

### Validation
- [x] `git diff --check`.
- [x] `python3 -m py_compile workspace/*.py workspace/core/*.py workspace/kraken/*.py workspace/nado/*.py test/*.py`.
- [x] `python3 -m pytest test/test_smoke.py test/test_v2.py test/test_trade_dashboard.py` (100 passed).
- [x] `python3 workspace/run.py --help`.
- [x] `python3 workspace/run.py setup-check --json`.
- [x] Validação operacional sintética registrada.
- [x] Validação real do Low Stoch Storm via Binance.
- [x] Validação real do Divergence and Volume via Binance.
- [x] Secret scan local para padroes `sk-`, `gho_`, `AIza`, `xoxb-` e private-key blocks.

### Rollback
- Tag anterior estavel: `v1.1.18`.
- Procedimento: publicar novo PATCH a partir de `v1.1.18` se a restricao de allowlist reduzir cobertura operacional de forma indevida.

## v1.1.18 — 2026-05-26

> Bump: PATCH
> Compatibilidade: sem quebra. Corrige nomes publicos/documentacao dos setups sem remover aliases historicos de entrada.

### Fixed
- Corrige a entrega publica dos setups para usar `low-stoch-storm` e `divergence-and-volume-*`, removendo nomes antigos Zeus/DIVAP da documentacao ativa, manifesto e labels operacionais.
- Corrige comandos/manifesto das validações reais dedicadas de Low Stoch Storm e Divergence and Volume.
- Corrige configuracao runtime de Divergence and Volume por timeframe (`15m`, `1h`, `4h`) e allowlists correspondentes.

### Changed
- `skill.json.version` atualizado para `1.1.18`.
- `metadata.wizard.release_note` aponta a correcao atual.
- Tracking: closes #1.

### Validation
- [x] `git diff --check`.
- [x] `python3 -m py_compile workspace/*.py workspace/core/*.py workspace/kraken/*.py workspace/nado/*.py test/*.py`.
- [x] `python3 workspace/run.py --help`.
- [x] `python3 workspace/run.py setup-check --json`.
- [x] `python3 workspace/run.py setups`.
- [x] `python3 -m pytest test/test_smoke.py test/test_v2.py test/test_trade_dashboard.py` (98 passed).
- [x] Secret scan local para padroes `sk-`, `gho_`, `AIza`, `xoxb-` e private-key blocks.

### Rollback
- Tag anterior estavel: `v1.1.17`.
- Procedimento: publicar novo PATCH a partir de `v1.1.17` se a correcao de nomenclatura causar regressao.

## v1.1.16 — 2026-05-15

> Bump: PATCH
> Compatibilidade: sem quebra. Alinha o PRD ao Skill Builder sem alterar lógica operacional/live.

### Added
- PRD HTML documenta **Caminho iniciante** e **Caminho avançado** para o usuário.
- PRD HTML explicita que `wizard_path` é a primeira pergunta e vem antes de `setup-check`/`doctor`.
- PRD HTML registra runtime/path operacional e payload real do wizard.

### Changed
- Fluxo visual do PRD agora começa por wizard/coleta mínima antes de diagnóstico.
- `metadata.wizard.release` alinhado para `1.1.16`.

### Validation
- [x] `skill.json` válido.
- [x] `workspace/first_run_setup.py --json` começa em `wizard_path`.
- [x] PRD validado com `review_generated_html.py` sem warnings.
- [x] `python3 -m py_compile workspace/first_run_setup.py`.

## v1.1.15 — 2026-05-14

> Bump: PATCH
> Compatibilidade: sem quebra. Corrige a ordem do first run para não bloquear o wizard em `setup-check`.

### Fixed
- First run agora começa pelo wizard antes de qualquer `setup-check`/`doctor`.
- Primeira pergunta obrigatória explicitada como `wizard_path` (`Caminho iniciante` ou `Caminho avançado`).
- Se `workspace/run.py` ou o pacote operacional estiver ausente, o wizard textual não deve ser bloqueado; a validação técnica fica pendente.

### Changed
- `skill.json.metadata.wizard` agora declara `first_run_required_until_configured=true`, `first_run_starts_before_setup_check=true` e `first_question=wizard_path`.
- `SKILL.md` remove a ambiguidade que induzia agentes a rodarem `setup-check` antes do onboarding.

### Validation
- [x] `skill.json` válido.
- [x] `workspace/first_run_setup.py --json` válido.
- [x] `question_flow[0].field = wizard_path`.

## v1.1.14 — 2026-05-13

> Bump: PATCH
> Compatibilidade: sem quebra. Torna a orientação de credenciais determinística no payload do wizard.

### Added
- `credential_guidance` estruturado no payload `first_run_setup.py --json`, com texto pronto para usuário e caminhos do secret manager em **Chaves e Segredos**.

### Changed
- Wizard não depende mais da LLM para explicar onde configurar chaves/segredos; a orientação vem pronta no payload.

### Security
- Reforçado: nunca pedir API key, token, webhook, OAuth, private key, seed ou secret value no chat.

### Validation
- [x] `first_run_setup.py --json` retorna `next_question.field = wizard_path`.
- [x] `credential_guidance.must_show_to_user = true`.

## Security guidance — 2026-05-13

### Security
- Padronizada orientação OpenClaw para chaves e segredos: nunca pedir valores no chat; orientar Chaves LLM, Chaves de Serviço ou OAuth Token conforme o tipo de credencial.

## v1.1.13 — 2026-05-13

> Bump: PATCH
> Compatibilidade: sem quebra. Atualiza wizard para o padrão OpenClaw por caminhos.

### Added
- Escolha inicial no wizard entre **Caminho iniciante** e **Caminho avançado**.
- Passo a passo documentado para os dois caminhos em `references/onboarding-questionario.md`.

### Changed
- `SKILL.md` e `README.md` passam a apontar explicitamente para o wizard por caminhos.
- `first_run_setup.py` agora emite `wizard_path` como primeira pergunta, `wizard_paths` no payload e `question_flow` iniciado pela escolha de caminho.

### Security
- Mantido guardrail de nunca pedir segredos no chat; credenciais devem estar em env/Secret Manager/OpenClaw.

### Validation
- [ ] Validar comando mínimo/runtime específico da skill antes da release oficial.

## v1.1.12 — 2026-05-13

> Bump: PATCH
> Compatibilidade: sem quebra. Release limpa/aprovada após reversão da `v1.1.11`.

### Changed
- Mantém o comportamento aprovado da `v1.1.10`.
- Marca esta release como a referência correta após a `v1.1.11` ter sido revertida.
- Preserva a regra: `NADO_SUBACCOUNT_NAME` não é pergunta obrigatória do wizard curto; usar `default_1` por padrão e só orientar ajuste se houver subconta customizada ou falha no diagnóstico.

### Validation
- [x] `python3 workspace/first_run_setup.py --json`
- [x] `python3 workspace/run.py --help`
- [x] Runtime sincronizado para `1.1.12`.

### Nota operacional
- `v1.1.11` não deve ser usada como release de validação/instalação. A release correta é `v1.1.12`.

## v1.1.10 — 2026-05-12

> Bump: PATCH
> Compatibilidade: sem quebra. Ajusta o wizard curto para não tratar `NADO_SUBACCOUNT_NAME` como pergunta obrigatória.

### Changed
- Wizard curto passa a usar `NADO_SUBACCOUNT_NAME=default_1` como default operacional.
- O nome da subconta Nado só deve ser pedido/orientado se o usuário usar subconta customizada ou se `setup-check`/`doctor` falhar.
- Checklist do onboarding agora separa segredo obrigatório (`NADO_OWNER_PRIVATE_KEY`) de config não sensível opcional (`NADO_SUBACCOUNT_NAME`).

### Validation
- [x] `python3 workspace/first_run_setup.py --json`
- [x] `python3 workspace/run.py --help`
- [x] Verificação textual: o wizard curto não pergunta o nome da subconta como requisito obrigatório.

## v1.1.9 — 2026-05-12

> Bump: PATCH
> Compatibilidade: sem quebra. Release correta para validação do wizard curto final.

### Changed
- Consolida a correção do wizard curto sem link/cadastro externo.
- Mantém `account_and_secrets_status` no payload do wizard.
- Marca a release do wizard em `skill.json.metadata.wizard.release`.

### Validation
- [x] `python3 workspace/first_run_setup.py --json`
- [x] `python3 workspace/run.py --help`
- [x] Verificação de ausência de `sign-up`, `referral`, `inviteCode` e “você consegue abrir o site” no wizard/referências.

## v1.1.8 — 2026-05-12

> Bump: PATCH
> Compatibilidade: sem quebra. Ajusta a fala do wizard curto para não puxar cadastro/link externo.

### Changed
- Wizard curto não envia link de cadastro nem pergunta “você consegue abrir o site?”.
- Campo `secrets_status` virou `account_and_secrets_status`, cobrindo acesso às plataformas + envs salvas.
- Guia detalhado remove links/referrals diretos do texto operacional e orienta usar domínios oficiais quando o usuário pedir passo a passo.

### Validation
- [x] `python3 workspace/first_run_setup.py --json`
- [x] `python3 workspace/run.py --help`

## v1.1.7 — 2026-05-12

> Bump: PATCH
> Compatibilidade: sem quebra. Encurta o wizard real e preserva o guia longo como referência sob demanda.

### Added
- `workspace/first_run_setup.py --json` com payload chat-first curto para descoberta automática.
- `references/onboarding-detalhado.md` preservando o guia longo Nado/Kraken para uso sob demanda.
- Metadado `metadata.wizard` em `skill.json` apontando para wizard curto e referência detalhada.

### Changed
- `references/onboarding-questionario.md` agora é curto e operacional: 6 perguntas essenciais.
- Wizard passa a perguntar só modo, ambiente, status de secrets, sizing, margem e autorização para `setup-check`/`doctor`.
- Detalhes de criação de conta, bridge, Ink, API Kraken e troubleshooting saíram do fluxo principal.

### Security
- Reforçado: nunca pedir private key, seed, mnemonic, API secret ou token no chat.
- Live/mainnet continua exigindo sizing explícito e confirmação explícita.

### Validation
- [x] `python3 workspace/first_run_setup.py --json`
- [x] `python3 workspace/run.py --help`

### Rollback
- Voltar para `v1.1.6` se o agente validador precisar do questionário longo como fluxo principal.

## v1.1.0 — 2026-05-09


## 1.1.6 - 2026-05-12

- Ajusta fallback Nado para TP parcial abaixo do mínimo nativo: fecha 100% no primeiro alvo gerenciado por padrão (`SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`).
- `live-status` passa a marcar exposições reais como `managed` ou `ORPHAN`, sem fechar posições automaticamente.
- Registra `PNL potencial max` por entrada e avança múltiplos TPs cruzados na mesma iteração do loop.
- Reforça que `setup-live --dry-run` não executa TP/SL real nem libera slot como live.

> Bump: MINOR
> Compatibilidade: nenhuma quebra. Skill funciona exatamente como antes — refactor lossless de documentacao.

### Added
- `references/onboarding-questionario.md` — questionario completo de onboarding OpenClaw (14 sub-sessoes Nado + Kraken) carregado sob demanda. Conteudo verbatim extraido de SKILL.md v1.0.20 sem modificacao semantica.
- `.github/workflows/ci.yml` apontando OpenClaw-Skills/skill-ci@v1.

### Changed
- `SKILL.md` reduzido de 703 para 237 linhas (66% reducao). Secoes "Onboarding OpenClaw" mantida com pointer normativo para references/onboarding-questionario.md. Demais secoes (frontmatter, guardrails, seguranca, env esperadas, modos, sizing, dashboard, workflow, formato de resposta) **inalteradas**.
- `SKILL.md` frontmatter `name`: `trade-automatizado-openclaw` -> `trade-automatizado-openclaw` (alinha com slug do repo).
- `skill.json.name`: idem.
- `skill.json.license`: MIT -> Proprietary (alinha com policy da org).
- `skill.json.homepage`: `skill-delta-trade-nado-kraken-OpenClaw` -> `trade-automatizado-openclaw`.
- `LICENSE`: MIT -> Proprietary (texto padrao da org).

### Fixed
- Token cost no system prompt do bot reduzido em ~500 linhas (questionario so e carregado quando user pede onboarding).

### Security
- Nenhuma mudanca de comportamento de seguranca. Guardrails (DELTA_NEUTRAL_CONFIRM_LIVE, env-only secrets, dry-run obrigatorio) preservados verbatim.

### Migration Notes
- **Comportamento operacional inalterado**. Todos os comandos (`setup-check`, `doctor`, `setup-live`, `open`, `dashboard`, etc.) funcionam identicamente.
- Bot que ja roda esta skill continua sem precisar de mudanca de configuracao apos atualizar.
- Apenas mudou: SKILL.md menor + arquivo references/ novo.

### Validation
- [x] SKILL.md frontmatter validado (name=trade-automatizado-openclaw)
- [x] skill.json.version 1.0.20 -> 1.1.0 (MINOR — adicao retrocompativel de references/)
- [x] Tag a criar: v1.1.0
- [x] Sem secrets, sem .env, sem artefatos de runtime versionados
- [x] CI da org passa (skill-ci v1.2.0 — whitelist do diretório padrão do OpenClaw)
- [x] Conteudo do questionario verbatim no references/ (497 linhas, conferido por wc + diff)

### Rollback
- Tag anterior estavel: v1.0.20
- Procedimento: criar branch a partir de v1.0.20, bumpar PATCH (v1.0.21) com nota de erratum, publicar nova release. SKILL.md de 703 linhas volta tal qual.
