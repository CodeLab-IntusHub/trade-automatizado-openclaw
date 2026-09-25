# Changelog

## Nao publicado

### Mudanca de comportamento (atencao ao atualizar)

- **Nao ha mais modo de execucao padrao.** `abrir` sem `EXECUTION_MODE`/`--execution-mode` virava `hedged` e abria as duas pernas; agora para com uma mensagem que sugere os modos compativeis com as venues escolhidas (`hedged` so aparece com DEX e CEX). O modo nao e deduzido pelo que tem credencial: acrescentar uma chave mudaria o modo sozinho no ciclo seguinte. Leitura e diagnostico seguem sem modo; o `setup-live` real direcional ja exigia modo. O `.env.example` traz `EXECUTION_MODE` em branco, e o relatorio do `setup-check` mostra o modo vazio em vez de `hedged`.
- **Nao ha mais venue padrao.** `DEX_ID` ausente deixava de ser `nado`, e `CEX_ID` ausente deixava de ser `kraken`: cada operador escolhe onde opera. Quem nunca definiu essas variaveis e contava com o Nado/Kraken implicito passa a receber, no primeiro comando de mercado, uma mensagem dizendo qual venue escolher -- nenhum bot opera numa venue que o operador nao escolheu. O `doctor` ganha o check bloqueante `venue_escolhida` e so cobra credencial da venue escolhida; o wizard perde o par sugerido; o `.env.example` traz `DEX_ID` e `CEX_ID` em branco. Quem opera so CEX segue com a DEX substituida por um stub que recusa operar. **Quem opera so DEX ainda precisa de `CEX_ID`**, sem credencial: hoje os candles e o universo de simbolos vem da CEX em todos os modos, e o motor recusa subir sem ela -- um stub no lugar deixava o `setup-live` falhar em silencio a cada ciclo, sem gerir TP/SL de posicao aberta.
- O badge da imagem gerada pelo `render_trade_chart.js` passa a mostrar `SETUP_NOTIFY_BRAND`, e nao mais o texto fixo `INTUSCRIPTO`. Com a variavel vazia ou ausente, a imagem sai **sem badge** -- a mesma regra que o texto do sinal ja seguia. Quem usa o `.env.example` nao percebe diferenca: ele traz `SETUP_NOTIFY_BRAND=INTUSCRIPTO`.

### Adicionado

- `doctor` ganha o check `modo_execucao` (nao bloqueante): avisa modo nao escolhido e modo incompativel com as venues escolhidas, sugerindo os compativeis.

### Corrigido

- **O dashboard nao derruba mais o publisher quando falta config de venue.** `build_engine` sinaliza config faltando com `SystemExit`, que nao e `Exception`, e a sincronizacao de exposicao so pegava `Exception` -- um operador so-CEX com o default antigo `nado` e sem chave da Nado ja caia nisso. A sincronizacao agora exige so as venues escolhidas e registra o erro no painel.
- **O badge do renderer le a marca da configuracao** (ROADMAP 0.2). A marca vai escapada para o HTML. O `html()` do renderer passa a ser exportado e o Playwright so e carregado no modo de linha de comando, o que permite testar o badge com `node`, sem navegador: um teste prova que a marca configurada aparece no HTML fotografado, que marca vazia nao gera badge, e que nenhuma marca fica escrita no renderer.

### Documentacao

- **`doc referencia/` volta a valer** (ROADMAP 0.3). Congelada na v1.2.0 e linkada pelo `INSTALL.md`, a pasta tratava a subconta Kraken como obrigatoria -- "novas entradas so podem rodar com `KRAKEN_API_IS_SUBACCOUNT=true`" -- quando o codigo so exige isso com `KRAKEN_REQUIRE_SUBACCOUNT=true`, que e opcional e desligado por padrao. `01` e `04` passam a separar o padrao da validacao estrita, e `00`, `01`, `03` e `04` passam a dizer que, **sem** linked signer configurado, a Nado assina com a owner key -- o que o codigo faz desde antes; so o linked signer configurado e invalido bloqueia; o `02`, registro da migracao de 22/04/2026, vai para `doc referencia/historico/` com aviso de que nao descreve a configuracao atual; o indice tinha os links para `README`, `INSTALL` e `SKILL` quebrados. Um teste passa a travar os links da pasta e a exigir que o indice liste cada arquivo, e os docs vivos da pasta entram no guard que proibe declarar sandbox por env.

- **Inventario do `SKILL.md`** (ROADMAP 1.1), em `Docs/inventario-do-skill-md.md`: cada trecho classificado como regra geral, preferencia de instancia ou historico, com a linha de origem. Aponta as tres referencias a arquivos fora do pacote e duas contradicoes internas -- "embed nativo por padrao" contra "sem embed", e o fallback automatico para a owner key da Nado contra `NADO_REQUIRE_LINKED_SIGNER=true` (o codigo segue o primeiro: sem linked signer, assina com a owner key).

## v1.8.0 — 2026-09-24

Contrato do sinal fechado e pacote limpo. O registro estruturado de cada sinal
perde os campos de convivencia -- nada lia o outbox -- e passa a ter o conjunto
de chaves travado por teste; o `.skill` passa a conter so o que o git rastreia.
Do lado do plano, o repositorio vira satelite do repositorio de plataforma da
IntusHub, e o ecossistema passa a ser acessado por endpoints da plataforma (ADR
0006). As secoes do changelog seguem, a partir desta versao e retroativamente
ate a v1.5.0, uma ordem fixa: mudanca de comportamento primeiro.

### Mudanca de comportamento (atencao ao atualizar)

- O registro estruturado no outbox muda de forma: `schema` troca de valor, e `schema_canonico` e `raw_payload` deixam de existir. Nada le esse arquivo hoje; se voce passou a ler depois desta versao, leia pelos campos do topo.

### Alterado

- **Contrato do sinal fechado.** Confirmou-se que nada le o outbox local (`trading-signal-outbox.jsonl`), entao os campos de convivencia deixados pela v1.7.0 nao protegiam ninguem: `schema` passa a ser `intuscripto.trading.signal_call.v1`, e `schema_canonico` e `raw_payload` saem. Sem `raw_payload` nao sobra passagem direta do dicionario interno -- todo campo e montado explicitamente.
- **O conjunto exato de chaves do registro fica travado por teste**, por igualdade (nem a mais nem a menos), no topo e no `context`. A lista mora no teste, e nao no modulo: se vivesse no codigo, acrescentar um campo seria so acrescentar na lista, e o teste concordaria. Isso substitui `CAMPOS_PUBLICOS_DO_SINAL`, que so existia para filtrar o `raw_payload`.

### Corrigido

- **O pacote `.skill` passa a conter so o que o git rastreia.** `build.py` montava o pacote com `ROOT.rglob("*")` menos uma lista fixa de pastas -- o criterio era **o que esta no disco**, nao o que esta no repositorio. Medido numa maquina de desenvolvimento: de 239 arquivos que iriam no pacote, **104 estavam fora do git** -- 74 do `.ua/` (o grafo do codigo e o inventario de variaveis de ambiente de uma auditoria) e os caches do mypy e do ruff. Um `settings.local.json` deixado na raiz iria junto, para o bot de quem instalasse a skill. Agora o pacote sai do `git ls-files` (135 arquivos na mesma maquina), e fora de um repositorio git o build recusa em vez de adivinhar.
- `CLAUDE.md` fica fora do pacote: e instrucao de desenvolvimento do repositorio, descreve a organizacao, e nao pertence ao produto entregue.

### Documentacao

