# Configuração de setups

**Versão:** 1.0.0 · **Última atualização:** 14/09/2026

Parâmetros de setup são configuráveis por arquivo, sem editar código.

## Onde configurar

| Camada | Arquivo | Versionado? | Para quê |
|---|---|---|---|
| 1 (vence) | variável de ambiente | — | override pontual, CI, emergência |
| 2 | `settings.local.json` | não (gitignored) | calibração da máquina do operador |
| 3 | `settings.json` | sim | o que vale para o time |
| 4 | default do código | sim | fallback |

`settings.local.json` é procurado em `$DELTA_NEUTRAL_SETTINGS_DIR`, depois
`~/.config/openclaw/trade-automatizado-openclaw/`, e por último na raiz do
repositório. As duas primeiras ficam fora da árvore porque a skill é
reinstalada por cima do próprio diretório.

Ponto de atenção: **a variável de ambiente vence o arquivo.** Se você definir
`setups.triangle-breakout.pivot_window` no settings e tiver
`TRIANGLE_PIVOT_WINDOW` no ambiente, o ambiente ganha. O boot emite um
`WARNING` listando exatamente quais chaves foram encobertas — se o settings
"não está funcionando", olhe esse log primeiro.

## Formato

Ver `settings.example.json` na raiz. A estrutura é `setups.<chave>.<parâmetro>`:

```json
{ "setups": { "funding-arb": { "min_rate": 0.0005, "max_hold_hours": 24 } } }
```

Chaves de setup: `triangle-breakout`, `funding-arb`,
`divergence-and-volume-15m`, `divergence-and-volume-1h`,
`divergence-and-volume-4h`.

## Calibração por timeframe

As variáveis de ambiente do `divergence-and-volume` são únicas para os três
timeframes: um `DIVERGENCE_AND_VOLUME_RSI_PERIOD` vale para 15m, 1h e 4h ao
mesmo tempo. Pelo settings, cada timeframe tem a sua chave — dá para calibrar o
4h sem tocar nos outros dois.

## Parâmetros que só o settings alcança

`fibonacci_levels`, `target_levels` e `target_weights` não têm variável de
ambiente. Eles decidem **onde o capital sai da posição**, e antes disso só
mudavam editando o código.

`target_levels` e `target_weights` precisam ter o mesmo tamanho, e a lista de
alvos não pode ser vazia — as duas condições são recusadas no boot, com a chave
nomeada.

## Validação

Valor inválido derruba o comando no boot, antes do primeiro ciclo. Isso é
deliberado: dentro do loop de scan a exceção seria capturada como `WARNING` e o
bot ficaria de pé sem abrir nada.

## Segredos

Segredo nunca entra no settings. O arquivo declara apenas o *nome* da variável
de ambiente: `{"env": ["KRAKEN_API_KEY", "CEX_API_KEY"]}`. Valor literal é
recusado — `settings.json` é versionado.

## Changelog

| Data | Mudança |
|------|---------|
| 14/09/2026 | Documento inicial: `settings.json`, precedência e parâmetros por setup (PRs #7 e #9) |
| 24/09/2026 | Seção de changelog adicionada |
