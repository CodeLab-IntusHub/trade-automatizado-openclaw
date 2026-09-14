"""Resolucao unica de `sandbox` por venue.

`sandbox` decide se a ordem vai para dinheiro de brinquedo ou para dinheiro
real. Antes desta modulo a mesma pergunta era respondida em quatro lugares com
regras diferentes -- precedencia invertida entre dois deles, vocabulario que so
definia o lado verdadeiro (entao `ture` resolvia para producao em silencio) e
duas copias que devolviam string crua sem normalizar nada.

O contrato, do mais forte para o mais fraco:

1. env especifica da venue (`BINANCE_SANDBOX`)
2. env generica do tipo (`CEX_SANDBOX` / `DEX_SANDBOX`)
3. settings por venue (`venues.cex.binance.sandbox`)
4. settings do tipo (`venues.cex.sandbox`)
5. default

Camada e especificidade sao eixos separados e nesta ordem: **ambiente vence
arquivo** (o contrato do `workspace.config`) e, dentro de cada camada, **o mais
especifico vence o generico**. Colapsar os dois eixos faria uma chave de
arquivo por venue derrubar uma env generica, o que contradiz a precedencia
documentada do resto do sistema.

Valor fora do vocabulario levanta `ConfigError` em vez de virar falso -- ver
`workspace.config.get_bool`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - apenas para anotacao
    from workspace.config import Settings

__all__ = [
    "SANDBOX_GENERIC_ENV",
    "default_sandbox",
    "resolve_sandbox",
    "sandbox_env_names",
    "sandbox_settings_keys",
]

SANDBOX_GENERIC_ENV = {"cex": "CEX_SANDBOX", "dex": "DEX_SANDBOX"}

# Unica venue que nasce apontada para sandbox. A assimetria e deliberada: a
# Kraken tem ambiente demo estavel e publico, o resto das CEXs nao tem
# equivalente confiavel, entao um default `true` generico prometeria uma
# protecao que a corretora nao entrega.
_SANDBOX_BY_DEFAULT_PREFIXES = ("kraken",)

# Envs de familia: um grupo de ids que compartilha uma env intermediaria, mais
# especifica que a generica do tipo e menos que a da propria venue. Existe
# porque `KRAKEN_SANDBOX` ja e usada assim -- ela vale para `kraken`,
# `krakenfutures` e `kraken-spot`. Sem representar isso aqui, migrar o helper
# faria `KRAKEN_SANDBOX` parar de valer para as variantes, em silencio.
_FAMILY_ENV_PREFIXES = ("KRAKEN",)


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


def sandbox_env_names(kind: str, venue_id: str) -> tuple[str, ...]:
    """Envs consultadas, da mais especifica para a mais generica.

    Normalmente duas: a da venue e a do tipo. Para uma venue de familia
    conhecida entra uma terceira no meio (ver `_FAMILY_ENV_PREFIXES`).
    """
    prefix = venue_prefix(venue_id)
    names = [f"{prefix}_SANDBOX"]
    for family in _FAMILY_ENV_PREFIXES:
        if prefix.startswith(family):
            names.append(f"{family}_SANDBOX")
    names.append(SANDBOX_GENERIC_ENV[_kind(kind)])
    # dedup preservando ordem: `kraken` gera o mesmo nome duas vezes
    return tuple(dict.fromkeys(names))


def sandbox_settings_keys(kind: str, venue_id: str) -> tuple[str, str]:
    """`(por_venue, do_tipo)`, na ordem de precedencia."""
    key = _kind(kind)
    slug = (venue_id or "").strip().lower()
    generic = f"venues.{key}.sandbox"
    return (f"venues.{key}.{slug}.sandbox" if slug else generic), generic


def default_sandbox(kind: str, venue_id: str) -> bool:
    _kind(kind)
    return (venue_id or "").strip().lower().startswith(_SANDBOX_BY_DEFAULT_PREFIXES)


def resolve_sandbox(
    kind: str,
    venue_id: str,
    *,
    settings: "Settings | None" = None,
    default: bool | None = None,
) -> bool:
    """Veredito unico de sandbox para uma venue.

    `settings` entra por parametro para que teste e chamador injetem sem mexer
    em variavel de ambiente global. `default` sobrescreve o default da venue
    para quem ja o deriva de outra config -- a Hyperliquid o tira da rede
    selecionada (`testnet` implica sandbox), e perder isso mandaria quem esta
    em testnet para producao.
    """
    from workspace.config import load_settings

    cfg = load_settings() if settings is None else settings
    env_names = sandbox_env_names(kind, venue_id)
    by_venue, by_kind = sandbox_settings_keys(kind, venue_id)

    declared = cfg.has_env(*env_names)
    if declared is not None:
        # Uma env so: passar as duas deixaria o `get_bool` reordenar por conta
        # propria e o erro apontaria a chave errada.
        return cfg.get_bool(by_kind, env=declared)

    for dotted in (by_venue, by_kind):
        if cfg.origin(dotted).layer != "default":
            return cfg.get_bool(dotted)

    return default_sandbox(kind, venue_id) if default is None else default