- **ROADMAP ganha o portao da Fase 3 e as etapas em ordem.** Nenhum passo do ecossistema comeca antes de: piso de cobertura com catraca, escritor atual do schema `trading` identificado, decisao da plataforma sobre onde vivem os dados de operadores externos, e `premortem`. Os passos viram etapas A-H com dependencias explicitas; a central de aprendizagem (3.9) passa a depender da telemetria.
- `PROGRESS.md` registra o conteudo do pacote e o lugar do produto na IntusHub (satelite, sem integracao com o banco ainda); o indice deixa de citar campos de legado do contrato do sinal, removidos na #28.
- **O repositorio passa a ser satelite do `intushub-core`**, o repositorio de plataforma da IntusHub. Novo `CLAUDE.md` com a posicao na constelacao: toda DDL, Edge Function e politica do banco compartilhado vive no planeta; aqui fica o cliente HTTP e o contrato do que a skill publica. Varredura de DDL e Edge Function: limpo.
- **ADR 0006 substitui o ADR 0004.** O ecossistema e acessado por Edge Functions da plataforma, e nao por uma conta Supabase Auth por bot com RLS -- o modelo do 0004 abriria um segundo caminho de acesso ao banco, paralelo ao da plataforma, e exigiria expor o schema `trading`.
- **ROADMAP, Fase 3:** o trabalho de banco e PR no planeta (expand no banco primeiro, contract no satelite depois); o passo 3.2 registra a primeira leitura do inventario e decide o acesso; novos passos 3.8 (compartilhamento de setups entre agentes, sobre o `settings` e o `config-export`) e 3.9 (central de aprendizagem dos agentes). Fases 4 e 5 passam a falar com as Edge Functions.

- O ecossistema passa a ter lugar definido: o schema Postgres `trading` que ja existe no Supabase da IntusHub, reformulavel por completo. O passo 3.2 do `Docs/ROADMAP.md` comeca por um **inventario** do que ha nele e de quem le ou escreve -- verificado no banco, nao presumido -- antes de qualquer migration destrutiva.

## v1.7.0 — 2026-09-24

Preparacao para virar produto. A marca passa a ser IntusCripto, o registro
estruturado de cada sinal -- o formato que o ecossistema vai publicar -- deixa
de levar o que nao deveria, e o plano do produto fica escrito (`Docs/ROADMAP.md`
e `Docs/decisions/`).

### Mudanca de comportamento (atencao ao atualizar)

- **O badge do grafico enviado ao Discord muda de `ASPIRA TRADE` para `INTUSCRIPTO`.** Ele e escrito no renderer, nao lido da configuracao, entao muda para todo mundo que atualizar -- inclusive quem mantem `SETUP_NOTIFY_BRAND` antigo no `.env`. O texto da mensagem, que le `SETUP_NOTIFY_BRAND`, so muda para quem trocar a variavel.
- **O registro estruturado do sinal no outbox (`trading-signal-outbox.jsonl`) mudou de forma.** `context.scanner_state_path` saiu; `raw_payload` passa a trazer so os campos de `CAMPOS_PUBLICOS_DO_SINAL`; entra `schema_canonico`. O campo `schema` **nao** mudou. Se algo le esse arquivo, confira se dependia do que saiu.
- O `bootstrap` passa a instalar o `setuptools` sem teto. Quem usa a Nado continua precisando do `requirements-nado.txt`, que agora traz o `setuptools<81` que o SDK exige.

### Alterado

- **Rebrand Aspira -> IntusCripto.** "Aspira" era o nome do OpenClaw onde esta skill foi desenvolvida; o produto hoje e IntusCripto. Renomeados: os 13 `.pine` (arquivo e nome do estudo), o `mapping.json`, o README e o checklist da pasta, os ids de DOM e globais do HTML gerado, o boundary MIME, os comentarios editoriais, e a marca exibida (`SETUP_NOTIFY_BRAND` e `SETUP_NOTIFY_DISCORD_EMBED_AUTHOR` no `.env.example`, mais o badge do `render_trade_chart.js`).
- **Tres superficies seguem com `aspira` de proposito**, porque espelham estado que vive fora deste repositorio e renomea-las trocaria uma inconsistencia cosmetica por uma quebra silenciosa:
  - **Caminhos de estado** (`~/.openclaw/state/aspira-trading-whatsapp-scanner*`): ja existem na maquina de quem opera. Renomear faz o scanner nao achar o estado anterior e recomecar do zero, sem erro nenhum. Nome de arquivo interno nao e superficie de marca.
  - **`pine_title`, `layout_name` e `tradingview_actual_layout_name`** do `tradingview-managed-layouts.json`: nomeiam layouts e estudos que existem na conta TradingView, e o renderer casa por string -- `tradingview_sandbox_render.js:145` derruba o render quando o `pine_title` nao esta no layout. Os `.pine` ja trazem o nome novo (valido a partir da proxima publicacao); ao republicar, atualizar o `pine_title` no mesmo commit. O acoplamento esta escrito no checklist.
  - **O campo `schema` do sinal**: e contrato de fio: vai para o outbox local, e nao foi confirmado se algo le esse arquivo casando por ele. O nome novo entra **ao lado**, em `schema_canonico`; o campo `schema` preserva `aspira.trading.signal_call.v1` para nao quebrar em silencio quem ja casa por ele. Inverter os dois e remover o legado quando o consumidor estiver conferido.
- Ha teste para as tres: sem eles nada na suite falharia se um proximo rebrand as arrastasse junto.
- **`setuptools<81` sai do `requirements.txt` base e vai para o `requirements-nado.txt`.** A restricao existe por causa do `eth-keyfile`, que ainda importa `pkg_resources` (removido no setuptools 81) e **so vem com o SDK da Nado**. No base ela limitava o `setuptools` de toda instalacao por uma dependencia que a maioria nao instala -- inclusive no `bootstrap`, que instalava `setuptools<81` para todo mundo. O `pip` reaplica a restricao quando o extra da Nado e instalado.
- **`python-dotenv` 1.0.1 -> 1.2.3.** O projeto usa apenas `load_dotenv`, a parte mais estavel da API; a suite passa integralmente com a versao nova, local e na CI (ubuntu x windows, 3.12 e 3.13).

### Corrigido

- **O payload do sinal deixa de emitir o caminho de arquivo do operador.** `context.scanner_state_path` carregava o caminho absoluto -- com o **nome de usuario da maquina** -- para dentro do registro estruturado do sinal, gravado no outbox local (`trading-signal-outbox.jsonl`) -- o que qualquer leitor desse arquivo recebe, e o que passaria a ir para o ecossistema de bots. A mensagem do Discord e o texto renderizado e nao carregava esse campo. Medido: o valor era o caminho completo do arquivo de estado dentro do diretorio pessoal do operador, comecando pela raiz de perfis do sistema e pelo nome da conta. E dado de diagnostico e pertence ao log local, nao ao sinal.
- **`raw_payload` deixa de ser passagem direta do dicionario interno.** Uma chave arbitraria plantada na entrada atravessava inteira para a saida. Nao e que houvesse segredo ali hoje -- e que nada impedia: a seguranca do campo dependia de ninguem nunca por nada sensivel no dict interno, o que nao e propriedade que alguem garanta. E congelava os internos no contrato, fazendo de toda mudanca interna uma quebra para quem consome. Agora ele carrega apenas os 14 campos declarados em `CAMPOS_PUBLICOS_DO_SINAL` -- que sao exatamente os que o produtor monta, e que ja saem como campo de primeira classe.
- **Um teste que consagrava a passagem direta foi corrigido.** `test_unified_signal_publication.py` afirmava `structured["raw_payload"] == signal`, isto e, exigia que o dict interno atravessasse inteiro.
- **Modo de stop por alvo irreconhecivel no estado deixa de desligar o trailing em silencio.** `_target_stop_mode_from_state` devolvia `off` para qualquer valor fora do vocabulario, sem dizer nada. `off` **nao** deixa a posicao sem stop -- o stop inicial continua onde foi colocado --, mas desliga a melhoria: com `breakeven_on_tp1` ou `ladder` o stop deveria subir depois de um alvo atingido, e passava a nao subir. O operador pede a melhoria e ela silenciosamente nao acontece. Dentro de uma mesma versao isso nao ocorre (o valor e normalizado na entrada do comando, que levanta); ocorre **entre versoes**, porque o arquivo de estado sobrevive ao upgrade e um alias removido apagaria o trailing de toda posicao aberta, e com estado editado a mao.
- Ele **continua** devolvendo `off` em vez de levantar, de proposito: o loop gerencia varias posicoes, e derruba-lo por causa do estado de uma so deixaria as outras sem gestao. `off` e a acao conservadora quando nao da para interpretar o valor; o que faltava era dizer que foi isso que aconteceu, nomeando o simbolo, o setup e o valor recusado.

