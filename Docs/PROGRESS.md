# Progresso

> Última atualização: 24 de setembro de 2026
> Versão da skill: 1.6.0

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
| [Contrato do sinal](features/contrato-do-sinal.md) | Registro estruturado de cada sinal: campos, fronteira pública e campos de legado |

## Venues

| Venue | Papel | Adapter | Validação de resposta |
|---|---|---|---|
| Hyperliquid | DEX | próprio, via CCXT | sim |
| Kraken (spot/futures) | CEX | próprio, via CCXT | sim |
| Binance, Bybit, OKX, KuCoin, MEXC, Bitget, Gate.io | CEX | `GenericCcxtTrader` | sim |
| Nado | DEX | SDK próprio (opcional) | parcial |
| DEX custom | DEX | `DEX_ADAPTER_MODULE` | depende do adapter |

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

## Sinais e marca

Cada sinal produz o **texto** entregue a pessoas (Discord, WhatsApp) e um
**registro estruturado** gravado no outbox local, que é o formato que o
ecossistema vai publicar. O registro só leva campos declarados — ver
[Contrato do sinal](features/contrato-do-sinal.md).

O produto se chama **IntusCripto**. O nome anterior, Aspira, permanece de
propósito em três pontos que espelham estado fora do repositório (arquivos de
estado na máquina do operador, nomes no TradingView e o campo `schema` do
sinal) — ver o [ADR 0005](decisions/0005-rebrand-intuscripto.md).

## Plataforma

Windows e Linux são alvos suportados e testados. A CI roda a suíte em
`ubuntu-latest` e `windows-latest` × Python 3.12 e 3.13.

## Portões de qualidade

`main` é protegida com 8 checks obrigatórios, aplicados também a
administradores: a matriz de pytest (4 combinações), a suíte com o SDK da Nado,
`ruff` (sintaxe e nome indefinido), `mypy` nos módulos anotados e o `validate`
do skill-ci. Cobertura, `pip-audit` e o ruff completo reportam sem bloquear.

Cobertura atual: ~42%. Sem piso definido — a decisão é medir antes de fixar.
