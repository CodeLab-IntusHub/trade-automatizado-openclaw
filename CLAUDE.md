# CLAUDE.md — trade-automatizado-openclaw

Instruções de desenvolvimento deste repositório. **Não vai no pacote `.skill`**:
o `build.py` exclui este arquivo, porque ele descreve a organização e o
trabalho, não o produto.

O estado do produto está em [`Docs/PROGRESS.md`](Docs/PROGRESS.md); o plano,
em [`Docs/ROADMAP.md`](Docs/ROADMAP.md); o porquê das decisões, em
[`Docs/decisions/`](Docs/decisions/).

## Onde este repositório fica na constelação

A IntusHub organiza os repositórios como **um planeta e satélites**. O planeta é
o [`intushub-core`](https://github.com/CodeLab-IntusHub/intushub-core)
(privado): ele guarda **toda** a DDL do banco compartilhado da plataforma,
de todos os schemas, e as Edge Functions da org. **Este repositório é
satélite**: a skill IntusCripto, que cada bot OpenClaw executa na máquina do
próprio operador.

| O que mora aqui | O que **não** mora aqui |
|---|---|
| A skill: scanner, execução, adapters de venue, renderers, testes | DDL, migration, Edge Function, política de acesso do banco compartilhado |
| O contrato do que a skill publica ([`Docs/features/contrato-do-sinal.md`](Docs/features/contrato-do-sinal.md)) | Credencial do banco compartilhado, em qualquer forma |

**As duas regras que valem aqui:**

1. **Este repo não depende do planeta.** Nada de `import`, caminho relativo para
   fora ou spec lida de lá. **Chamar em runtime** um endpoint HTTP da plataforma
   é permitido, porque é fronteira e não acoplamento. O teste: se o planeta
   sumisse do disco, este repositório ainda compila e testa?
2. **Toda integração com o banco compartilhado nasce no planeta.** O
   ecossistema da [Fase 3 do ROADMAP](Docs/ROADMAP.md) (schema `trading`, RPCs,
   Edge Functions) é PR no `intushub-core`. Aqui entra só o cliente HTTP que
   chama esses endpoints. Ordem: **expand no banco primeiro, contract no
   satélite depois**, porque mergear código que chama um endpoint inexistente
   quebra quem atualizar a skill.

**Varredura de DDL e Edge Function (24/09/2026): limpo.** Nenhuma pasta
`supabase/`, `migrations/` ou `functions/`, nenhum `.sql`, nenhuma DDL em
string, nenhum `Deno.serve`, e nenhum código cita Supabase.

Fonte da verdade da hierarquia:
`Docs/organizacao/hierarquia-de-repositorios.md` no planeta. Divergiu? Aquele
arquivo ganha.