### Documentacao

- **`Docs/ROADMAP.md`**: o plano do produto, passo a passo -- skill generica que qualquer bot OpenClaw instala, painel `localhost` do proprio bot, ecossistema no Supabase da IntusHub (publicacao de setups, analises, validacoes e noticias, com identidade e RLS por bot) e telemetria opt-in. Cada passo tem criterio de pronto.
- **`Docs/decisions/`**: cinco ADRs -- execucao descentralizada com ecossistema de dados compartilhado; Sentry nao se aplica a skill; painel como app local novo (proposta); identidade de bot via Supabase Auth (proposta); rebrand com superficies preservadas.
- **`Docs/features/contrato-do-sinal.md`**: o registro estruturado de cada sinal -- campos, fronteira publica e campos de legado. Documenta tambem que ele vai para o **outbox local**, e nao para o Discord, que recebe o texto renderizado.
- `Docs/features/protecao-de-ordens.md` ganha o modo de stop por alvo lido do estado.
- `RELEASE_NOTES.md` passa a ser rotulado como arquivo historico: ele parou na v1.1.22, mas guarda as versoes v1.1.0 a v1.1.16, que nao existem no `CHANGELOG`. Apaga-lo perderia historico.
- A arvore de estrutura do `README` foi atualizada; ela nao mostrava `Docs/`, `references/`, `settings.schema.json` nem `workspace/venues/`.
- **Correcao:** textos desta versao afirmavam que o payload do sinal "ja ia para um grupo". Nao ia: ele e gravado no outbox local; o grupo recebe o texto renderizado, sem esse payload. O vazamento de caminho corrigido existia -- chegava a qualquer leitor do outbox e chegaria ao ecossistema --, mas nao ao grupo.

### Nao coberto por esta versao

- `raw_payload` **continua existindo**, limitado, para nao quebrar quem ja le dele. Ele e redundante com os campos do topo e sai numa release futura, junto com a inversao do `schema`/`schema_canonico`, quando o consumidor estiver conferido -- uma confirmacao fecha as duas.
- O badge do `render_trade_chart.js` continua **hardcoded** em vez de ler `SETUP_NOTIFY_BRAND` -- contraria a regra de nao hardcodear config, mas ligar env naquele renderer e outra mudanca, com teste proprio.
- `OPENCLAW-SOURCE.md` e a regra anti-legado do `SKILL.md` mantem "Aspira": sao registro historico correto de proveniencia, nao marca em uso.

## v1.6.0 — 2026-09-23

Uma familia de defeitos, tres formas. Em todas elas um valor que o operador
escreveu era descartado em silencio e substituido por um default -- e em
todas elas o default decidia dinheiro ou protecao. O padrao e o mesmo do
`CEX_SANDBOX=ture` que abriu esta fase.

### Mudanca de comportamento (atencao ao atualizar)

Sao **duas**, e as duas na mesma direcao: valor irreconhecivel agora derruba o comando em vez de virar o default. Em ambos os casos, se voce tem hoje um valor fora do vocabulario, ele **ja nao estava valendo** -- a diferenca e que agora voce fica sabendo.

- **Percentual fora do vocabulario derruba o comando** em vez de cair no default. Ausente ou em branco continua caindo no default -- nao declarar segue sendo diferente de declarar errado. Confira `PROTECTIVE_STOP_LOSS_PCT`, `PROTECTIVE_TAKE_PROFIT_PCT`, `MAX_PAIR_LOSS_PCT` e `MARGIN_USD` no seu `.env`: se algum usa virgula decimal, ele **ja nao estava valendo** -- a diferenca e que agora voce fica sabendo.
- **Direcao fora do vocabulario derruba o comando** em vez de virar "sem filtro". Ausente ou em branco continua significando sem filtro. Se voce tem `UNIQUE_TREND` com um valor que nao seja `long`/`comprado`/`compra`/`short`/`vendido`/`venda`, ele **ja nao estava filtrando nada** -- a diferenca e que agora voce fica sabendo.

### Removido

- Os dois PRDs em HTML da raiz (`PRD.html` e `trade-automatizado-openclaw-prd.html`), copias byte a byte um do outro. Nenhum documento versionado os referenciava.

### Corrigido

- **Percentual de risco invalido deixa de virar o default em silencio.** `_pct_from_env` e `_notice_pct_from_env` faziam `except (TypeError, ValueError): return default`, e o que elas alimentam e **stop loss e take profit** (`PROTECTIVE_STOP_LOSS_PCT`, `MAX_PAIR_LOSS_PCT`, `SETUP_NOTIFY_STOP_LOSS_PCT`). Com `default=0.03`, medido: `2,5` virava `0.030` -- um stop 20% mais largo que o pretendido, calado. **A virgula decimal e a escrita natural em portugues**, entao este nao e um typo improvavel: e a forma como muita gente escreve numero. Mesmo formato de defeito do `CEX_SANDBOX=ture` e do `NADO_REQUIRE_LINKED_SIGNER=on`.
- **A mensagem diz o que corrigir.** Valor com virgula recebe `Use ponto como separador decimal (2.5), nao virgula` -- dizer so "valor invalido" devolveria o operador ao mesmo lugar, procurando o erro num numero que para ele esta certo. E ela nomeia **a variavel que de fato carregou o valor**, e nao a primeira da cadeia de quatro: citar a primeira mandaria mexer numa variavel que o operador nao definiu.
- **O scanner consome o mesmo parser.** `ccxt_entry_scanner._pct_from_env` tinha a sua propria copia, consultando exatamente as mesmas variaveis. Corrigir so o `cli` deixaria dois vereditos para a mesma pergunta -- o defeito de origem do sandbox.
- **`_load_optional_float_arg` nomeia a variavel.** Ele decide `MARGIN_USD`, o tamanho da posicao. Ja falhava fechado, mas com `ValueError` cru: traceback, sem dizer qual variavel da cadeia estava errada.
- **`UNIQUE_TREND` invalido deixa de apagar o filtro de direcao.** Ele restringe a direcao das entradas, e **string vazia significa sem filtro** -- e o que `decision.py:497` testa. O helper devolvia `""` para tudo que nao fosse exatamente `LONG` ou `SHORT`: medido, `LNOG`, `LONGO`, `comprado` e `LONG,SHORT` todos resolviam para vazio. O operador restringia a direcao e passava a operar **nos dois sentidos**, sem nada dizer. Aqui o vazio nao e a ausencia de um valor: e um valor com significado, entao resolver lixo para vazio nao era cair no default -- era apagar o que o operador escreveu.
- **`comprado` e `compra` passam a valer tambem na variavel de ambiente.** `_normalize_order_side_arg`, na mesma `cli.py`, ja as aceitava para o mesmo conceito: o projeto entendia a palavra no argumento e a descartava na env. As duas portas passaram a ler de `_DIRECOES`, uma definicao so -- foi a divergencia entre duas copias que criou o desencontro.
- **`CERTAINTY` nomeia a variavel.** O limiar que decide se a entrada acontece ja falhava fechado, mas com `ValueError` cru: traceback, sem dizer qual variavel nem o que se esperava dela. E `70,5` esbarrava na mesma virgula decimal dos percentuais.
- **As copias da Nado consomem os mesmos helpers.** `nado/auto_trade_nado.py` tinha a propria versao dos dois, lendo as mesmas variaveis -- dois vereditos para a mesma pergunta.
- **Um teste que consagrava o defeito foi corrigido.** `test_v2.py` afirmava `UNIQUE_TREND=true` -> `""`, ou seja, exigia que um valor que nao e direcao nenhuma apagasse a restricao em silencio.

