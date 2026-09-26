# Progresso

> Última atualização: 25 de setembro de 2026
> Versão da skill: 1.10.0

Estado do **produto** — o que existe e funciona. O que vem depois está no
[ROADMAP](ROADMAP.md); o porquê das decisões de arquitetura, em
[decisions/](decisions/).

## Índice de documentação

| Doc | Cobre |
|---|---|
| [Configuração de setups](features/configuracao-de-setups.md) | `settings.json`, precedência, calibração por setup e timeframe |
| [Proteção de ordens](features/protecao-de-ordens.md) | Validação de SL/TP, substituição de stop, limitações por venue |
| [Sandbox por venue](features/sandbox-por-venue.md) | Resolvedor único de sandbox, precedência e defaults por venue |
| [Vocabulário de configuração](features/vocabulario-de-booleanos.md) | Booleano, número e direção: valor irreconhecível recusado em vez de adivinhado |
| [Schema do settings](features/schema-do-settings.md) | Chave desconhecida derruba o comando em vez de ser ignorada |
| [config-export](features/config-export.md) | Emite o `settings.json` equivalente ao ambiente atual, e o que ele não cobre |
| [Contrato do sinal](features/contrato-do-sinal.md) | Registro estruturado de cada sinal: o conjunto exato de campos, travado por teste |
| [Escolha de venue e de modo](features/escolha-de-venue-e-modo.md) | Sem venue nem modo padrão: o operador escolhe, e o que falta para o comando |
| [Travas e auditoria](features/travas-e-auditoria.md) | Key sem saque conferida no `doctor`; rastro de cada execução real |
| [Entrega de mensagens](features/entrega-de-mensagens.md) | Avisos pelos canais do OpenClaw do operador; tópico do Telegram, bot dedicado |
| [Inventário do `SKILL.md`](inventario-do-skill-md.md) | Cada trecho do manual do agente: regra geral, preferência de instância ou histórico |

## Venues

| Venue | Papel | Adapter | Validação de resposta |
|---|---|---|---|
| Hyperliquid | DEX | próprio, via CCXT | sim |
| Kraken (spot/futures) | CEX | próprio, via CCXT | sim |
| Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io | CEX | `GenericCcxtTrader` | sim |
| Nado | DEX | SDK próprio (opcional) | parcial |
| DEX custom | DEX | `DEX_ADAPTER_MODULE` | depende do adapter |

**Nenhuma venue é padrão:** o operador escolhe `DEX_ID` e/ou `CEX_ID`, e sem
escolha os comandos de mercado param. A CEX é a fonte de candles em todos os
modos, então quem opera só DEX informa `CEX_ID` mesmo assim, sem credencial. O
modo de execução também não tem padrão — ver
[Escolha de venue e de modo](features/escolha-de-venue-e-modo.md).

O SDK da Nado é dependência **opcional** (`workspace/requirements-nado.txt`):
exige toolchain de build nativo, e só `DEX_ID=nado` precisa dele. As demais
venues rodam por CCXT.

## Configuração

Precedência: `env` → `settings.local.json` → `settings.json` → default do
código. A variável de ambiente vence o arquivo — o boot avisa quais chaves de
settings estão encobertas.

Segredo nunca entra no settings: o arquivo declara só o *nome* da variável.

`sandbox` tem resolvedor único (`workspace/venues/sandbox.py`): uma precedência,
um vocabulário, um default por venue. Valor inválido derruba o comando em vez de
virar `false` — ver [Sandbox por venue](features/sandbox-por-venue.md).

Sandbox se configura **por arquivo**, em `venues.<tipo>.<venue>.sandbox`. As
variáveis `*_SANDBOX` continuam sendo lidas e vencem o arquivo, por isso vêm
comentadas no `.env.example` e não são mais prescritas em documento nenhum; se
uma delas chegar pelo `config.env` do operador, o carregamento avisa qual chave
de settings ficou sem efeito.

Chave **desconhecida** no settings derruba o comando em vez de ser ignorada: um
typo no nome fazia a chave não ser lida e o valor efetivo virar o default — que
para `sandbox`, fora da família kraken, é produção. Ver
[Schema do settings](features/schema-do-settings.md).

## Autonomia do agente

O agente escolhe análises, ativos, setups e parâmetros dentro do que o operador
pede. As travas da skill (`AUTORIZAR_TRADE_REAL`, allowlist, `settings.json`)
são **instrução ao agente, não fechadura**: quem monta o comando é o próprio
agente, e ele tem shell. As travas que valem ficam fora da skill — na exchange
(key sem saque, subconta com capital limitado) e na aprovação de execução do
OpenClaw, encaminhada ao operador pelo chat. Três modos: análise (padrão), real
com aprovação (recomendado) e real autônomo — ver o
[ADR 0007](decisions/0007-autonomia-do-agente.md). O `doctor` confere se a
API key da CEX pode sacar (Binance, Bybit, OKX) e cada execução real deixa
rastro de auditoria — ver [Travas e auditoria](features/travas-e-auditoria.md).
O que falta está no passo 1.7 do ROADMAP.

## Sinais e marca

Cada sinal produz o **texto** entregue a pessoas e um
**registro estruturado** gravado no outbox local, que é o formato que o
ecossistema vai publicar. Todo campo do registro é explícito, e o conjunto de
chaves é travado por teste — ver [Contrato do sinal](features/contrato-do-sinal.md).

O texto sai pelos canais do OpenClaw do operador no `setup-live`; o scanner e o
watcher ainda falam direto com o Discord — ver
[Entrega de mensagens](features/entrega-de-mensagens.md). A marca da imagem do
sinal vem de `SETUP_NOTIFY_BRAND`; vazia, a imagem sai sem marca.

O produto se chama **IntusCripto**. O nome anterior, Aspira, permanece de
propósito em dois pontos que espelham estado fora do repositório (arquivos de
estado na máquina do operador e nomes no TradingView) — ver o
[ADR 0005](decisions/0005-rebrand-intuscripto.md).

## Pacote

O `.skill` que cada operador instala contém **só arquivos rastreados pelo git**
(`build.py`), sem instruções de desenvolvimento (`CLAUDE.md`). O que estiver
apenas no disco de quem empacota — caches, artefatos de auditoria, um
`settings.local.json` — não entra.

## Lugar na IntusHub

Este repositório é **satélite** do repositório de plataforma da IntusHub (ver
[`CLAUDE.md`](../CLAUDE.md)). Hoje a skill **não tem nenhuma integração** com o
banco compartilhado: não há DDL, Edge Function nem código que fale com ele. O
ecossistema da Fase 3 chega por endpoints da plataforma
([ADR 0006](decisions/0006-ecossistema-pela-plataforma.md)).

## Plataforma

Windows e Linux são alvos suportados e testados. A CI roda a suíte em
`ubuntu-latest` e `windows-latest` × Python 3.12 e 3.13.

## Portões de qualidade

`main` é protegida com 8 checks obrigatórios, aplicados também a
administradores: a matriz de pytest (4 combinações), a suíte com o SDK da Nado,
`ruff` (sintaxe e nome indefinido), `mypy` nos módulos anotados e o `validate`
do skill-ci. Cobertura, `pip-audit` e o ruff completo reportam sem bloquear.

Cobertura atual: ~42%. Sem piso definido — a decisão é medir antes de fixar.
