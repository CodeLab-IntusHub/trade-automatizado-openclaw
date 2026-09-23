# config-export

> Última atualização: 22 de setembro de 2026
> Versão: 1.0.0

## Visão geral

Emite o `settings.json` equivalente ao ambiente atual.

A migração de variável de ambiente para arquivo é incremental por desenho, e
isso cria um degrau ruim para quem já opera: o operador tem dezenas de
variáveis no `.env`, a documentação fala em `settings.json`, e o caminho entre
as duas coisas era transcrever à mão — lendo o código para descobrir qual chave
corresponde a qual variável.

```bash
python workspace/run.py config-export > settings.json
```

O JSON vai para a **stdout** e os avisos para a **stderr**, para o
redirecionamento acima produzir um arquivo válido. Aviso misturado no stdout
transformaria o redirecionamento num arquivo quebrado, e o operador só
descobriria no boot seguinte.

## O que ele não pode fazer é parecer completo

Esta é a restrição que define o desenho. Só parte das variáveis tem equivalente
em settings hoje; um arquivo que aparentasse substituir o `.env` levaria o
operador a apagar o `.env` e **perder credencial**.

Saem três avisos, e nenhum é decorativo:

| Aviso | Por quê |
|---|---|
| **Não substitui o `.env`** | incondicional; é o que impede o dano maior |
| **Continuam vencendo o arquivo** | ambiente vence arquivo por desenho, então exportar não muda nada enquanto a variável existir |
| **Segredos definidos** | pelo nome, nunca pelo valor; para o operador saber que a credencial fica onde está |

O segundo merece ênfase: quem exporta, mantém o `.env` e não vê mudança
nenhuma conclui que settings não funciona. É o mesmo mal-entendido que motivou
o aviso de origem no boot dos setups.

## Arquitetura

| Componente | Arquivo | Função |
|---|---|---|
| Export | `workspace/config_export.py` | `exportar`, `formatar_relatorio` |
| Comando | `workspace/run.py` | `config-export` |

### De onde saem as chaves

Do próprio código, não de uma lista paralela. Os getters de `Settings` são
espionados enquanto `validate_setup_settings` roda — ela já exercita todos, é o
que ela existe para fazer —, então a colheita acompanha o código sozinha. Uma
lista mantida à mão divergiria na primeira chave nova, e divergiria em
silêncio: emitindo um arquivo que descreve uma configuração que ninguém lê.

A costura são os **getters**, não `_require`. Espionar `_require` devolvia o
valor cru (a string `"7"`, não o int `7`) e capturava as sondagens de presença:
`setups.py` chama o getter com um sentinela próprio como `default` para
distinguir "ausente" de "declarado", e `_require` devolve esse sentinela.

O sandbox das venues não passa por esses getters, então vem do mesmo
`resolve_sandbox` que a ordem usa. Obtê-lo de outro jeito devolveria o problema
que [Sandbox por venue](sandbox-por-venue.md) acabou de fechar: duas respostas
para a mesma pergunta.

### De onde saem os nomes de variável

União de `skill.json` (`dependencies.env`, 115 nomes) com o
`workspace/.env.example` (106). **Nenhum dos dois é completo sozinho** —
`VOLUME_ORDER` está só no exemplo, variáveis de diagnóstico estão só no
manifesto. Sub-reportar aqui é a direção cara: o operador conclui que cobriu
tudo e apaga o `.env`.

É lista versionada, não varredura do ambiente. Sem ela o relatório listaria
`PATH`, `HOME` e o resto do shell como "sem equivalente em settings" — o que é
verdade e é inútil.

### Duas regras de montagem

**A primeira leitura de cada chave vence.** O preenchimento é last-wins por
natureza, e a mesma chave pode ser lida duas vezes na mesma execução (leitura
real + sondagem de presença). Medido: sem essa regra, a sondagem sobrescrevia o
valor lido do ambiente.

**Só o que o JSON representa entra.** A saída vira arquivo; valor não
serializável quebraria o comando na hora de imprimir, e o operador ficaria sem
export nenhum.

As duas vivem em `_montar`, que é função pura — no coletor, o defeito de
removê-las só apareceria se existisse uma chave apenas sondada, condição que
hoje não ocorre. Uma mutação que as removia de lá era invisível.

### Lista numérica sai numérica

`get_list` devolve `[str(item)]` por contrato, então a escada de alvos saía
como `["1.0", "1.5"]` onde o `settings.example.json` traz `[1.0, 1.5]`. O
produto deste comando é um arquivo feito para uma pessoa ler e editar; emitir
um dialeto diferente do exemplo que documentamos convida a editar errado.

A conversão é segura porque `get_list` re-stringifica na leitura — há teste de
round-trip. E vale para a lista **inteira** ou para nenhuma: converter item a
item produziria uma lista mista, pior que qualquer um dos dois lados.

## Segredo

Nunca sai. A garantia não é uma filtragem da saída: é que as únicas chaves
emitidas são as que o `Settings` lê, e segredo nunca é lido de settings — o
arquivo declara só o *nome* da variável.

A filtragem por `SECRET_ENV` existe no relatório, que é outra coisa: lá o nome
aparece, o valor não. Há teste que planta um valor conhecido em cada nome de
`SECRET_ENV` e falha se ele aparecer em qualquer parte da saída.

## Verificação

A saída passa pelo [schema do settings](schema-do-settings.md) — há teste. Um
export que o próprio validador recusa derrubaria o boot de quem o usou, que é
pior que não ter export.

O teste que de fato prova o comando é o **round-trip**: exporta com o ambiente
cheio, grava o resultado, limpa as variáveis e confere que o arquivo sozinho
produz os mesmos valores efetivos. Há um para escalares e um para o
`divergence-and-volume`, cuja escada de alvos é invariante do tipo — o primeiro
round-trip cobria só escalares, e foi por isso que a lista numérica passou
batida.

## Limitações conhecidas

- **Cobre apenas o que já tem equivalente em settings**: `venues.*.sandbox` e
  os parâmetros de setup. As demais variáveis continuam só no ambiente, e o
  relatório as lista.
- O relatório se baseia em **nomes declarados** no repositório. Variável lida
  pelo código e ausente dos dois arquivos não aparece como "sem equivalente".

## Changelog

| Data | Mudança |
|------|---------|
| 22/09/2026 | Documento inicial: comando, os três avisos, a colheita pelos getters e as regras de montagem |