### Nao coberto por esta versao

- Os `_to_float` dos adapters (`kraken_integration`, `ccxt_cex`, `hyperliquid_dex`) tambem caem no default em silencio, mas parseiam **resposta de corretora**, nao config do operador. Dado externo com default e outra decisao, e misturar as duas na mesma mudanca so dificultaria a revisao.

## v1.5.0 — 2026-09-22

### Mudanca de comportamento (atencao ao atualizar)

Esta versao tem **duas** mudancas que podem derrubar um comando que hoje roda. As duas sao na mesma direcao: valor que antes era adivinhado em silencio agora e recusado. Confira o seu `.env` e o seu `settings.json` antes de atualizar.

- **Chave desconhecida em `settings.json` ou `settings.local.json` derruba o comando** no boot e marca `attention` no `doctor`. Se voce mantinha chaves proprias no arquivo -- anotacao, campo de outra ferramenta, resto de experimento --, prefixe com `_comentario` (aceito em qualquer nivel) ou remova. A direcao cara desta mudanca e recusar config legitima, e ha duas defesas contra isso na suite: o `settings.example.json` tem que passar pelo schema, e um espiao em `Settings._require` registra toda chave que os getters de setup pedem e exige que o schema aceite cada uma.
- **Valor fora do vocabulario nos oito portoes agora derruba o comando** em vez de virar `False`. Ausente ou vazio continua devolvendo o default -- nao declarar segue sendo diferente de declarar errado --, e comentario inline (`false  # legado`) continua sendo cortado antes da leitura. Confira os valores de `NADO_REQUIRE_LINKED_SIGNER`, `KRAKEN_API_IS_SUBACCOUNT`, `KRAKEN_REQUIRE_SUBACCOUNT`, `KRAKEN_ALLOW_MAIN_ACCOUNT`, `NADO_ALLOW_OWNER_FALLBACK`, `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK`, `SETUP_NOTIFY_MONITORED_ON_START` e `SETUP_NOTIFY_MONITORED_FORCE` no seu `.env`: o vocabulario aceito e `1/true/yes/sim/on/y/s` e `0/false/no/nao/nao/off/n`. `ConfigError` e um `RuntimeError`, entao o comando termina com a mensagem, nao com traceback.

### Adicionado

- **`config-export`**: emite na stdout o `settings.json` equivalente ao ambiente atual, com os avisos na stderr -- `python workspace/run.py config-export > settings.json` produz um arquivo valido. A migracao de env para arquivo e incremental por desenho, e o caminho entre as duas coisas era transcrever a mao, lendo o codigo para descobrir qual chave corresponde a qual variavel.
- O comando **nao pode parecer completo**, e e isso que define o desenho dele. So parte das variaveis tem equivalente em settings hoje; um arquivo que aparentasse substituir o `.env` levaria o operador a apagar o `.env` e perder credencial. Saem tres avisos, nenhum decorativo: o que **nao tem equivalente** (uniao de `skill.json` com o `.env.example` -- nenhum dos dois e completo sozinho), o que **continua vencendo** o arquivo (exportar nao muda nada enquanto a variavel existir, porque ambiente vence arquivo por desenho) e os **segredos definidos**, pelo nome, nunca pelo valor.
- As chaves saem do proprio codigo: os getters de `Settings` sao espionados enquanto `validate_setup_settings` roda, entao a colheita acompanha o codigo sem lista paralela. O sandbox das venues vem do mesmo `resolve_sandbox` que a ordem usa -- emitir aqui um valor obtido de outro jeito devolveria o problema que esta fase acabou de fechar.
- A saida passa pelo `settings.schema.json` (ha teste): um export que o proprio validador recusa derrubaria o boot de quem o usou.

### Corrigido

- **Chave desconhecida no settings deixa de ser ignorada em silencio.** Um typo no *nome* de uma chave nao produzia erro nenhum: a chave nao era lida, o codigo caia no default e o operador via o comando rodar achando que a configuracao dele valia. Medido: `venues.cex.binance.sandbxo: true` e `venues.cex.binanse.sandbox: true` resolviam `False` -- **producao** --, `venues.cexs.kraken.sandbox: false` resolvia `True`, e `setups.triangle-breakout.pivot_windwo: 9` operava com o default `2`. `validate_setup_settings`, que existe para o erro aparecer no boot, passava por todos: ela valida os **valores** das chaves que conhece, e um typo produz uma chave que ela nao conhece. Esta e a contrapartida da fatia anterior -- passar a instruir o operador a escrever `venues.cex.binance.sandbox` num arquivo, sem nada conferir o que ele escreveu, troca um modo de falha silenciosa por outro.
- **`settings.schema.json`**: o vocabulario como dado, legivel pelo operador, caminhado por `workspace/settings_schema.py`. Sem dependencia nova: o vocabulario e pequeno e o valor esta quase todo na mensagem, que aponta a chave, o caminho e a grafia provavel (`Voce quis dizer 'pivot_window'?`). A lista de parametros e **por setup**, nao uma lista unica: `funding-arb.pivot_window` existe como parametro, mas nao nesse setup, e uma lista unica o aceitaria com a chave morta do mesmo jeito.
- **Id de venue da CEX e conferido contra `ccxt.exchanges`** mais as variantes internas (`kraken-spot`, `krakenfutures`, `hyperliquid-dex`). Id fora dessa lista nao constroi adapter nenhum, entao a chave estaria morta de qualquer forma -- e a venue cairia no default, que fora da familia kraken e producao. O id do **DEX** fica aberto de proposito: `DEX_ADAPTER_MODULE` permite adapter proprio, e fechar ali recusaria configuracao legitima.
- **O `doctor` reporta e o veredito conta.** `settings_error` no relatorio e o check `settings_schema` em `BLOCKING_CHECKS`. Quem edita o settings roda `setup-check`, nao `setup-live`: reportar so no boot do live deixaria a descoberta para o momento em que ja ha ordem para abrir.
- **Os oito portoes booleanos que sobraram ganham vocabulario com os dois lados.** `_load_bool_env` era `raw.lower() in {"1","true","yes","sim"}`: todo o resto caia no `else` implicito e virava `False`. Em `NADO_REQUIRE_LINKED_SIGNER`, cujo default e `True`, isso **desligava a protecao** -- e aqui nao ha o consolo de o default ser o lado seguro, como havia no sandbox. Medido: `ture`, `tru`, `verdadeiro` e tambem `on`, `s` e `y` resolviam `False`. Os tres ultimos sao o caso que mais incomoda, porque sao **validos** no vocabulario que o `sandbox` usa: quem aprendeu a escrever `CEX_SANDBOX=on` desligava a verificacao de linked signer sem nada dizer.
- **Quatro copias do vocabulario viraram uma.** `Settings.get_bool` passou a delegar para `config.coerce_bool`, e os leitores que nao carregam `Settings` consomem a mesma funcao: `cli._load_bool_env`, `nado/auto_trade_nado._env_bool`, `nado/example._env_bool` e `venues/hyperliquid_dex._to_bool`. Corrigir so o `cli` repetiria o defeito de origem do sandbox -- `NADO_REQUIRE_LINKED_SIGNER` e lido em tres lugares, e nos tres o default e `True`.
- **`hyperliquid_dex._to_bool` era um quinto leitor de `sandbox`**, a jusante do resolvedor e com default `False` -- producao. Hoje o resolvedor entrega um `bool` de verdade e a recoercao e inofensiva, mas um valor irreconhecivel chegando por qualquer caminho resolvia para producao em silencio.

### Nao coberto por esta versao

- Restam ~20 leituras booleanas inline (`SETUP_NOTIFY_*`, `SETUP_NOTIFY_TRADINGVIEW_*`) com o mesmo `else` implicito. Ficaram de fora de proposito: todas tem default `False` e ligam funcionalidade de notificacao/renderizacao, entao o typo desliga o que o operador queria ligar -- sem direcao de dinheiro nem de protecao. Migra-las e limpeza, nao correcao.

