"""Resolucao unica de `sandbox` por venue.

`sandbox` decide se a ordem vai para dinheiro de brinquedo ou para dinheiro
real. Antes deste modulo a mesma pergunta era respondida em quatro lugares com
regras diferentes -- precedencia invertida entre dois deles, vocabulario que so
definia o lado verdadeiro (entao `ture` resolvia para producao em silencio) e
duas copias que devolviam string crua sem normalizar nada.

O contrato, do mais forte para o mais fraco:

1. env, da venue para a familia para o tipo
   (`KRAKENFUTURES_SANDBOX` -> `KRAKEN_SANDBOX` -> `CEX_SANDBOX`)
2. settings, camada por camada (`settings.local.json` antes de
   `settings.json`) e, dentro de cada uma, da venue para a familia para o tipo
   (`venues.cex.krakenfutures.sandbox` -> `venues.cex.kraken.sandbox` ->
   `venues.cex.sandbox`)
3. default derivado pelo chamador (`venue_default`)
4. default da venue

**Camada e especificidade sao eixos separados:** ambiente vence arquivo (o
contrato do `workspace.config`), `settings.local.json` vence `settings.json`, e
dentro de cada camada o mais especifico vence o generico. Camada e o eixo
externo. A primeira versao deste modulo colapsava os dois na varredura de
arquivo, e uma chave por venue do arquivo do time derrubava uma chave generica
do arquivo do operador -- o oposto do que o resto do sistema promete.

`venue_default` fica **abaixo de toda config declarada**, inclusive da chave
generica do tipo. Uma tentativa anterior o colocou acima dela, para proteger
quem escolheu testnet na Hyperliquid de um `venues.dex.sandbox: false` no
arquivo -- mas isso reintroduzia a mistura de eixos que o item 2 existe para
eliminar, e um proprio teste pegou a contradicao. Quem escreve a chave no
arquivo esta declarando, nao aceitando um default; e o mesmo tratamento que
`DEX_SANDBOX` sempre teve. O risco real era o **exemplo** distribuir esse
`false`, e ele deixou de distribuir.

Valor fora do vocabulario levanta `ConfigError` em vez de virar falso -- ver
`workspace.config.get_bool`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from workspace.config import FILE_LAYERS

if TYPE_CHECKING:  # pragma: no cover - apenas para anotacao
    from workspace.config import Settings

__all__ = [
    "SANDBOX_GENERIC_ENV",
    "default_sandbox",
    "resolve_sandbox",
    "sandbox_env_names",
    "sandbox_settings_keys",
    "venue_chain",
    "venue_prefix",
]

SANDBOX_GENERIC_ENV = {"cex": "CEX_SANDBOX", "dex": "DEX_SANDBOX"}

# Familias de venue: ids que compartilham um nivel intermediario, mais
# especifico que o generico do tipo e menos que o da propria venue. Vale para
# **env e para settings ao mesmo tempo** -- na primeira versao a familia
# existia so para env, e `venues.cex.kraken.sandbox` no arquivo nao alcancava
# `krakenfutures`, que caia na chave generica e ia para producao.
_VENUE_FAMILIES = ("kraken", "hyperliquid", "nado")

# Familias que nascem apontadas para sandbox. Assimetria deliberada: a Kraken
# tem ambiente demo estavel e publico, o resto das CEXs nao tem equivalente
# confiavel, entao um default `true` generico prometeria uma protecao que a
# corretora nao entrega.
_SANDBOX_BY_DEFAULT = frozenset({"kraken"})

_LAYER_RANK = {name: rank for rank, name in enumerate(FILE_LAYERS)}


def venue_prefix(venue_id: str) -> str:
    """Prefixo de env para uma venue.

    Colapsa qualquer pontuacao em `_`. Um dos helpers antigos fazia apenas
    `.upper().replace('-', '_')`, o que para `binance.us` produzia
    `BINANCE.US_SANDBOX` -- nome que nenhum shell exporta, deixando a env
    especifica inalcancavel sem que nada avisasse.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", venue_id or "").strip("_").upper()
    return cleaned or "VENUE"


