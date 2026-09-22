# Vocabulário de booleanos

> Última atualização: 22 de setembro de 2026
> Versão: 1.0.0

## Visão geral

Um portão booleano mal lido não falha: ele responde. A pergunta é para que
lado. Até esta versão o projeto tinha **quatro cópias** do mesmo vocabulário, e
todas declaravam só o lado verdadeiro:

```python
return raw.lower() in {"1", "true", "yes", "sim"}
```

Tudo o que não estivesse na lista caía no `else` implícito e virava `False`. Em
`sandbox`, `False` significa dinheiro real — foi o defeito que originou a
[refatoração do sandbox](sandbox-por-venue.md). Em
`NADO_REQUIRE_LINKED_SIGNER`, cujo default é `True`, é pior: ali `False`
**desliga uma proteção**, e não há nem o consolo de o default ser o lado
seguro.

Medido antes da correção, com o portão valendo `True` por default:

| Valor | Resolvia | |
|---|---|---|
| `ture` | `False` | proteção desligada |
| `tru` | `False` | proteção desligada |
| `verdadeiro` | `False` | proteção desligada |
| `on` | `False` | proteção desligada |
| `s` | `False` | proteção desligada |
| `y` | `False` | proteção desligada |
| `TRUE`, `sim`, `1` | `True` | |

`on`, `s` e `y` são o caso que mais incomoda: eles são **válidos** no
vocabulário que o `sandbox` usa. Quem aprendeu a escrever `CEX_SANDBOX=on`
escrevia `NADO_REQUIRE_LINKED_SIGNER=on` e desligava a verificação de linked
signer sem nada dizer.

## Arquitetura

`workspace.config.coerce_bool(value, origem)` é a única definição. Foi extraída
de `Settings.get_bool`, que agora delega para ela — o ponto era justamente não
ter duas.

| Leitor | Arquivo | Portões |
|---|---|---|
| `Settings.get_bool` | `workspace/config.py` | tudo que vem de settings/env pela fonte única |
| `_load_bool_env` | `workspace/cli.py` | os 8 portões lidos direto do ambiente |
| `_env_bool` | `workspace/nado/auto_trade_nado.py` | `NADO_REQUIRE_LINKED_SIGNER`, confirmação live |
| `_env_bool` | `workspace/nado/example.py` | idem |
| `_to_bool` | `workspace/venues/hyperliquid_dex.py` | `sandbox`, `load_markets` do payload |

`origem` é a chave pontilhada ou o nome da variável de ambiente: quem lê a
mensagem precisa reconhecer o que ele mesmo escreveu. Passar a chave de arquivo
quando o operador declarou uma env manda ele mexer no lugar errado.

## Vocabulário

| Verdadeiro | Falso |
|---|---|
| `1`, `true`, `yes`, `sim`, `on`, `y`, `s` | `0`, `false`, `no`, `nao`, `não`, `off`, `n` |

Não diferencia maiúsculas e ignora espaço em volta.

## Os oito portões

| Variável | Default | O que o typo fazia |
|---|---|---|
| `NADO_REQUIRE_LINKED_SIGNER` | `True` | **desligava a proteção** |
| `KRAKEN_REQUIRE_SUBACCOUNT` | `False` | deixava de exigir subconta |
| `KRAKEN_API_IS_SUBACCOUNT` | `False` | direção benigna |
| `KRAKEN_ALLOW_MAIN_ACCOUNT` | `False` | direção benigna |
| `NADO_ALLOW_OWNER_FALLBACK` | `False` | direção benigna |
| `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK` | `False` | direção benigna |
| `SETUP_NOTIFY_MONITORED_ON_START` | `False` | direção benigna |
| `SETUP_NOTIFY_MONITORED_FORCE` | `False` | direção benigna |

Onde o default é `False`, o valor não reconhecido coincide com o default e o
efeito é só o operador não conseguir ligar o que queria. Onde é `True`, ele
**inverte** o portão — por isso a lista está ordenada por consequência, e não
por nome.

## Comportamento em erro

Valor fora do vocabulário levanta `ConfigError` e derruba o comando.
`ConfigError` é um `RuntimeError`, e `cli.main` trata `RuntimeError` como
mensagem de erro com `exit 1` — o operador vê o texto, não um traceback.

**Ausente ou vazio devolve o default.** Não declarar continua sendo diferente
de declarar errado; sem essa distinção, todo portão viraria obrigatório.
Comentário inline (`KRAKEN_ALLOW_MAIN_ACCOUNT=false  # legado`) é cortado por
`_clean_literal_env` antes da leitura, então continua funcionando — há teste
para isso, porque perdê-lo transformaria uma linha do `.env.example` em erro de
boot.

## Limitação conhecida

Restam cerca de 20 leituras booleanas inline nos módulos de notificação e de
renderização (`SETUP_NOTIFY_*`, `SETUP_NOTIFY_TRADINGVIEW_*`) com o mesmo
`else` implícito. Ficaram de fora **de propósito**: todas têm default `False` e
ligam funcionalidade, então o typo desliga o que o operador queria ligar — sem
direção de dinheiro nem de proteção. Migrá-las é limpeza, e limpeza no mesmo
commit de uma correção de segurança só dificulta a revisão.

## Changelog

| Data | Mudança |
|------|---------|
| 22/09/2026 | Documento inicial: `coerce_bool` como definição única, os oito portões e o que ficou de fora |