## v1.4.0 — 2026-09-22

### Corrigido

- **A documentacao parou de distribuir as variaveis que derrubam o `settings.json`.** Fechar o `.env.example` e o assistente de primeiro uso (fatias 1 e 2) nao alcancava quem segue o manual, que e a maioria: `SKILL.md`, `README.md`, `INSTALL.md`, `references/onboarding-*.md` e `doc referencia/` continuavam mandando declarar `KRAKEN_SANDBOX=false` / `CEX_SANDBOX=...` -- 42 linhas em 6 arquivos. O `SKILL.md` era o pior caso: ele recomendava nominalmente salvar `KRAKEN_SANDBOX=false` no `config.env` do workspace/state, que `run._load_key_value_file` **reinjeta em `os.environ`**. Reproduzido: com `venues.cex.kraken.sandbox: true` declarado, quem seguiu a documentacao operava com dinheiro real -- e em silencio, porque `KRAKEN_SANDBOX` e a env mais especifica que existe para a venue e o aviso de "generica engoliu especifica" nao se aplicava.
- **O arquivo de config do operador avisa quando encobre o settings.** As seis variaveis que chegam ao resolvedor (`CEX_SANDBOX`, `KRAKEN_SANDBOX`, `DEX_SANDBOX`, `HYPERLIQUID_SANDBOX`, `HYPERLIQUID_NETWORK`, `DEX_NETWORK`) continuam sendo carregadas do `config.env`, mas o carregamento emite `WARNING` nomeando o arquivo e a chave de settings que ficou sem efeito. Tira-las da allowlist pareceria a correcao obvia e seria pior: quem tem `HYPERLIQUID_SANDBOX=true` salvo la cairia no default da venue, que e `False`, e passaria a operar na mainnet so por atualizar. A chave do aviso sai do proprio resolvedor (`sandbox_settings_keys`), para nao manter uma segunda tabela que diverge da primeira. `NADO_NETWORK` e `NETWORK` ficam de fora de proposito -- o adapter da Nado nunca chama o resolvedor, e aviso que sai sempre e aviso ignorado.
- Teste de guarda que falha se um documento de operador voltar a prescrever `*_SANDBOX=` ou `*_NETWORK=`, no mesmo espirito do guard do `.env.example`.

- **A Hyperliquid passa a consumir o resolvedor unico de sandbox.** Ela deriva o valor da rede selecionada (`HYPERLIQUID_NETWORK`: `testnet` implica sandbox), e esse valor entra na **camada de ambiente** -- abaixo de um `HYPERLIQUID_SANDBOX` explicito, acima de qualquer arquivo --, porque e de uma variavel de ambiente que ele vem. O chamador passa `None` quando nenhuma rede foi declarada: `network in {...}` e sempre um bool, e esse `False` incondicional tornaria `venues.dex.*.sandbox` config morta e mandaria para a mainnet quem declarou sandbox no arquivo.
- **A contradicao entre rede e sandbox deixa de ser silenciosa.** `HyperliquidDexTrader.__init__` faz `self.network = "testnet" if self.sandbox else "mainnet"`: a rede declarada nao sobrevive ao construtor. Com `HYPERLIQUID_NETWORK=testnet` e `HYPERLIQUID_SANDBOX=false` -- o par que o `.env.example` distribuia --, quem escolheu testnet operava na mainnet sem nenhum aviso. A precedencia nao muda; o conflito agora sai como `WARNING` nomeando as duas pontas e dizendo onde a ordem vai cair.
- `HYPERLIQUID_SANDBOX` **e `HYPERLIQUID_NETWORK`** vem comentadas no `workspace/.env.example`. Comentar so a primeira nao resolvia: depois que a rede passou a entrar na camada de ambiente, o `HYPERLIQUID_NETWORK=mainnet` que o exemplo distribuia derrubava `venues.dex.*.sandbox` do mesmo jeito -- e sem aviso, porque rede e sandbox concordavam. O assistente de primeiro uso (`first_run_setup.py`) tambem parou de entregar essas variaveis: ele as escrevia no arquivo de config do operador, que e reinjetado em `os.environ`.
- **Rede da Hyperliquid ganha vocabulario com os dois lados.** `HYPERLIQUID_NETWORK=testnetz` resolvia para producao em silencio -- o mesmo defeito do `ture`, agora pior, porque o valor entra na camada de ambiente e por isso tambem derruba o arquivo. Valor fora do vocabulario levanta `ConfigError`.
- **`env_default` tambem avisa** quando engole uma declaracao de arquivo mais especifica, como ja fazia a env explicita. E o aviso passa a nomear a variavel que de fato decidiu (`DEX_NETWORK`, por exemplo), em vez de citar sempre `HYPERLIQUID_NETWORK`.
- **Empate entre as duas grafias de uma venue resolve pela grafia escrita.** Com as duas no mesmo nivel de especificidade, o desempate caia na ordem alfabetica da chave -- e `-` vem antes de `_`, entao o alias ganhava daquela que o operador selecionou.
- **O campo `kraken_sandbox` do `setup-check` foi removido.** Ele falava de uma venue que podia nao ser a selecionada e ficava ao lado de `cex_sandbox` sem nada indicar isso; com `CEX_ID=binance` o relatorio mostrava `cex_sandbox: "false"` e `kraken_sandbox: "true"` no mesmo payload. `cex_id` + `cex_sandbox` dizem o mesmo sem ambiguidade, e `cex_sandbox` agora sai do resolvedor para a venue selecionada (honrando o alias `PRIMARY_CEX`) e vale `null` quando a config esta ilegivel.
- **A especificidade passa a vir da cadeia da venue, nao do indice da lista.** Quando as grafias alternativas entraram, `keys` ficou maior que `env_names` e o aviso de "env generica engoliu chave especifica" sumia em silencio para todo id normalizado (`kraken_futures`, `hyperliquid_dex`, `binance.us`) -- justamente o caso de migracao que ele existe para cobrir.
- **As duas grafias de um id resolvem nos dois sentidos.** A normalizacao ia so para hifen, entao selecionar `kraken-futures` nao alcancava uma chave escrita `kraken_futures` e a declaracao da venue era descartada pela generica.
- **O veredito do `doctor` sai por nome de check, nao por posicao.** `venues_config` entrou como quinto item e o criterio era `checks[:4]`, entao o comando devolvia `ok` com config que derruba `venues`, `rodar-setups` e o `build_engine`.
- **`kraken_sandbox` segue a variante selecionada.** Cravar o id `kraken` fazia o campo fabricar `"true"` a partir do default enquanto a ordem ia para producao, contradizendo `cex_sandbox` no mesmo payload.
- **Isolamento de teste completo**: o `settings.json` versionado tambem e redirecionado (`config.REPO_ROOT`), os arquivos de env do operador saem do caminho de `setup_check`, e o `os.environ` e restaurado entre testes -- `monkeypatch` so desfaz o que ele mesmo mudou, e codigo de producao chamado de dentro do teste tambem escreve no ambiente.
- **`sandbox` das CEXs passa a ter um resolvedor unico** (`workspace/venues/sandbox.py`). A mesma pergunta -- dinheiro de brinquedo ou dinheiro real -- era respondida em quatro lugares com regras diferentes, e dois defeitos saiam disso: (1) o vocabulario de booleano so definia o lado verdadeiro, entao `CEX_SANDBOX=ture` caia no `else` implicito e o bot operava com dinheiro real achando que estava em sandbox; (2) `_load_cex_sandbox` dava prioridade a variavel generica e `_load_pair_cex_sandbox` a especifica, de modo que `CEX_SANDBOX=false` com `BINANCE_SANDBOX=true` mandava a ordem para sandbox enquanto o resumo exibido ao operador dizia `false`. Ver `Docs/features/sandbox-por-venue.md`.
- Prefixo de variavel por venue deixa de quebrar em id com pontuacao: `binance.us` gerava `BINANCE.US_SANDBOX`, nome que nenhum shell exporta, tornando a variavel especifica inalcancavel em silencio.
- `KRAKEN_SANDBOX` vira variavel de familia declarada, e nao um caso especial no meio do `cli.py`. A familia vale **tambem para as chaves de settings**: `venues.cex.kraken.sandbox` alcanca `krakenfutures` e `kraken-spot`, que de outro modo caiam na chave generica e iam para producao.
- Na varredura dos arquivos de settings, a **camada e o eixo externo**: `settings.local.json` vence `settings.json` mesmo quando o versionado tem a chave mais especifica. Sem isso, uma chave por venue do arquivo do time derrubava a chave generica do arquivo do operador.
- Mensagem de valor invalido nomeia a variavel de ambiente que o operador escreveu (`BINANCE_SANDBOX`), e nao uma chave de arquivo que pode nem existir.