def _kind(kind: str) -> str:
    key = (kind or "").strip().lower()
    if key not in SANDBOX_GENERIC_ENV:
        raise ValueError(f"tipo de venue desconhecido: {kind!r}. Use 'cex' ou 'dex'.")
    return key


def venue_chain(venue_id: str) -> tuple[str, ...]:
    """Ids a consultar, do mais especifico para o mais generico.

    `krakenfutures` -> `('krakenfutures', 'kraken')`, porque `KRAKEN_SANDBOX` e
    `venues.cex.kraken.sandbox` valem para a familia inteira.

    O casamento e por prefixo do nome de env, entao uma venue futura chamada
    `nadotrade` herdaria de `nado`. E o preco de nao manter uma tabela de
    variantes que envelhece a cada exchange nova; vale porque os ids reais sao
    do tipo `kraken-spot`, `hyperliquid_dex`.
    """
    slug = (venue_id or "").strip().lower()
    if not slug:
        return ()
    prefix = venue_prefix(slug)
    chain = [slug]
    chain.extend(
        family
        for family in _VENUE_FAMILIES
        if family != slug and prefix.startswith(venue_prefix(family))
    )
    return tuple(dict.fromkeys(chain))


def sandbox_env_names(kind: str, venue_id: str) -> tuple[str, ...]:
    """Envs consultadas, da mais especifica para a mais generica."""
    names = [f"{venue_prefix(v)}_SANDBOX" for v in venue_chain(venue_id)]
    names.append(SANDBOX_GENERIC_ENV[_kind(kind)])
    return tuple(dict.fromkeys(names))


def sandbox_settings_keys(kind: str, venue_id: str) -> tuple[str, ...]:
    """Chaves de settings, da mais especifica para a mais generica."""
    key = _kind(kind)
    keys = [f"venues.{key}.{v}.sandbox" for v in venue_chain(venue_id)]
    keys.append(f"venues.{key}.sandbox")
    return tuple(dict.fromkeys(keys))


def default_sandbox(kind: str, venue_id: str) -> bool:
    _kind(kind)
    return any(v in _SANDBOX_BY_DEFAULT for v in venue_chain(venue_id))


def _best_settings_key(cfg: "Settings", keys: tuple[str, ...]) -> str | None:
    """Chave declarada mais forte, com camada como eixo externo.

    Ordenar so por especificidade faria o arquivo do time vencer o do
    operador; ordenar so por camada ignoraria a familia.
    """
    best: tuple[tuple[int, int], str] | None = None
    for specificity, dotted in enumerate(keys):
        layer = _LAYER_RANK.get(cfg.origin(dotted).layer)
        if layer is None:  # veio do default: nao foi declarada em arquivo
            continue
        rank = (layer, specificity)
        if best is None or rank < best[0]:
            best = (rank, dotted)
    return None if best is None else best[1]


def resolve_sandbox(
    kind: str,
    venue_id: str,
    *,
    settings: "Settings | None" = None,
    venue_default: bool | None = None,
) -> bool:
    """Veredito unico de sandbox para uma venue.

    `settings` entra por parametro para que teste e chamador injetem sem mexer
    em variavel de ambiente global. `venue_default` e para quem deriva o valor
    de outra config explicita da mesma venue -- ver o cabecalho do modulo.
    """
    from workspace.config import load_settings

    cfg = load_settings() if settings is None else settings

    declared_env = cfg.has_env(*sandbox_env_names(kind, venue_id))
    if declared_env is not None:
        # A env vai como chave: `get_bool` nomeia o que recebe, e o operador
        # precisa ler o nome que ele mesmo definiu. Passar a chave pontilhada
        # apontava para um caminho de arquivo que podia nem existir.
        return cfg.get_bool(declared_env, env=declared_env)

    chosen = _best_settings_key(cfg, sandbox_settings_keys(kind, venue_id))
    if chosen is not None:
        return cfg.get_bool(chosen)

    if venue_default is not None:
        return venue_default

    return default_sandbox(kind, venue_id)
