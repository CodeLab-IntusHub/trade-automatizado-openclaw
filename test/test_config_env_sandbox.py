"""O settings so vale se nada o estiver derrubando por variavel de ambiente.

As fatias 1 e 2 fecharam o `.env.example` e o assistente de primeiro uso. Ficou
aberto o terceiro distribuidor, que e o mais dificil de ver: os documentos que
o operador (e a propria skill) leem continuavam mandando salvar
`KRAKEN_SANDBOX=false` no arquivo de config nao-sensivel do workspace/state --
e `run._load_key_value_file` **reinjeta** esse arquivo em `os.environ`.

O resultado reproduzido: com `venues.cex.kraken.sandbox: true` declarado no
settings, quem seguiu a documentacao opera com dinheiro real. E em silencio,
porque `KRAKEN_SANDBOX` e a env mais especifica que existe para a venue
`kraken` -- o aviso de "env generica engoliu chave especifica" nao se aplica.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import workspace.run as run  # noqa: E402

# Documentos que o operador le e de onde ele copia. `Docs/features/` e o
# `CHANGELOG` ficam de fora: eles descrevem o mecanismo, inclusive citando as
# variaveis para explicar por que nao usa-las.
DOCS_DE_OPERADOR = (
    "SKILL.md",
    "README.md",
    "INSTALL.md",
    "references/onboarding-questionario.md",
    "references/onboarding-detalhado.md",
    "doc referencia/03-env-e-credenciais.md",
)

# Atribuicao com valor: `KRAKEN_SANDBOX=false`. Citar o nome da variavel para
# explicar que ela existe nao e o problema -- copiar a linha e.
ATRIBUICAO = re.compile(r"\b([A-Z][A-Z0-9_]*_(?:SANDBOX|NETWORK))\s*=\s*([^\s`|,;)]+)")

# `NADO_NETWORK` e `NETWORK` ficam de fora: o adapter da Nado e construido so a
# partir delas e nunca chama o resolvedor, entao elas nao derrubam settings
# nenhum. Mesmo criterio do guard do `.env.example`.
NAO_DERRUBAM = {"NADO_NETWORK", "NETWORK"}


def test_docs_de_operador_nao_mandam_escrever_sandbox_em_env() -> None:
    """O `.env.example` foi fechado; a documentacao continuava distribuindo.

    Sem este guard, a correcao das fatias 1 e 2 vale para quem le o codigo e
    nao para quem segue o manual -- que e a maioria.

    **Limite conhecido:** ele pega a forma copiavel (`KRAKEN_SANDBOX=false`),
    que e o vetor real -- o operador cola a linha no arquivo. Prosa que manda
    salvar a variavel sem escrever a atribuicao passa por ele; uma linha assim
    existia no `onboarding-detalhado.md` e foi encontrada a olho, nao por este
    teste. Alargar o padrao para qualquer mencao pegaria tambem o texto que
    explica **por que nao** usa-las, que e justamente o que se quer escrito.
    """
    ofensas: list[str] = []
    for relativo in DOCS_DE_OPERADOR:
        caminho = ROOT / relativo
        if not caminho.exists():
            continue
        for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
            for nome, valor in ATRIBUICAO.findall(linha):
                if nome in NAO_DERRUBAM or not valor:
                    continue
                ofensas.append(f"{relativo}:{numero}: {linha.strip()[:90]}")
    assert ofensas == [], (
        "documento de operador mandando declarar sandbox/rede por env "
        f"(elas vencem o settings.json):\n" + "\n".join(ofensas)
    )


def test_config_env_do_operador_avisa_ao_derrubar_o_settings(tmp_path: Path, caplog) -> None:
    """Arquivo antigo continua valendo -- mas para de valer em silencio.

    Remover essas chaves da allowlist seria pior: quem tem
    `HYPERLIQUID_SANDBOX=true` salvo la cairia no default da venue, que e
    `False`, e passaria a operar na mainnet so por atualizar. A precedencia
    fica; o silencio e que sai.
    """
    arquivo = tmp_path / "config.env"
    arquivo.write_text("KRAKEN_VENUE=futures\nKRAKEN_SANDBOX=false\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        run._load_key_value_file(arquivo, allowed_keys=run.NON_SECRET_CONFIG_ENV)
    mensagens = "\n".join(r.getMessage() for r in caplog.records)
    assert "KRAKEN_SANDBOX" in mensagens, mensagens
    assert "venues.cex.kraken.sandbox" in mensagens, mensagens
    # A que nao derruba nada nao vira ruido: um aviso que sai sempre e ignorado.
    assert "KRAKEN_VENUE" not in mensagens, mensagens