### Adicionado

- `sandbox` configuravel por arquivo em `venues.<tipo>.sandbox` e `venues.<tipo>.<venue>.sandbox`, com exemplo em `settings.example.json`. Antes so existia por variavel de ambiente.
- `Settings.has_env` e `config.FILE_LAYERS`: permitem tratar camada e especificidade como eixos separados sem recodificar a ordem das camadas em dois lugares.
- Aviso quando uma chave de camada mais forte e menos especifica que outra declarada **e os valores divergem** -- um `venues.cex.sandbox: false` do operador engolindo um `venues.cex.kraken.sandbox: true` do time. A ordem continua valendo; perder a declaracao em silencio, nao.
- Teste de guarda que falha se o `.env.example` voltar a trazer uma variavel de sandbox descomentada, e teste que exercita as chaves do `settings.example.json` contra o codigo que as le.

### Mudanca de comportamento (atencao ao atualizar)

- **A precedencia entre as variaveis de sandbox foi invertida.** Antes
  `_load_cex_sandbox` era `CEX_SANDBOX > <PREFIX>_SANDBOX > default`; agora a
  especifica vence a generica, alinhando com os outros tres leitores. A direcao
  benigna e a que motivou a mudanca (`CEX_SANDBOX=false` + `BINANCE_SANDBOX=true`
  passa a ir para sandbox), mas **a direcao oposta tambem mudou**: quem usa
  `CEX_SANDBOX=true` como chave-mestra de seguranca e tem um `<VENUE>_SANDBOX=false`
  esquecido no `.env` passa de sandbox para **producao** so por atualizar.
  Confira as variaveis `*_SANDBOX` do seu `.env` antes de subir esta versao.

### Alterado

- `CEX_SANDBOX` e `KRAKEN_SANDBOX` vem comentadas no `workspace/.env.example`: ativas, venciam o `settings.json` e o deixavam inoperante para quem copiasse o exemplo.
- Os dois comandos de diagnostico deixam de estourar com config invalida: `setup-check` reporta a mensagem em `venues_error` e devolve `cex_sandbox: null` em vez de chutar `"false"`; `venues` termina com a mensagem em vez de traceback. Eles sao rodados justamente quando algo esta errado.
- As fixtures de `test_sandbox_resolution` e `test_config_foundation` isolam o home: `_local_settings_path` devolve o primeiro caminho que existe, entao sem isso a suite lia o `settings.local.json` real do operador em vez da fixture.

## v1.3.0 — 2026-09-14

### Adicionado

- **Fonte unica de configuracao** (`workspace/config.py`): precedencia `env -> settings.local.json -> settings.json -> default`, vocabulario de booleano com os dois lados explicitos (valor desconhecido levanta erro em vez de virar `false`), segredo declarado apenas pelo *nome* da variavel de ambiente, e origem rastreavel por chave. Ver `Docs/features/configuracao-de-setups.md`.
- **Parametros de setup configuraveis por arquivo**: cada setup expoe as suas vars em `setups.<chave>.<parametro>`. Destrava calibracao por timeframe no `divergence-and-volume` (as variaveis de ambiente sao unicas para 15m/1h/4h) e torna `fibonacci_levels`, `target_levels` e `target_weights` ajustaveis — antes so mudavam editando codigo, apesar de decidirem onde o capital sai da posicao. Exemplo em `settings.example.json`.
- **Validacao da config de setup no boot** (`validate_setup_settings`): valor invalido derruba o comando antes do primeiro ciclo. Dentro do loop de scan a excecao seria capturada como `WARNING`, deixando o bot de pe sem abrir nada.
- **Pipeline de CI que executa a suite** (`.github/workflows/tests.yml`): pytest em ubuntu x windows x Python 3.12/3.13, ruff, mypy, pip-audit e cobertura, mais `dependabot.yml`. A CI anterior passava sem rodar teste nenhum.

### Corrigido

- **Resposta da corretora ao anexar SL/TP passa a ser validada** nos tres adapters (`workspace/venues/order_validation.py`). Antes, qualquer objeto nao-`None` contava como "protecao anexada" — inclusive uma rejeicao estruturada —, porque os chamadores so testam `if order is None`. Ver `Docs/features/protecao-de-ordens.md`.
- `replace_stop_loss` cancela o stop vivo antes de criar o novo nos tres adapters; a falha agora diz explicitamente que a posicao ficou sem stop, e a referencia da ordem morta e limpa do estado.
- `place_market_order_with_tp_sl` (Kraken) deixa de engolir a falha de protecao: devolve `protected`, `protection_error` e os ids de SL/TP.
- Escada de alvos passa a ser invariante de `DivergenceVolumeConfig`: escada vazia, contagem divergente de pesos e soma nao positiva sao recusadas na construcao. Antes o mesmo estado invalido era fatal vindo do settings e silenciosamente reparado vindo do construtor.
- Dois nomes indefinidos expostos pelo gate de lint: `_first_float` sem import em `cli.py` (o `NameError` era engolido por um `except Exception` e virava "saldo indisponivel") e `BacktestResult` num fake de teste que nunca era exercitado.
- Bit de execucao restaurado em `render_trade_chart.js` e `tradingview_session.js`.

### Alterado

- `workspace/.env.example` comenta as variaveis de calibracao de setup: elas continuam funcionando e **tem precedencia** sobre o `settings.json`, entao mante-las ativas no exemplo tornava o settings inoperante para quem copiasse o arquivo. O boot avisa quando uma chave de settings esta encoberta pela env.
- `settings.local.json` e procurado fora da arvore primeiro (`DELTA_NEUTRAL_SETTINGS_DIR`, depois `~/.config/openclaw/<skill>/`), porque a skill e reinstalada por cima do proprio diretorio.

## v1.2.0 — 2026-09-09

### Corrigido

- Substitui `import fcntl` por um lock de arquivo cross-platform (`workspace/file_lock.py`): o CLI nao importava no Windows, o que derrubava a coleta de 3 dos 4 arquivos de teste. Consolida a estrategia PID + `O_EXCL` que ja existia no `dashboard_publisher`, agora com espera por timeout.
- Corrige a sonda de liveness do lock: no Windows `os.kill(pid, 0)` **nao levanta** para um PID que ja morreu (o sinal 0 e `CTRL_C_EVENT`, que cai no ramo de evento de console), entao qualquer processo morto era reportado como vivo e o lock orfao nunca seria recuperado. Passa a usar `OpenProcess`/`GetExitCodeProcess`. *(Corrigido em 14/09/2026: a versao original desta nota afirmava que `os.kill(pid, 0)` executaria `TerminateProcess` — verificado por execucao que nao e o caso.)*
- `setup-check` deixa de disparar `pip install` de rede a cada execucao em maquinas sem o SDK da Nado, e deixa de gastar um startup de interpretador por modulo sondado (24s -> 0,28s nesta maquina).

### Alterado

