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
3. default da venue

**Camada e especificidade sao eixos separados:** ambiente vence arquivo (o
contrato do `workspace.config`), `settings.local.json` vence `settings.json`, e
dentro de cada camada o mais especifico vence o generico. Camada e o eixo
externo. A primeira versao deste modulo colapsava os dois na varredura de
arquivo, e uma chave por venue do arquivo do time derrubava uma chave generica
do arquivo do operador -- o oposto do que o resto do sistema promete.

A Hyperliquid ainda nao consome este modulo: ela deriva sandbox da rede
selecionada (`HYPERLIQUID_NETWORK`), o que exige um degrau proprio na camada de
ambiente. Isso vem na fatia seguinte, junto com o caller -- misturar as duas
coisas foi o que obrigou a fatiar.

Valor fora do vocabulario levanta `ConfigError` em vez de virar falso -- ver
`workspace.config.get_bool`.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from workspace.config import FILE_LAYERS, ConfigError

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
# So entram familias cujas *variantes* precisam herdar. `hyperliquid` ja entra
# embora nenhum caller `dex` use o resolvedor nesta fatia: sem ela,
# `HYPERLIQUID_SANDBOX` fica inalcancavel para os ids `hyperliquid-dex` e
# `hyperliquid_dex`, que sao selecoes aceitas -- um bug inerte hoje e vivo no
# minuto em que a fatia seguinte ligar o caller, sem teste para pega-lo.
# `nado` nao entra porque o adapter dela e construido so a partir de
# `NADO_NETWORK` e nunca chama este resolvedor. Isso nao torna `NADO_SANDBOX`
# inexistente -- para o id `nado` a cadeia gera o nome como para qualquer
# venue; apenas nada o consulta.
_VENUE_FAMILIES = ("kraken", "hyperliquid")

# Familias que nascem apontadas para sandbox. Assimetria deliberada: a Kraken
# tem ambiente demo estavel e publico, o resto das CEXs nao tem equivalente
# confiavel, entao um default `true` generico prometeria uma protecao que a
# corretora nao entrega.
_SANDBOX_BY_DEFAULT = frozenset({"kraken"})

_LAYER_RANK = {name: rank for rank, name in enumerate(FILE_LAYERS)}

_logger = logging.getLogger(__name__)


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


def _settings_slugs(venue_id: str) -> tuple[str, ...]:
    """Grafias aceitas de um id para chave de settings.

    O nome de env colapsa pontuacao (`kraken-futures` e `kraken_futures` dao o
    mesmo `KRAKEN_FUTURES_SANDBOX`), mas a chave de arquivo usava o slug cru --
    entao declarar com uma grafia e selecionar a outra caia calado na chave
    generica. As duas passam a valer, com a grafia escrita vencendo.
    """
    slugs = []
    for venue in venue_chain(venue_id):
        slugs.append(venue)
        canonico = venue_prefix(venue).lower().replace("_", "-")
        if canonico != venue:
            slugs.append(canonico)
    return tuple(dict.fromkeys(slugs))


def sandbox_settings_keys(kind: str, venue_id: str) -> tuple[str, ...]:
    """Chaves de settings, da mais especifica para a mais generica."""
    key = _kind(kind)
    keys = [f"venues.{key}.{v}.sandbox" for v in _settings_slugs(venue_id)]
    keys.append(f"venues.{key}.sandbox")
    return tuple(dict.fromkeys(keys))


def default_sandbox(kind: str, venue_id: str) -> bool:
    _kind(kind)
    return any(v in _SANDBOX_BY_DEFAULT for v in venue_chain(venue_id))


