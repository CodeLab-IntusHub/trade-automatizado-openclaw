# ADR 0005 — Rebrand Aspira → IntusCripto, com superfícies preservadas

> Data: 23 de setembro de 2026
> Status: **Aceita** — executada no PR #24

## Contexto

"Aspira" era o nome do OpenClaw onde esta skill foi desenvolvida. O produto
hoje é **IntusCripto**, da IntusHub. O nome antigo aparecia em 145 lugares, em
29 arquivos — mas não eram todos do mesmo tipo.

## Opções consideradas

1. **Substituir tudo.** Rápido, e errado: algumas ocorrências espelham estado
   que vive **fora** do repositório.
2. **Não renomear nada.** Mantém a marca antiga no que o operador vê.
3. **Renomear por camada de risco**, preservando o que espelha o mundo de fora.

## Decisão

**Opção 3.** Renomeados: os arquivos e nomes de estudo dos `.pine`, os índices
da pasta de referências, identificadores internos do HTML gerado e a marca
exibida (`SETUP_NOTIFY_BRAND` e afins).

**Preservados de propósito**, com teste para cada um:

| Superfície | Por que fica |
|---|---|
| Arquivos de estado do scanner em `~/.openclaw/state/` | Já existem na máquina de quem opera. Renomear faria o scanner não achar o estado anterior e recomeçar do zero, sem erro. Nome de arquivo interno não é superfície de marca |
| `pine_title`, `layout_name`, `tradingview_actual_layout_name` | Nomeiam layouts e estudos que existem na conta TradingView, e o renderer compara por texto — renomear aqui sem renomear lá quebra a renderização |
| Campo `schema` do sinal | Contrato com consumidor em funcionamento. O nome novo entrou ao lado, em `schema_canonico` |

## Consequências

- **Republicar um estudo Pine com o nome novo exige atualizar o `pine_title` no
  mesmo commit** — as duas pontas do mesmo nome. Está escrito no checklist da
  pasta `references/pine-setups/`.
- **Fechar o legado do `schema`** é o passo 0.1 do [ROADMAP](../ROADMAP.md).
- Registro histórico de proveniência (`OPENCLAW-SOURCE.md`) mantém "Aspira": é
  história correta, não marca em uso.
- **Lição registrada:** encontrar um nome em uso no código responde "onde ele
  aparece", não "de quem ele é". Antes desta decisão, a presença do nome em
  valores ativos chegou a ser lida como prova de que era a marca atual.

## Changelog

| Data | Mudança |
|------|---------|
| 23/09/2026 | Decisão registrada |