- O SDK `nado-protocol` passa a ser dependencia **opcional**, exigida apenas por `DEX_ID=nado`. `requirements.txt` agora instala em qualquer maquina; a Nado vive em `requirements-nado.txt`. Kraken, Hyperliquid e as demais CEXs sempre rodaram por CCXT e nao precisam do toolchain de build nativo.
- `core/delta_neutral.py` nao importa mais `NadoTrader` em runtime — era usado so como anotacao de tipo, e agora vai sob `TYPE_CHECKING`.
- `workspace/nado/__init__.py` resolve simbolos sob demanda; usar a Nado sem o SDK falha alto no ponto de uso, com instrucao explicita.

### Adicionado

- `workspace/nado/units.py` com as conversoes `from_x18`/`from_x6` (aritmetica pura, sem dependencia do SDK), reexportadas por `nado_integration`.

## v1.1.22 — 2026-06-16

### Adicionado

- Adiciona `setup-live --modo-stop-alvo desligado|entrada-no-tp1|escada` e env `SETUP_LIVE_TARGET_STOP_MODE` para escolher se o stop fica fixo, vai para entrada no TP1 ou sobe em escada a cada alvo.
- Documenta no wizard/skill que o stop movido é gerenciado pelo loop do `setup-live`; a recriação de ordem stop nativa depende de suporte explícito da venue.

## v1.1.20 — 2026-06-16

### Alterado

- Atualiza o wizard de configuração para perguntar DEX/CEX antes de secrets, modo, sizing e margem.
- Lista as principais venues no onboarding: Nado, Hyperliquid, Binance, Kraken, Bybit, OKX, KuCoin, MEXC, Bitget e Gate.io.
- Adiciona passo a passo por corretora/venue e reforça que outras CEXs integram via CCXT e outras DEXs via adapter Python.
- Deixa explícito no wizard e guias que subconta/conta isolada é recomendada quando a corretora/DEX oferecer esse recurso, mas não obrigatória por padrão; a decisão final é do usuário e não deve ser hard-coded; o requisito mínimo é API key/credencial dedicada sem saque e validação por `doctor`/dry-run.

## v1.1.19 — 2026-06-01

### Alterado

- Restringe `low-stoch-storm` para BTC/ETH/SOL/XRP na allowlist padrão, com base em validação operacional real.
- Restringe `divergence-and-volume-*` para ETH/XMR na allowlist padrão e no whitelist default do setup experimental.
- Atualiza símbolos padrão das validações reais para refletir os ativos validados por setup.

### Corrigido

- Corrige o label do ranking operacional para manter `Divergence and Volume 15m`, `1h` e `4h` separados.

## v1.1.18 — 2026-05-26

### Corrigido

- Corrige nomes publicos/documentacao dos setups para `low-stoch-storm` e `divergence-and-volume-*`.
- Corrige comandos/manifesto das validações reais dedicadas de Low Stoch Storm e Divergence and Volume.
- Corrige runtime/config por timeframe do Divergence and Volume e allowlists relacionadas.

### Tracking

- Issue: #1

## 1.1.9 - 2026-05-12

- Nova release correta para validação do wizard curto final.
- Mantém correção que remove link/cadastro externo do wizard.


## 1.1.8 - 2026-05-12

- Ajusta wizard curto para não enviar link/cadastro externo.
- Troca `secrets_status` por `account_and_secrets_status`.
- Remove links/referrals diretos do guia detalhado operacional.

## 1.1.7 - 2026-05-12

- Encurta o wizard principal para 6 perguntas essenciais.
- Move o onboarding longo Nado/Kraken para `references/onboarding-detalhado.md`.
- Adiciona payload JSON em `workspace/first_run_setup.py --json` para first-run automático.



## 1.1.6 - 2026-05-12

- Ajusta fallback Nado para TP parcial abaixo do mínimo nativo: fecha 100% no primeiro alvo gerenciado por padrão (`SETUP_LIVE_NADO_MANAGED_TP_POLICY=first_target_full`).
- `live-status` passa a marcar exposições reais como `managed` ou `ORPHAN`, sem fechar posições automaticamente.
- Registra `PNL potencial max` por entrada e avança múltiplos TPs cruzados na mesma iteração do loop.
- Reforça que `setup-live --dry-run` não executa TP/SL real nem libera slot como live.

## v1.0.20 — 2026-05-06

### Adicionado

- Portados os setups `low-stoch-storm` e `divergence-and-volume-4h` para o catálogo operacional da skill.
- `low-stoch-storm` agora entra no ranking operacional com regra LONG 4h por Stoch/EMA/RSI, stop estrutural/ATR e alvos 1R/1.5R/2R/3R.
- `divergence-and-volume-4h` entra no ranking operacional e mantém validação real dedicada por divergência RSI + volume + zona Fibonacci + candle de reversão.

### Alterado

- Separados os filtros `normal` vs `strict` de `momentum` e `institutional`: as versões normais preservam a calibração anterior, enquanto as versões strict exigem RSI mais estreito, volume `>SMA20x1.15` e gaps de tendência mais fortes.

### Validação

- Validação sintética registrada para `divergence-and-volume-4h`; `low-stoch-storm` permaneceu sem trades nessa amostra, com execução observada tratada como amostra pequena.

## v1.0.19 — 2026-05-06

### Adicionado

- Entrega extra de aviso de entrada confirmada no Discord via `--notify-entry-discord-channel-id` ou `SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID`, sem substituir o destino principal como Telegram.
- O aviso agora cobre todas as entradas confirmadas do `setup-live`, incluindo DEX-only, CEX-only e hedged.

## v1.0.18 — 2026-05-01

### Alterado

- Default recomendado de `SETUP_ACCOUNT_MARGIN_SLOTS` atualizado de 16 para 8 para evitar entradas abaixo do mínimo operacional da Nado em contas pequenas.
- Regra operacional Nado: quando `NADO_LINKED_SIGNER_PRIVATE_KEY` estiver ausente, a skill usa automaticamente o owner da subconta em vez de bloquear trade.
- Fallback owner por erro/mismatch de linked signer continua exigindo `NADO_ALLOW_OWNER_FALLBACK=true` + `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK=true`.
- Atualizados `setup-check`/`doctor`, `.env.example`, README/INSTALL/SKILL.md e testes para refletir a regra.

## v1.0.17 — 2026-04-30

### Adicionado

- Novos setups calibrados `momentum-strict`, `grid-strict` e `institutional-strict` para substituir variantes menos robustas.
- Validação operacional registrada para `momentum-strict`, `grid-strict` e `institutional-strict`.

### Operacional

- `triangle-breakout` continua fora das novas entradas até nova calibração.

## v1.0.16 — 2026-04-30

### Adicionado

- Novo setup `bollinger-mean-reversion-strict`, calibrado com distância de 0.20 ATR fora da banda e RSI 35/72.

## v1.0.15 — 2026-04-30

### Corrigido

- Saídas parciais solo (`partial_exit`) agora atualizam quantidade/notional restantes no state gerenciado, evitando status e stress guardrail superestimarem exposição após TP parcial.

## v1.0.14 — 2026-04-30

### Adicionado

- Flags no `setup-live` para notificação de entrada confirmada: `--notify-entry-target`, `--notify-entry-channel`, `--notify-entry-account` e `--no-notify-entry`.

## v1.0.13 — 2026-04-30

### Adicionado

- Notificação best-effort de entrada confirmada no `setup-live` via `openclaw message send`, configurável por `SETUP_NOTIFY_ENTRY_*`.

## v1.0.12 — 2026-04-30

### Adicionado

- Guardrail de margem cross da Nado para `setup-live`: `--account-margin-reserve-usd`, `--account-margin-reserve-pct`, `--account-margin-slots`, `--account-max-maint-usage-pct` e `--account-stress-pct`.
- Cálculo de `Maint. Margin Usage` a partir dos healths da subconta e log de orçamento/slot por entrada.
- Quando não há `--margin-usd` explícito, `--account-margin-slots` divide o orçamento operacional da conta em slots e calcula a margem por entrada automaticamente.

## v1.0.11 — 2026-04-30

