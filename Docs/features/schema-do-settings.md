# Schema do settings

> Última atualização: 22 de setembro de 2026
> Versão: 1.0.0

## Visão geral

Um typo no *nome* de uma chave do `settings.json` não produzia erro nenhum. A
chave simplesmente não era lida, o código caía no default, e o operador via o
comando rodar achando que a configuração dele valia. Medido antes da correção:

| Declarado | Efetivo | |
|---|---|---|
| `venues.cex.binance.sandbxo: true` | `False` | **produção** |
| `venues.cex.binanse.sandbox: true` | `False` | **produção** |
| `venues.cexs.kraken.sandbox: false` | `True` | |
| `setups.triangle-breakout.pivot_windwo: 9` | `2` (o default) | |

`validate_setup_settings` — que existe justamente para o erro aparecer no boot
— passava por todos. Ela valida os **valores** das chaves que conhece, e um
typo produz uma chave que ela não conhece.

Isto é a contrapartida de [Sandbox por venue](sandbox-por-venue.md): passar a
instruir o operador a escrever `venues.cex.binance.sandbox` num arquivo, sem
nada conferir o que ele escreveu, troca um modo de falha silenciosa por outro.

## Arquitetura

| Componente | Arquivo | Função |
|---|---|---|
| Vocabulário | `settings.schema.json` | os nomes aceitos, como **dado** |
| Caminhador | `workspace/settings_schema.py` | `validar_settings`, `exigir_settings_valido` |
| Boot | `workspace/core/setups.py` | `validate_setup_settings` derruba o comando |
| Diagnóstico | `workspace/run.py` | campo `settings_error` e check `settings_schema` |

### Por que não `jsonschema`

O vocabulário é pequeno e o valor da validação está quase todo na **mensagem**:
apontar a chave, o caminho e a grafia provável. Uma dependência nova no
`requirements.txt` teria custo de supply-chain para entregar uma mensagem pior.
O schema continua sendo dado legível pelo operador; só o caminhador é código.

### Formato do schema

Cada nó tem quatro campos, todos opcionais:

| Campo | Significado |
|---|---|
| `campos` | chaves escalares aceitas neste nível |
| `filhos` | sub-objetos de nome fixo |
| `padroes` | sub-objetos cujo nome casa uma regex |
| `livre` | qualquer outro nome é sub-objeto; `dominio` diz contra o que validar o nome |

`_comentario*` é aceito em qualquer nível — é como o `settings.example.json`
documenta a si mesmo.

`padroes` existe por causa do divergence: a chave dele é gerada com sufixo de
timeframe (`divergence-and-volume-4h`), e sem sufixo para o backtest, que não
passa timeframe.

`livre` existe por causa das venues: o id é aberto por natureza, mas o nível da
folha (`sandbox`) continua fechado.

## Decisões

### A lista de parâmetros é por setup

Uma lista única aceitaria `setups.funding-arb.pivot_window`. O parâmetro
existe — só não nesse setup —, e a chave ficaria morta do mesmo jeito. Esse é
um erro mais provável que o typo de digitação: quem calibra dois setups copia o
bloco de um para o outro.

### Id de CEX é fechado; de DEX, aberto

`ccxt.exchanges` é a fonte da verdade para a CEX genérica: id fora dessa lista
não constrói adapter nenhum, então a chave estaria morta de qualquer forma — e
a venue cairia no default, que fora da família `kraken` é produção. Mais as
variantes internas (`kraken-spot`, `krakenfutures`, `hyperliquid-dex`), que são
seleções nossas e não existem no CCXT.

O DEX fica aberto **de propósito**: `DEX_ADAPTER_MODULE` permite adapter
próprio, e o id dele é do operador. Fechar ali recusaria configuração legítima,
que é a direção cara do erro.

### O schema não segue `config.REPO_ROOT`

`REPO_ROOT` aponta para onde o settings do **operador** é procurado, e a suíte
a redireciona para um diretório falso. O schema viaja com o código, então
`SCHEMA_PATH` sai de `__file__`.

Amarrado ao `REPO_ROOT`, ele passava na suíte só por acidente de ordem de
import — e sumia assim que alguém importasse o módulo depois do patch,
derrubando o `setup_check` inteiro com traceback.

## Comportamento em erro

Chave desconhecida **derruba o comando** no boot (`validate_setup_settings`) e
marca `attention` no `doctor`. O check `settings_schema` está em
`BLOCKING_CHECKS`: `doctor` devolvendo `ok` com config morta é o mesmo defeito
que o corte `checks[:4]` produziu com o `venues_config`.

`setup-check` e `venues` continuam sobrevivendo a schema ausente ou ilegível —
eles são rodados justamente quando algo está errado, e trocar o relatório
inteiro por um traceback é o oposto do que se quer ali.

## A direção perigosa

O risco desta feature não é deixar passar um typo — é **recusar configuração
legítima**. Um schema incompleto derruba o boot de quem seguiu a documentação,
trocando uma falha silenciosa por uma barulhenta e errada. Duas defesas na
suíte:

1. `settings.example.json` tem que passar pelo schema.
2. Um espião em `Settings._require` registra toda chave que os getters de setup
   pedem, e o teste exige que o schema aceite cada uma. Se o código passar a
   ler `setups.X.novo_campo` e ninguém tocar no schema, a suíte falha **antes**
   de o operador descobrir pelo boot.

## Migração

Se você mantinha chaves próprias no arquivo — anotação, campo de outra
ferramenta, resto de experimento —, prefixe com `_comentario` ou remova. O boot
vai nomeá-las uma a uma.

## Changelog

| Data | Mudança |
|------|---------|
| 22/09/2026 | Documento inicial: schema como dado, lista por setup, id de CEX fechado, e as duas defesas contra o schema incompleto |
