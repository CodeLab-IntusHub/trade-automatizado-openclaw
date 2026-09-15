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
| CLI | `workspace/cli.py` | `_load_cex_sandbox`, `_load_pair_cex_sandbox`, Kraken, `_hyperliquid_sandbox` |
| Resumo | `workspace/venues/config.py` | `venue_summary()["cex_sandbox"]` |
| Diagnóstico | `workspace/run.py` | guarda de `ConfigError` no `setup_check()` |

## Precedência

Do mais forte para o mais fraco:

1. **env**, seguindo a cadeia da venue: `KRAKENFUTURES_SANDBOX` →
   `KRAKEN_SANDBOX` → `CEX_SANDBOX`
2. **`env_default`** — valor que o chamador derivou de *outra variável de
   ambiente* da mesma venue
3. **`settings.local.json`**, mesma cadeia: `venues.cex.krakenfutures.sandbox`
   → `venues.cex.kraken.sandbox` → `venues.cex.sandbox`
4. **`settings.json`**, mesma cadeia
5. default da venue

**Camada é o eixo externo; especificidade, o interno.** Ambiente vence arquivo,
`settings.local.json` vence `settings.json`, e dentro de cada camada o mais
específico vence o genérico. Isso preserva a precedência documentada em
[Configuração de setups](configuracao-de-setups.md).

Quando uma chave de camada mais forte é **menos** específica que outra
declarada — o caso de um `venues.cex.sandbox: false` no arquivo do operador
engolindo um `venues.cex.kraken.sandbox: true` do time — a ordem continua
valendo, mas sai um `WARNING` nomeando as duas chaves. Perder uma declaração de
segurança em silêncio é o defeito que este módulo existe para remover.

O aviso só sai quando os dois valores **divergem**. Avisar com as duas chaves
declarando o mesmo não relata perda nenhuma e, num aviso de segurança, treina o
operador a ignorá-lo.

### A cadeia de venue

`venue_chain` resolve família uma vez e a aplica **a env e a settings ao mesmo
tempo**: `krakenfutures` → `('krakenfutures', 'kraken')`. Na primeira versão a
família existia só para env, e `venues.cex.kraken.sandbox` no arquivo não
alcançava `krakenfutures` — que caía na chave genérica e ia para produção.
O casamento é por prefixo, então uma venue futura chamada `krakenx` herdaria de
`kraken`; é o preço de não manter uma tabela de variantes que envelhece a cada
exchange nova.

### `env_default`: a rede da Hyperliquid

Está na **camada de ambiente**, porque é exatamente isso que ele é: a
Hyperliquid deriva sandbox de `HYPERLIQUID_NETWORK`/`DEX_NETWORK`, onde
`testnet` implica sandbox. Fica abaixo das envs de sandbox explícitas, que
respondem à pergunta diretamente, e acima de qualquer arquivo.

A posição foi errada duas vezes antes de assentar, e o nome foi a causa das
duas: chamado de `venue_default`, primeiro ficou acima apenas da chave genérica
do tipo (misturando os eixos que o resto do módulo separa) e depois abaixo de
toda configuração de arquivo — e aí um `venues.dex.sandbox: false` derrubava uma
rede declarada por variável de ambiente.

**Quem passa `env_default` deve passar `None` quando a env não foi declarada.**
Uma expressão como `network in {"testnet", ...}` é sempre um `bool`: injetar
esse `False` incondicional coloca na camada de ambiente um valor que ninguém
escreveu, e ele derruba todo o arquivo. Como a Hyperliquid é o único DEX que
chama o resolvedor, isso tornava `venues.dex.*.sandbox` configuração morta.

### A rede declarada não sobrevive ao construtor

`HyperliquidDexTrader.__init__` faz `self.network = "testnet" if self.sandbox
else "mainnet"` — quem manda é o `sandbox`, e a rede declarada é descartada.

Enquanto `HYPERLIQUID_SANDBOX=false` vinha **ativo** no `.env.example` ao lado
de `HYPERLIQUID_NETWORK`, trocar só a rede para `testnet` deixava o operador na
mainnet sem nada dizer. A variável saiu do exemplo, e a contradição passou a
emitir um `WARNING` que nomeia as duas pontas e diz onde a ordem vai cair. A
precedência não mudou: a env explícita continua vencendo.

### Nado fora das famílias

`nado` não entra na lista de famílias porque nenhuma variante dela precisa
herdar: o adapter da Nado é construído só a partir de `NADO_NETWORK` e **nunca
chama este resolvedor**.

Isso não quer dizer que `NADO_SANDBOX` deixe de ser gerado — para o id `nado` a
cadeia produz o nome como para qualquer venue. Quer dizer que nada o consulta.
Quem for ligar a Nado ao resolvedor precisa passar por aqui primeiro.

## Defaults

Só a família `kraken` nasce apontada para sandbox. **Toda outra CEX nasce em
produção.** A assimetria é deliberada: a Kraken tem ambiente demo estável e
público (`demo.futures.kraken.com`), e as demais não têm equivalente confiável
— um default `true` genérico prometeria uma proteção que a corretora não
entrega.

A Hyperliquid deriva o default da rede selecionada: `testnet` implica sandbox,
por `env_default` — ver a seção acima.

## Configuração

```jsonc
// settings.json — a chave da família vale para todas as variantes
{
  "venues": {
    "cex": { "kraken": { "sandbox": true } }
  }
}
```

Evite declarar `venues.<tipo>.sandbox` sem precisar. Ela vence o default da
venue e também qualquer chave mais específica que esteja numa camada mais
fraca — mandando para produção quem contava com elas. Nesse segundo caso sai um
`WARNING`; no primeiro, não há o que avisar, porque nada foi declarado do outro
lado.

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
  relatório; o campo `cex_sandbox` vira `null`, porque chutar `"false"` ali
  seria um palpite na direção do dinheiro.
- `venues` termina com a mensagem de erro, não com traceback.

## Limitações conhecidas

- **`resolve_sandbox` recarrega os arquivos a cada pergunta.** Ele está no
  caminho de construção de ordem, então o mesmo run pode ler os arquivos várias
  vezes — e, se o settings mudar no meio, duas pernas podem enxergar valores
  diferentes. Quem já tem um `Settings` carregado deve passá-lo pelo parâmetro
  `settings=`; um cache por processo resolveria o resto.
- **As chaves por venue aceitam hífen e underscore** (`venues.cex.kraken-futures`
  e `venues.cex.kraken_futures` alcançam a mesma venue, em qualquer sentido). A
  grafia escrita no `CEX_ID` é consultada primeiro; as duas formas compartilham
  o mesmo nível de especificidade, então declarar as duas com valores opostos é
  ambíguo — não faça.

## Nome de variável

O prefixo da venue colapsa qualquer pontuação em `_`. Um dos helpers antigos
fazia apenas `.upper().replace('-', '_')`, o que para `binance.us` produzia
`BINANCE.US_SANDBOX` — nome que nenhum shell exporta, deixando a variável
específica inalcançável sem que nada avisasse.

## Changelog

| Data | Mudança |
|------|---------|
| 14/09/2026 | Documento inicial: resolvedor único, cadeia de venue, precedência com camada como eixo externo, defaults e avisos |
| 15/09/2026 | Hyperliquid migrada: `env_default` na camada de ambiente e aviso quando a rede declarada contradiz o sandbox |
| 15/09/2026 | Especificidade vem da cadeia da venue (e não do índice da lista); as duas grafias resolvem nos dois sentidos |
