# Aspira Trade — checklist de publicação Pine no TradingView

Status operacional desde 2026-07-07 23:55 UTC: **rota Pine pausada para entrega Discord**.

Objetivo original deste checklist: publicar/salvar os Pines dos setups e configurar o renderer para usar o Pine canônico por setup/timeframe.

Decisão mais recente: voltar à entrega gráfica funcional do Discord baseada em TradingView/widget + overlay direto, **sem intervenção de Pine**. Este arquivo fica como referência técnica/backup, não como rota ativa de publicação.

## Setups ativos

| Setup | Timeframe | Arquivo Pine | Variável de ambiente |
|---|---:|---|---|
| grid-strict | 1H | `aspira_grid_strict_1h.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_GRID_STRICT` |
| institutional-strict | 1H | `aspira_institutional_strict_1h.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_INSTITUTIONAL_STRICT` |
| bollinger-mean-reversion | 15M | `aspira_bollinger_mean_reversion_15m.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_BOLLINGER_MEAN_REVERSION` |
| low-stoch-storm | 4H | `aspira_low_stoch_storm_4h.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_LOW_STOCH_STORM` |
| divergence-and-volume-15m | 15M | `aspira_divergence_and_volume_15m.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_15M` |
| divergence-and-volume-1h | 1H | `aspira_divergence_and_volume_1h.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_1H` |
| divergence-and-volume-4h | 4H | `aspira_divergence_and_volume_4h.pine` | `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_DIVERGENCE_AND_VOLUME_4H` |

## Procedimento

1. Abrir o TradingView logado na conta que será usada na renderização.
2. Para cada arquivo Pine ativo, abrir Pine Editor, colar o código, salvar e adicionar ao gráfico.
3. Confirmar que o script aparece no timeframe correto.
4. Coletar o study id aceito pelo widget/renderizador.
5. Preencher `tradingview-study-env.template` com listas JSON, por exemplo:
   `SETUP_NOTIFY_TRADINGVIEW_PINE_STUDIES_GRID_STRICT=["<study-id>"]`
6. Aplicar essas envs no serviço de teste.
7. Rodar uma sequência com 1 mensagem por setup no canal de teste.
8. Só religar entrada automática depois da aprovação visual.

## Validação 2026-07-07

IDs privados `USER;...` dos 7 Pines ativos foram recuperados via `pine-facade/list?filter=saved` e registrados em `tradingview-study-env.generated`.

Status atual:
- os IDs existem e apontam para os scripts salvos na conta logada;
- o widget isolado limpo aceita estudos públicos/nativos como `RSI@tv-basicstudies`;
- o widget isolado retornou `403` para `USER;...` privado e não carregou o Pine real;
- formatos testados sem sucesso para `Aspira Divergence and Volume 4h`: `USER;...`, `USER;...@tv-scripting`, `Script$USER;...@tv-scripting`, `Script$USER;...`.

Próximo passo para entrega Discord com TradingView limpo: obter ID aceito pelo widget/renderizador, provavelmente `PUB;...`/publicação protegida/convite, ou renderizar via app logado em layout descartável isolado validado pela árvore de objetos/janela de dados.

## Layouts gerenciados por setup

Decisão 2026-07-07: a rota canônica com TradingView logado usa `tradingview-managed-layouts.json` como manifesto determinístico.

Regra:
- cada setup/timeframe ativo deve ter um layout TradingView gerenciado e nomeado;
- esse layout já deve conter o Pine oficial do setup;
- o renderer escolhe o layout pelo setup/timeframe e falha se o layout não existir ou se o Pine não estiver presente/visível;
- entrada, stop e alvos continuam vindo do payload do trade e são desenhados temporariamente pela escala real do TradingView;
- o layout manual `Intus` / `jnC4he2w` continua proibido no fluxo de render.

Primeiro layout validado:
- setup: `divergence-and-volume-4h`
- layout TradingView: `Aspira Render | Divergence Volume | 4H`
- chart id: `ffzh8YJR`
- Pine esperado: `Aspira Divergence and Volume 4h`
- prova estrutural: renderer estrito passou com `inserted:false`, ou seja, o Pine já estava definido no layout e não foi injetado na hora.
- correção visual histórica pré-2026-08-04: a versão com tabela `ASPIRA DV 4H`, marcadores de componente e fib/faixas foi rejeitada por poluição visual. Regra atual: o Pine do layout deve carregar somente a lógica/indicadores necessários do setup/timeframe específico; entrada, stop e alvos continuam fora do Pine e vêm do payload do trade. Referências humanas antigas neste item não criam validador/owner atual.
- prova visual limpa 2026-07-07: Pine corrigido contra runtime `RE10008`, salvo/aplicado no TradingView sem painel/tabela, sem marcadores históricos e sem faixas decorativas; renderer captura o pane limpo com entrada/stop/alvos.
- validação Discord limpa: imagem `divergence-volume-4h-clean-pine-v13.png` enviada no canal privado de teste `<DISCORD_TEST_CHANNEL_ID>` como mensagem de validação, não trade real.

Os demais setups ficam com status `pending_tradingview_layout` até criação/validação visual equivalente.

Pendência honesta: o renderer valida automaticamente presença do Pine no chart model/legenda e a escala real do overlay. A validação estética de poluição visual ainda depende de inspeção/visão; para automatizar isso de verdade, adicionar OCR/vision gate ou heurística de ausência de toolbars/painéis/marcadores históricos.

## Guardrail

Enquanto a rota sem Pine estiver ativa, manter:

```env
SETUP_NOTIFY_TRADINGVIEW_PINE_ENABLED=false
SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE=false
```

Com `SETUP_NOTIFY_TRADINGVIEW_PINE_ENABLED=true` e `SETUP_NOTIFY_TRADINGVIEW_REQUIRE_PINE=true`, ou com o manifesto de layouts gerenciados em modo estrito, o renderer deve falhar se o setup não tiver Pine/layout configurado ou se o Pine esperado não aparecer no chart model e na legenda. Isso é intencional para testes Pine, mas não é a rota ativa de entrega gráfica do Discord.