### Adicionado

- Novo comando `asset-scan` para comparar perps/ativos entre Nado e Kraken, detectar símbolos adicionados/removidos, salvar snapshot em `state/asset_scan_state.json` e marcar mercados suspeitos por preço inválido ou spread alto Nado/Kraken.
- Env `NADO_DISABLED_PERP_SYMBOLS`/`NADO_EXCLUDE_SYMBOLS` documentadas no manifesto para blacklist temporária de perps ainda não operacionais.

## v1.0.10 — 2026-04-30

### Corrigido

- `setup-live` não bloqueia mais entrada por uma liquidação teórica derivada de `1/leverage` antes da ordem existir.
- O stop configurado por `--stop-loss-pct` continua sendo a regra de saída/gestão negativa, sem ser confundido com preço de liquidação.
- Após entrada real, o log registra `liq_corretora` com a liquidação lida da venue quando disponível; enquanto a corretora não retornar o dado, fica `corretora_pendente`.
- `setup-live --symbol all` agora exclui por padrão `ADA/USDT` e `ARB/USDT` na Nado, pois não há perp ativo; pode ser sobrescrito por `NADO_DISABLED_PERP_SYMBOLS`/`NADO_EXCLUDE_SYMBOLS`.

## v1.0.9 — 2026-04-30

### Adicionado

- `setup-live --max-open-setups` e env `SETUP_LIVE_MAX_OPEN_SETUPS` para limitar o número global de setups gerenciados abertos.
- Com `--max-open-setups 1`, a skill abre no máximo uma operação e pausa novas entradas enquanto ela estiver ativa.

## v1.0.8 — 2026-04-30

### Adicionado

- `NADO_MIN_ORDER_NOTIONAL_USD` permite substituir explicitamente o mínimo de notional usado pela validação local da skill em entradas Nado-only/setup-live.

### Observação

- O override não altera regras reais da Nado; ordens abaixo do mínimo efetivo da venue ainda podem ser rejeitadas durante a execução.

## v1.0.7 — 2026-04-29

### Adicionado

- `open` e `setup-live` aceitam `--margin-usd`, `--nado-margin-usd` e `--kraken-margin-usd`; o notional operacional passa a ser `margem * leverage`.
- `setup-live` aceita stop por execução com `--stop-loss-pct` e presets `--stop-loss-preset 10|20|30|conservador|moderado|degen`.
- Wrapper aceita `.env` efêmero com `--runtime-env`, antes ou depois do comando.
- Flags explícitas para fallback privilegiado: `NADO_ALLOW_OWNER_FALLBACK`, `KRAKEN_ALLOW_MAIN_ACCOUNT` e `DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK`.

### Corrigido

- Entrada solo Nado/DEX agora bloqueia pelo mínimo real do ativo/venue, não por mínimo artificial de setup, SL ou TP parcial.
- TP parcial nativo da Nado abaixo do mínimo não bloqueia a entrada; o alvo permanece no gerenciamento do setup e o skip nativo fica registrado.
- Guardrail padrão de saldo Nado para setup-live foi reduzido para 5% do notional quando margem explícita não é usada.

## v1.0.6 — 2026-04-29

### Adicionado

- `open` agora aceita `--execution-mode hedged|dex_only|cex_only` com aliases `nado_only` e `kraken_only`.
- `open` agora aceita `--margin-mode`, `--nado-margin-mode`, `--kraken-margin-mode`, `--leverage`, `--nado-leverage` e `--kraken-leverage`.
- Defaults por env para execução/margem/leverage: `EXECUTION_MODE`, `MARGIN_MODE`, `NADO_MARGIN_MODE`, `KRAKEN_MARGIN_MODE`, `LEVERAGE` e aliases DEX/CEX.

### Corrigido

- `status`, `unwind`, `rebalance` e `farm` agora reconhecem estados solo Nado/DEX ou Kraken/CEX.
- `setup-live` aceita aliases `dex_only` e `cex_only` e pode ler `EXECUTION_MODE`/margens do env.

## v1.0.5 — 2026-04-29

### Corrigido

- Aceito `PRIVATE_KEY` como alias legado opcional depois de `NADO_OWNER_PRIVATE_KEY` e `NADO_PRIVATE_KEY`.
- `NETWORK` agora é fallback para `NADO_NETWORK`.
- `CERTAINTY` aceita inteiro, porcentagem ou decimal (`75`, `75%`, `0.75`).
- `UNIQUE_TREND` ignora valores booleanos e só aplica `LONG` ou `SHORT`.
- `MAX_OPPORTUNITIES` passa a ser respeitado no comando `opportunistic`.
- `EXCHANGES=nado,kraken` agora é tolerado: `nado` é ignorado como fonte CCXT e `kraken` é mapeado para Kraken Futures.

## v1.0.4 — 2026-04-29

### Corrigido

- Declarado `setuptools<81` no manifesto para refletir o bootstrap real da skill.
- Permitido `--help` e `--dry-run` em comandos protegidos sem exigir confirmação live.
- Atualizados scripts auxiliares Nado para usar envs canônicas (`NADO_OWNER_PRIVATE_KEY`, `NADO_LINKED_SIGNER_PRIVATE_KEY`) e bloquear execução direta sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`.
- Ajustado teste de linked signer para refletir o bloqueio seguro por `RuntimeError`.

### Documentação

- Esclarecido que as envs de Nado/Kraken são obrigatórias para operação real e devem vir do env/secret manager.
- Alinhados README/INSTALL ao repositório OpenClaw.

## v1.0.3 — 2026-04-29

### Corrigido

- Manifest agora declara `live-status`, `live-hedge` e `live-sync`, que já existiam no CLI.
- Smoke test cobre a paridade desses comandos no `skill.json`.

## v1.0.2 — 2026-04-29

### Alterado

- Alinhado o identificador runtime da skill para `trade-automatizado-openclaw`.
- Paths padrão de env/state/log agora usam o nome OpenClaw da skill.
- Mantido fallback para env/state legados de `delta-neutral-airdrop-farmer`, evitando quebra de instalações antigas.

## v1.0.1 — 2026-04-28

### Corrigido

- Reativada trava de linked signer em `NadoTrader.assert_trade_ready()`.
- Reativada trava de subconta/conta master em `KrakenTrader.validate_entry_subaccount_rule()`.
- `workspace/cli.py` agora também bloqueia comandos de trade sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`, evitando bypass do wrapper.
- Removido fallback genérico `PRIVATE_KEY`; a skill aceita apenas `NADO_OWNER_PRIVATE_KEY` e o alias explícito `NADO_PRIVATE_KEY`.
- `backup_project.py` não copia mais `.env`, `.env.*`, state, batch artifacts, dist ou caches.
- Removidos `workspace/batch-*.json` do repo e adicionado ignore para novos artefatos operacionais.
- Dependências principais pinadas e `pytest` incluído para validação dev.

### Segurança

- Não usar live/mainnet sem validar `doctor`, linked signer Nado e subconta Kraken dedicada.

## v1.0.0 — 2026-04-28

### Adicionado

- Release inicial da skill OpenClaw no repositório dedicado.
- Entrada `workspace/run.py` com `setup-check`, `doctor` e `bootstrap`.
- Bootstrap previsível de dependências Python em `.venv` local quando o runtime suporta `venv/pip`.
- Carregamento opcional de env seguro via `~/.config/openclaw/delta-neutral-airdrop-farmer.env`.
- Estado/logs fora do Git em `~/.openclaw/state/delta-neutral-airdrop-farmer/` e `~/.openclaw/logs/delta-neutral-airdrop-farmer/`.
- Bloqueio de comandos live/trade sem `DELTA_NEUTRAL_CONFIRM_LIVE=true`.

### Segurança

- Secrets apenas em env/secret manager, nunca no Git.
- Live trading exige confirmação explícita por execução.
- `workspace/cli.py` preservado como motor principal; wrapper adiciona guardrails sem reescrever estratégia.