def _best_settings_key(cfg: "Settings", keys: tuple[str, ...]) -> str | None:
    """Chave declarada mais forte, com camada como eixo externo.

    Ordenar so por especificidade faria o arquivo do time vencer o do
    operador; ordenar so por camada ignoraria a familia.

    Quando a vencedora e **menos** especifica que outra declarada, avisa: e o
    caso em que um `venues.cex.sandbox: false` generico no arquivo do operador
    engole um `venues.cex.kraken.sandbox: true` explicito do time. A ordem
    continua valendo -- o arquivo do operador manda --, mas perder uma
    declaracao de seguranca em silencio nao.
    """
    declared: list[tuple[tuple[int, int], str]] = []
    for specificity, dotted in enumerate(keys):
        layer = _LAYER_RANK.get(cfg.origin(dotted).layer)
        if layer is None:  # veio do default: nao foi declarada em arquivo
            continue
        declared.append(((layer, specificity), dotted))
    if not declared:
        return None
    declared.sort()
    (_, winner_specificity), winner = declared[0]
    for (_, specificity), dotted in declared[1:]:
        if specificity >= winner_specificity:
            continue
        # So avisa quando os valores de fato divergem. Avisar com os dois
        # iguais nao relata perda nenhuma e, num aviso de seguranca, treina o
        # operador a ignora-lo.
        try:
            if cfg.get_bool(winner) == cfg.get_bool(dotted):
                continue
        except ConfigError:
            pass  # valor ilegivel: quem resolve levanta com a mensagem certa
        _logger.warning(
            "sandbox: %s (%s) prevalece sobre %s (%s), que e mais especifica e "
            "declara o oposto. A camada mais forte vence; confira se era isso "
            "que voce queria.",
            winner, cfg.origin(winner).layer, dotted, cfg.origin(dotted).layer,
        )
        break
    return winner


def _avisa_se_engoliu_declaracao(
    cfg: "Settings",
    declared_env: str,
    env_names: tuple[str, ...],
    keys: tuple[str, ...],
    valor: bool,
) -> None:
    """Avisa quando uma env vence uma chave de arquivo **mais especifica**.

    `_best_settings_key` cobre a inversao entre arquivos; esta cobre a
    fronteira ambiente/arquivo, que e o caso de migracao mais provavel: ate
    esta fatia `CEX_SANDBOX` vinha descomentada no `.env.example`, entao todo
    operador atual tem essa env generica no `.env`. Ele segue a documentacao
    nova, declara `venues.cex.<venue>.sandbox` no arquivo -- e a declaracao
    seria descartada em silencio.
    """
    especificidade_env = env_names.index(declared_env)
    if especificidade_env == 0:
        return  # a env ja e a mais especifica que existe
    for especificidade, dotted in enumerate(keys):
        if especificidade >= especificidade_env:
            break
        if cfg.origin(dotted).layer == "default":
            continue
        try:
            if cfg.get_bool(dotted) == valor:
                continue
        except ConfigError:
            pass
        _logger.warning(
            "sandbox: a variavel de ambiente %s prevalece sobre %s (%s), que e "
            "mais especifica e declara o oposto. Ambiente sempre vence arquivo; "
            "para o arquivo valer, remova a variavel do seu .env.",
            declared_env, dotted, cfg.origin(dotted).layer,
        )
        break


def resolve_sandbox(
    kind: str,
    venue_id: str,
    *,
    settings: "Settings | None" = None,
) -> bool:
    """Veredito unico de sandbox para uma venue.

    `settings` entra por parametro para que teste e chamador injetem sem mexer
    em variavel de ambiente global.
    """
    from workspace.config import load_settings

    cfg = load_settings() if settings is None else settings
    keys = sandbox_settings_keys(kind, venue_id)

    env_names = sandbox_env_names(kind, venue_id)
    declared_env = cfg.has_env(*env_names)
    if declared_env is not None:
        # A env vai como chave: `get_bool` nomeia o que recebe, e o operador
        # precisa ler o nome que ele mesmo definiu. Passar a chave pontilhada
        # apontava para um caminho de arquivo que podia nem existir.
        valor = cfg.get_bool(declared_env, env=declared_env)
        _avisa_se_engoliu_declaracao(cfg, declared_env, env_names, keys, valor)
        return valor

    chosen = _best_settings_key(cfg, keys)
    if chosen is not None:
        return cfg.get_bool(chosen)

    return default_sandbox(kind, venue_id)
