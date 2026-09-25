# ADR 0007 — Autonomia do agente: as travas que valem ficam fora da skill

> Data: 25 de setembro de 2026
> Status: **Aceita**
> Decidida em conselho (modo rápido: Architect, Skeptic, Pragmatist, Critic) e
> confirmada pelo autor, que respondeu as perguntas em aberto.

## Contexto

O agente OpenClaw lê o `SKILL.md` e roda os comandos da skill. Dentro do que o
usuário pede, ele escolhe análises, ativos, setups e parâmetros. A pergunta é
quanto ele pode fazer sozinho, principalmente quando a ação abre posição com
dinheiro real.

Até aqui, as travas de operação real eram da própria skill:
`AUTORIZAR_TRADE_REAL=sim` na execução (`workspace/run.py`), allowlist estrita
por setup e limites no `settings.json`. **Nenhuma delas prende o agente:**

- quem monta o comando é o próprio agente, e ele pode definir a variável de
  confirmação, abrir a allowlist ou editar o `settings.json`;
- o agente tem shell na máquina do operador e lê a API key, então pode chamar a
  exchange direto e passar por fora da skill inteira.

Toda trava escrita na skill é **instrução ao agente**, não fechadura. Um agente
bem comportado para; um que entendeu mal o pedido, ou que foi induzido por
texto vindo de fora (nome de token, mensagem de grupo, campo de API), passa.

O produto também vira um **ecossistema** em que as decisões e os resultados de
cada agente servem de aprendizado para os outros (ROADMAP, passo 3.9). O que um
agente registra passa a influenciar todos.

## Opções consideradas

1. **Três níveis de autonomia com travas da skill** (análise; real com
   confirmação; real autônomo com limites). Proposta inicial. Caiu no conselho:
   a confirmação e os limites seriam forjáveis pelo próprio agente.
2. **Dois modos, com a trava na exchange:** análise, e real preso ao que a
   exchange impõe (key sem saque, subconta com capital limitado).
3. **A plataforma guarda as chaves e executa por um proxy.** Seria a única
   forma de um limite valer contra um agente com shell. Transforma a IntusHub em
   custodiante de credenciais de terceiros, com responsabilidade regulatória e
   um alvo concentrado para ataque.
4. **A opção 2, mais a aprovação de execução do OpenClaw** como a confirmação
   humana. O OpenClaw aprova comandos no processo do Gateway (ou do node host),
   fora do alcance do agente, e encaminha o pedido ao operador pelo chat
   (Slack, Discord, Telegram, Matrix, com `/approve`) ou pelo app.

## Decisão

**Opção 4.** Custódia de chaves (opção 3) está **descartada em definitivo**: o
produto é independente e não guarda credencial de ninguém.

**Os modos de operação:**

| Modo | O que o agente faz sozinho | O que prende de verdade |
|---|---|---|
| **Análise** (padrão de toda instalação) | scanner, backtest, simulação, dry-run, leitura de posição | nada a prender: não abre ordem |
| **Real com aprovação** (recomendado) | prepara a ordem; cada comando de trade espera o operador aprovar pelo chat | aprovação de execução do OpenClaw com allowlist estreita, mais as travas da exchange |
| **Real autônomo** | abre e gerencia posição sem pedir | só as travas da exchange: o teto real de perda é o saldo da subconta |

**As travas que valem, e onde vivem:**

- **Na exchange:** API key **sem permissão de saque**, subconta ou conta
  separada com **só o capital que o bot pode perder**, e os limites de conta que
  a venue oferecer. A skill verifica o que der para verificar (por exemplo,
  recusar operar se a key puder sacar, onde a venue expõe essa permissão) e diz
  ao operador, com franqueza, o que não dá para verificar.
- **No OpenClaw:** `tools.exec` em **allowlist estreita** (os comandos da skill,
  sem `python -c`, `curl` ou shell livre) e **pedido de aprovação para os
  comandos de trade**. Com o modo `full`, ou uma allowlist larga, o agente
  contorna a aprovação. A skill documenta a configuração recomendada; quem
  aplica é o operador.
- **Segredos:** no gerenciador de segredos do operador. A skill **sempre
  sugere o 1Password**, e nunca pede segredo no chat.

**`AUTORIZAR_TRADE_REAL` fica, com outro papel:** deixa de ser apresentada como
trava e passa a ser **rastro de auditoria**. Ela registra que o agente decidiu
operar real, naquela execução, e vai para o log. O mesmo vale para as três
variáveis que o código aceita como equivalentes (`CONFIRMAR_TRADE_REAL`,
`TRADE_AUTOMATIZADO_CONFIRM_LIVE` e `DELTA_NEUTRAL_CONFIRM_LIVE`): o registro
olha para qualquer uma delas, ou uma execução autorizada por outra ficaria sem
rastro.

**O que entra no aprendizado coletivo:** só **resultados conferíveis na
exchange**, ou seja, fills reconciliados pela API da venue. O relato do agente
sobre o que fez, e o raciocínio narrado por ele, não entram como fato. Um agente
que alucinou, mentiu ou foi induzido por texto externo não pode ensinar os
outros.

## Consequências

- **A instância que opera hoje não tem aprovação:** roda com `security: full`
  (e `ask: on-miss`) no OpenClaw, o que na prática dispensa a aprovação. Ela é,
  pela tabela acima, **real autônomo**. Mudar isso é configuração do OpenClaw,
  não mudança na skill.
- **A skill passa a orientar, no onboarding e no `doctor`:** a configuração de
  aprovação recomendada, as permissões da key e o isolamento de capital. O
  `doctor` avisa quando conseguir detectar que o modo do OpenClaw dispensa
  aprovação (o formato da configuração precisa ser confirmado antes).
- **A documentação para de chamar travas da skill de segurança.** Onde o texto
  diz que a skill "bloqueia", passa a dizer o que ela instrui e onde está a
  trava de verdade.
- **Três itens obrigatórios no `premortem` da Fase 3**, porque só aparecem com
  muitos agentes:
  1. **Risco sistêmico:** todos aprendem do mesmo banco, convergem no mesmo
     sinal e entram juntos no mesmo ativo ilíquido. Limite por operador não pega
     isso; o ecossistema precisa de um teto de exposição agregada por ativo.
  2. **Injeção de instrução via dados:** nome de token, mensagem de grupo e
     campo de API chegam ao agente como texto. Entram no modelo de ameaça como
     item de primeira classe.
  3. **Envenenamento do aprendizado:** coberto pela regra dos fills
     reconciliados, que precisa de teste na Edge Function que recebe.
- **Adendo de 25/09/2026 (decisão do autor): saque é aviso, bloqueio é
  escolha.** "Sacar não é um bloqueador, somente um warning que o usuário
  deve ter ciência. Quando possível, sempre bloquear configurável." Onde
  este ADR diz "recusar operar se a key puder sacar", vale: o `doctor`
  **avisa** (key da CEX com saque, saque automático da Nado, OpenClaw sem
  aprovação), e o operador liga o bloqueio com `BLOQUEAR_SAQUE` e
  `BLOQUEAR_SEM_APROVACAO`. Ligado, o `doctor` reprova e o comando de trade
  é recusado. O que não dá para verificar nunca bloqueia. Como toda trava da
  skill, o agente pode desligar a variável: é escolha do operador, não
  fechadura. A política do OpenClaw vem de `openclaw exec-policy show
  --json`; o `exec-approvals.json` foi aposentado nas versões novas.
- **A telemetria continua opt-in,** pela mesma razão do
  [ADR 0002](0002-sentry-nao-se-aplica.md): a skill roda na máquina do operador.
