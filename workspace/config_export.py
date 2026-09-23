"""Emite o `settings.json` equivalente ao ambiente atual.

A migração de variável de ambiente para arquivo é incremental por desenho, e
isso cria um degrau ruim para quem já opera: o operador tem dezenas de
variáveis no `.env`, a documentação fala em `settings.json`, e o caminho entre
as duas coisas é transcrever à mão — lendo o código para descobrir qual chave
corresponde a qual variável.

## O que este comando não pode fazer é parecer completo

Só parte das variáveis tem equivalente em settings hoje. Um arquivo que
aparentasse substituir o `.env` levaria o operador a apagar o `.env` e perder
credencial. Por isso a saída vem com três avisos, e nenhum deles é decorativo:

1. **o que não tem equivalente** — as variáveis que continuam só no ambiente;
2. **o que continua vencendo** — exportar não muda nada enquanto a variável
   existir, porque ambiente vence arquivo por desenho. Quem exporta, mantém o
   `.env` e não vê mudança conclui que settings não funciona;
3. **os segredos definidos**, pelo nome — para o operador saber que a
   credencial fica onde está, sem que o relatório a imprima.

## De onde saem as chaves

Do próprio código, não de uma lista paralela. `Settings._require` é o funil
único de leitura: instrumentá-lo enquanto os getters de setup rodam devolve
exatamente as chaves que existem, com os nomes de env associados. Uma lista
mantida à mão divergiria na primeira chave nova — e divergiria em silêncio,
emitindo um arquivo que descreve uma configuração que ninguém lê.

O sandbox das venues não passa por esses getters, então ele é resolvido à
parte, pelo mesmo `resolve_sandbox` que a ordem usa.

## Segredo

Nunca sai. A garantia não é uma filtragem da saída: é que as únicas chaves
emitidas são as que o `Settings` lê, e segredo nunca é lido de settings — o
arquivo declara só o *nome* da variável. A filtragem por `SECRET_ENV` existe no
relatório, que é outra coisa: lá o nome aparece, o valor não.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from workspace.config import Settings, load_settings
from workspace.venues.config import selected_venues
from workspace.venues.sandbox import resolve_sandbox, sandbox_settings_keys

__all__ = ["envs_do_projeto", "exportar", "formatar_relatorio"]


def _manifesto() -> Mapping[str, Any]:
    from workspace.settings_schema import SCHEMA_PATH

    caminho = SCHEMA_PATH.parent / "skill.json"
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # pragma: no cover - manifesto é versionado
        return {}


def envs_do_projeto() -> tuple[str, ...]:
    """Nomes de variável declarados no repositório, dos dois lugares.

    É lista versionada, não varredura do ambiente: sem ela o relatório listaria
    `PATH`, `HOME` e o resto do shell como "sem equivalente em settings", o que
    é verdade e é inútil.

    União de `skill.json` (115 nomes) com o `.env.example` (106): nenhum dos
    dois é completo sozinho -- `VOLUME_ORDER` está só no exemplo, e as variáveis
    de diagnóstico estão só no manifesto. Sub-reportar aqui é a direção cara:
    o operador conclui que cobriu tudo e apaga o `.env`.
    """
    from workspace.settings_schema import SCHEMA_PATH

    nomes = {str(n) for n in _manifesto().get("dependencies", {}).get("env", [])}
    exemplo = SCHEMA_PATH.parent / "workspace" / ".env.example"
    try:
        for linha in exemplo.read_text(encoding="utf-8").splitlines():
            crua = linha.strip().lstrip("#").strip()
            if "=" in crua:
                nome = crua.split("=", 1)[0].strip()
                if nome.isupper() and nome.replace("_", "").isalnum():
                    nomes.add(nome)
    except OSError:  # pragma: no cover - o exemplo é versionado
        pass
    return tuple(sorted(nomes))


# Os getters coagidos, e nao `_require`. Espionar `_require` devolvia o valor
# **cru** (a string `"7"` do ambiente, nao o int `7`) e, pior, capturava as
# sondagens de presenca: `setups.py` chama o getter com um sentinela proprio
# como `default` para distinguir "ausente" de "declarado", e `_require` devolve
# esse sentinela -- que virava o valor exportado.
_GETTERS = ("get_bool", "get_int", "get_float", "get_str", "get_list", "get_json")

# So o que o JSON representa. O sentinela de sondagem e um `object()` nu, entao
# este filtro tambem o descarta.
_EXPORTAVEL = (bool, int, float, str, list, tuple)


def _exportavel(valor: Any) -> bool:
    """O JSON representa este valor?

    A garantia vive em `_montar`, e nao so no coletor: la ela e uma funcao pura
    que o teste exercita com um sentinela direto. No coletor ela seria um
    filtro cujo defeito so aparece se existir uma chave que e **apenas**
    sondada -- condicao que hoje nao ocorre, entao a mutacao que removia o
    filtro sobrevivia.
    """
    return isinstance(valor, _EXPORTAVEL)


def _colher_chaves(cfg: Settings) -> list[tuple[str, tuple[str, ...], Any]]:
    """`(chave pontilhada, envs associadas, valor efetivo)` de cada setup.

    Espiona os getters enquanto `validate_setup_settings` roda. Ela ja exercita
    todos eles -- e o que ela existe para fazer --, entao a colheita acompanha
    o codigo sem lista paralela.
    """
    from workspace.core.setups import validate_setup_settings

    colhidas: list[tuple[str, tuple[str, ...], Any]] = []
    originais = {nome: getattr(Settings, nome) for nome in _GETTERS}

    def faz_espiao(original):
        def espiao(self, dotted, *, env=None, **kwargs):  # type: ignore[no-untyped-def]
            valor = original(self, dotted, env=env, **kwargs)
            if isinstance(valor, _EXPORTAVEL) and not isinstance(valor, type):
                nomes = (env,) if isinstance(env, str) else tuple(env or ())
                colhidas.append((dotted, nomes, valor))
            return valor

        return espiao

    for nome, original in originais.items():
        setattr(Settings, nome, faz_espiao(original))
    try:
        validate_setup_settings(settings=cfg)
    finally:
        for nome, original in originais.items():
            setattr(Settings, nome, original)
    return colhidas


def _enfiar(destino: dict, dotted: str, valor: Any) -> None:
    partes = dotted.split(".")
    no = destino
    for parte in partes[:-1]:
        no = no.setdefault(parte, {})
    no[partes[-1]] = valor


def _normalizar(valor: Any) -> Any:
    """Tupla vira lista, e lista toda numerica vira numerica.

    `get_list` devolve `[str(item)]` por contrato, entao a escada de alvos saia
    como `["1.0", "1.5"]` onde o `settings.example.json` traz `[1.0, 1.5]`. O
    produto deste comando e um arquivo feito para uma pessoa ler e editar;
    emitir um dialeto diferente do exemplo que documentamos convida a editar
    errado.

    A conversao e segura porque `get_list` re-stringifica na leitura -- ha
    teste de round-trip para isso. E vale para a lista **inteira** ou para
    nenhuma: converter item a item produziria uma lista mista, pior que
    qualquer um dos dois lados.
    """
    if isinstance(valor, (list, tuple)):
        itens = list(valor)
        try:
            numeros = [float(item) for item in itens]
        except (TypeError, ValueError):
            return itens
        return numeros if itens else itens
    return valor


def _montar(entradas) -> dict[str, Any]:
    """Monta o dict a partir das entradas colhidas, primeira leitura vencendo.

    O preenchimento e last-wins por natureza, e o mesmo `dotted` pode ser lido
    mais de uma vez na mesma execucao: `setups.py` sonda presenca chamando o
    getter com um sentinela proprio como `default`. Hoje o filtro de tipo em
    `_colher_chaves` descarta essa segunda leitura antes de chegar aqui, mas
    depender disso deixa a regra implicita num filtro que existe por outro
    motivo -- e foi exatamente assim que a sondagem sobrescreveu o valor bom
    quando o filtro saiu do lugar.
    """
    destino: dict[str, Any] = {}
    vistas: set[str] = set()
    for dotted, _nomes, valor in entradas:
        if dotted in vistas or not _exportavel(valor):
            continue
        vistas.add(dotted)
        _enfiar(destino, dotted, _normalizar(valor))
    return destino


def _sandbox_das_venues(cfg: Settings) -> list[tuple[str, tuple[str, ...], Any]]:
    """Sandbox das venues selecionadas, pela chave mais específica.

    Pelo mesmo `resolve_sandbox` que a ordem usa: emitir aqui um valor obtido
    de outro jeito devolveria o problema que a fase inteira acabou de fechar --
    duas respostas para a mesma pergunta.
    """
    from workspace.venues.sandbox import sandbox_env_names

    selecao = selected_venues()
    saida = []
    for tipo, venue in (("cex", selecao.cex_id), ("dex", selecao.dex_id)):
        try:
            valor = resolve_sandbox(tipo, venue, settings=cfg)
        except Exception:
            # Config ilegível já é reportada por `setup-check`/`venues`; aqui
            # ela só significa que este campo não entra no arquivo exportado.
            continue
        saida.append((sandbox_settings_keys(tipo, venue)[0], sandbox_env_names(tipo, venue), valor))
    return saida


def exportar(*, settings: Settings | None = None, ambiente: Mapping[str, str] | None = None):
    """`(settings equivalente, relatório)`.

    `ambiente` existe para o teste: por padrão usa o `os.environ` que o
    `Settings` já carregou, para o relatório falar do mesmo ambiente que o
    export leu.
    """
    import os

    cfg = load_settings() if settings is None else settings
    env = dict(os.environ if ambiente is None else ambiente)

    entradas = _colher_chaves(cfg) + _sandbox_das_venues(cfg)

    envs_com_equivalente: set[str] = set()
    envs_que_vencem: list[str] = []
    exportado = _montar(entradas)
    for dotted, nomes, valor in entradas:
        for nome in nomes:
            envs_com_equivalente.add(nome)
            if env.get(nome) and nome not in envs_que_vencem:
                envs_que_vencem.append(nome)

    from workspace.run import SECRET_ENV

    segredos = [nome for nome in SECRET_ENV if env.get(nome)]
    sem_equivalente = [
        nome
        for nome in envs_do_projeto()
        if env.get(nome) and nome not in envs_com_equivalente and nome not in SECRET_ENV
    ]

    avisos = [
        "Este arquivo NAO substitui o seu .env: ele cobre apenas o que ja tem "
        "equivalente em settings.",
    ]
    if envs_que_vencem:
        avisos.append(
            "As variaveis abaixo VENCEM o arquivo por desenho (ambiente > "
            "settings). Enquanto elas existirem no ambiente, o que voce acabou "
            "de exportar nao tem efeito nenhum -- remova-as do .env para o "
            "settings passar a valer."
        )
    if segredos:
        avisos.append(
            "Segredo nunca entra no settings: as credenciais continuam no "
            "ambiente/secret manager, e os nomes abaixo sao so para conferencia."
        )

    relatorio = {
        "chaves_exportadas": sorted(dotted for dotted, _, _ in entradas),
        "envs_que_vencem_o_arquivo": envs_que_vencem,
        "sem_equivalente_em_settings": sem_equivalente,
        "segredos_definidos": segredos,
        "avisos": avisos,
    }
    return exportado, relatorio


def formatar_relatorio(relatorio: Mapping[str, Any]) -> str:
    """Texto para a stderr. A stdout é só o JSON, para o redirecionamento
    `config-export > settings.json` produzir um arquivo válido."""
    linhas = [f"config-export: {len(relatorio['chaves_exportadas'])} chaves exportadas.", ""]
    for aviso in relatorio["avisos"]:
        linhas.append(f"AVISO: {aviso}")
    for titulo, chave in (
        ("Continuam vencendo o arquivo", "envs_que_vencem_o_arquivo"),
        ("Sem equivalente em settings (continuam so no ambiente)", "sem_equivalente_em_settings"),
        ("Segredos definidos (ficam onde estao)", "segredos_definidos"),
    ):
        nomes = relatorio[chave]
        if nomes:
            linhas.append("")
            linhas.append(f"{titulo}:")
            linhas.extend(f"  - {nome}" for nome in nomes)
    return "\n".join(linhas)
