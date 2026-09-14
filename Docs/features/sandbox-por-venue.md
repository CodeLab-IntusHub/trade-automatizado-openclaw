# Sandbox por venue

> Última atualização: 14 de setembro de 2026
> Versão: 1.0.0

## Visão geral

`sandbox` decide se a ordem vai para dinheiro de brinquedo ou para dinheiro
real. É a configuração de maior consequência do sistema, e até esta versão era
respondida em **quatro lugares com regras diferentes**:

| Onde | Precedência | Vocabulário | Default |
|---|---|---|---|
| `_load_cex_sandbox` (cli) | genérica `CEX_SANDBOX` ganha | `{1,true,yes,sim}` | kraken → `True` |
| `_load_pair_cex_sandbox` (cli) | específica `<PREFIX>_SANDBOX` ganha | idem | kraken → `True` |
| `venue_summary` (venues) | genérica ganha | string crua, sem normalizar | `"true"`/`"false"` |
| `run.py` safe_defaults | genérica, senão o resumo | string crua | `"false"` |

Dois defeitos concretos saíam daí:

1. **Typo virava produção em silêncio.** Os dois primeiros só definiam o lado
   verdadeiro do vocabulário, então `CEX_SANDBOX=ture` caía no `else` implícito
   e o bot operava com dinheiro real achando que estava em sandbox.
2. **O painel podia contradizer a ordem.** Com `CEX_SANDBOX=false` e
   `BINANCE_SANDBOX=true`, um helper enviava para sandbox e o resumo exibido ao
   operador dizia `false`.

## Arquitetura

`workspace/venues/sandbox.py` responde a pergunta uma vez; todo chamador
consome dali. O vocabulário e a coerção vêm de `workspace.config.get_bool`, que
recusa valor fora da lista em vez de tratá-lo como falso.

| Componente | Arquivo | Função |
|---|---|---|
| Resolvedor | `workspace/venues/sandbox.py` | `resolve_sandbox(kind, venue_id)` |
| Vocabulário | `workspace/config.py` | `get_bool`, `has_env` |
| CLI | `workspace/cli.py` | `_load_cex_sandbox`, `_load_pair_cex_sandbox`, Kraken, Hyperliquid |
| Resumo | `workspace/venues/config.py` | `venue_summary()["cex_sandbox"]` |
| Diagnóstico | `workspace/run.py` | `setup_check()` safe defaults |

## Precedência

Do mais forte para o mais fraco:

1. **env**, seguindo a cadeia da venue: `KRAKENFUTURES_SANDBOX` →
   `KRAKEN_SANDBOX` → `CEX_SANDBOX`
2. **`settings.local.json`**, mesma cadeia: `venues.cex.krakenfutures.sandbox`
   → `venues.cex.kraken.sandbox` → `venues.cex.sandbox`
3. **`settings.json`**, mesma cadeia
4. `venue_default` — derivado pelo chamador
5. default da venue

**Camada é o eixo externo; especificidade, o interno.** Ambiente vence arquivo,
`settings.local.json` vence `settings.json`, e dentro de cada camada o mais
específico vence o genérico. Isso preserva a precedência documentada em
[Configuração de setups](configuracao-de-setups.md).

A ordem foi errada duas vezes antes de assentar, sempre por misturar os eixos:
primeiro a varredura de arquivo colapsou camada e especificidade, e uma chave
por venue do arquivo do time derrubava uma chave genérica do arquivo do
operador; depois, ao tentar proteger o `venue_default`, ele foi posto acima da
chave genérica do tipo — reintroduzindo a mesma mistura, o que um teste vizinho
pegou.

### A cadeia de venue

`venue_chain` resolve família uma vez e a aplica **a env e a settings ao mesmo
tempo**: `krakenfutures` → `('krakenfutures', 'kraken')`. Na primeira versão a
família existia só para env, e `venues.cex.kraken.sandbox` no arquivo não
alcançava `krakenfutures` — que caía na chave genérica e ia para produção.
O casamento é por prefixo, então uma venue futura chamada `nadotrade` herdaria
de `nado`; é o preço de não manter uma tabela de variantes que envelhece a cada
exchange nova.

### `venue_default`

Fica **abaixo de toda config declarada**. Quem escreve a chave no arquivo está
declarando, não aceitando um default — mesmo tratamento que `DEX_SANDBOX`
sempre teve. O risco real era o `settings.example.json` distribuir
`venues.dex.sandbox: false` e derrubar o default de quem escolheu testnet; o
exemplo deixou de distribuir isso, e há teste de guarda.

## Defaults

Só a família `kraken` nasce apontada para sandbox. **Toda outra CEX nasce em
produção.** A assimetria é deliberada: a Kraken tem ambiente demo estável e
público (`demo.futures.kraken.com`), e as demais não têm equivalente confiável
— um default `true` genérico prometeria uma proteção que a corretora não
entrega.

A Hyperliquid deriva o default da rede selecionada: `testnet` implica sandbox.

## Configuração

```jsonc
// settings.json — a chave da família vale para todas as variantes
{
  "venues": {
    "cex": { "kraken": { "sandbox": true } }
  }
}
```

Evite declarar `venues.<tipo>.sandbox` sem precisar: a chave genérica vence o
default da venue e o `venue_default`, mandando para produção quem contava com
eles.

As variáveis `CEX_SANDBOX`, `KRAKEN_SANDBOX` e `HYPERLIQUID_SANDBOX` vêm
**comentadas** no `workspace/.env.example`. Elas continuam funcionando, mas têm
precedência sobre o arquivo: deixá-las ativas no exemplo tornava o settings
inoperante para quem copiasse — foi o que aconteceu com as `TRIANGLE_*` na
fatia anterior desta fase. Um teste de guarda impede a regressão.

## Comportamento em erro

Valor fora do vocabulário levanta `ConfigError` e **derruba o comando**, porque
o custo de adivinhar aqui é uma ordem com dinheiro real. Os dois comandos de
diagnóstico são exceção deliberada, já que são rodados justamente quando algo
está errado:

- `setup-check` reporta a mensagem no campo `venues_error` e segue produzindo o
  relatório.
- `venues` termina com a mensagem de erro, não com traceback.

## Nome de variável

O prefixo da venue colapsa qualquer pontuação em `_`. Um dos helpers antigos
fazia apenas `.upper().replace('-', '_')`, o que para `binance.us` produzia
`BINANCE.US_SANDBOX` — nome que nenhum shell exporta, deixando a variável
específica inalcançável sem que nada avisasse.

## Changelog

| Data | Mudança |
|------|---------|
| 14/09/2026 | Documento inicial: resolvedor único, precedência e defaults |
| 14/09/2026 | Cadeia de venue aplicada também às chaves de settings; camada vira eixo externo; `venue_default` abaixo da config declarada |
