# Progresso

> Última atualização: 14 de setembro de 2026
> Versão da skill: 1.3.0

Estado do **produto** — o que existe e funciona. Roadmap e pendências de
trabalho não ficam aqui.

## Índice de documentação

| Doc | Cobre |
|---|---|
| [Configuração de setups](features/configuracao-de-setups.md) | `settings.json`, precedência, calibração por setup e timeframe |
| [Proteção de ordens](features/protecao-de-ordens.md) | Validação de SL/TP, substituição de stop, limitações por venue |

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

## Plataforma

Windows e Linux são alvos suportados e testados. A CI roda a suíte em
`ubuntu-latest` e `windows-latest` × Python 3.12 e 3.13.

## Portões de qualidade

`main` é protegida com 8 checks obrigatórios, aplicados também a
administradores: a matriz de pytest (4 combinações), a suíte com o SDK da Nado,
`ruff` (sintaxe e nome indefinido), `mypy` nos módulos anotados e o `validate`
do skill-ci. Cobertura, `pip-audit` e o ruff completo reportam sem bloquear.

Cobertura atual: ~42%. Sem piso definido — a decisão é medir antes de fixar.
