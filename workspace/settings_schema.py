"""Chave desconhecida no settings deixa de ser ignorada.

Até esta versão, um typo no nome de uma chave não produzia erro nenhum: a
chave não era lida, o código caía no default e o operador via o comando rodar
achando que a configuração dele valia. Medido:

    venues.cex.binance.sandbxo: true   -> resolvido False   produção
    venues.cex.binanse.sandbox: true   -> resolvido False   produção
    setups.triangle-breakout.pivot_windwo: 9 -> efetivo 2 (o default)

`validate_setup_settings` passava por todos: ela valida os **valores** das
chaves que conhece, e um typo produz uma chave que ela não conhece.

Isto é a contrapartida da fatia que tirou as variáveis de ambiente da
documentação. Passar a instruir o operador a escrever
`venues.cex.binance.sandbox` num arquivo, sem nada conferir o que ele
escreveu, troca um modo de falha silenciosa por outro.

## Por que não `jsonschema`

O vocabulário aqui é pequeno e o valor da validação está quase todo na
**mensagem**: apontar a chave, o caminho e a grafia provável. Uma dependência
nova no `requirements.txt` teria custo de supply-chain para entregar uma
mensagem pior. O schema continua sendo **dado** (`settings.schema.json`,
legível pelo operador); só o caminhador é código.

## A direção perigosa

O risco desta mudança não é deixar passar um typo — é **recusar configuração
legítima**. Um schema incompleto derruba o boot de quem seguiu a documentação,
trocando uma falha silenciosa por uma barulhenta e errada. Duas defesas, ambas
em `test/test_schema_de_settings.py`: o `settings.example.json` tem que passar,
e um espião em `Settings._require` registra toda chave que os getters de setup
pedem e exige que o schema aceite cada uma.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from workspace.config import ConfigError

__all__ = ["SCHEMA_PATH", "validar_settings", "venues_conhecidas"]

# Deliberadamente **nao** derivado de `config.REPO_ROOT`. Aquela constante
# aponta para onde o settings do operador e procurado, e o teste a redireciona
# para um diretorio falso; o schema e arquivo versionado que viaja junto do
# codigo. Amarrado ao `REPO_ROOT`, ele passava na suite so por acidente de
# ordem de import -- e sumia assim que alguem importasse este modulo depois do
# patch, derrubando o `setup_check` inteiro.
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "settings.schema.json"

# Variantes internas que o código aceita como id de venue e que não existem em
# `ccxt.exchanges`: são seleções nossas (família e sufixo de mercado), não
# exchanges. Sem elas, `venues.cex.kraken-spot.sandbox` -- grafia que o próprio
# `cli._is_builtin_kraken_cex` aceita -- viraria erro.
_VARIANTES_INTERNAS = frozenset({
    "kraken", "kraken-spot", "kraken_spot", "krakenfutures", "kraken-futures", "kraken_futures",
    "hyperliquid", "hyperliquid-dex", "hyperliquid_dex",
    "nado", "nado-dex", "nado_dex",
})


@lru_cache(maxsize=1)
def venues_conhecidas() -> frozenset[str]:
    """Ids de venue aceitos: os do CCXT mais as variantes internas.

    O CCXT é a fonte da verdade para a CEX genérica -- id fora de
    `ccxt.exchanges` não constrói adapter nenhum, então a chave estaria morta
    de qualquer forma. Se o CCXT não importar, devolve só as variantes e o
    domínio vira permissivo (ver `_nome_livre_invalido`): recusar venue por
    causa de um import que falhou seria pior que deixar passar.
    """
    try:
        import ccxt
    except Exception:  # pragma: no cover - ccxt é dependência base
        return frozenset(_VARIANTES_INTERNAS)
    ids = {str(nome).lower() for nome in getattr(ccxt, "exchanges", ())}
    return frozenset(ids | _VARIANTES_INTERNAS)


@lru_cache(maxsize=1)
def _schema() -> Mapping[str, Any]:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["raiz"]
    except FileNotFoundError as exc:  # pragma: no cover - arquivo é versionado
        raise ConfigError(
            f"schema de settings ausente em {SCHEMA_PATH}. Ele é versionado; "
            "reinstale a skill ou restaure o arquivo."
        ) from exc


def _e_comentario(nome: str) -> bool:
    return nome.startswith("_comentario")


def _sugestao(nome: str, candidatos) -> str:
    """`n=1, cutoff=0.6`: sugerir demais é pior que não sugerir.

    Uma sugestão errada manda o operador trocar uma chave morta por outra
    chave morta, e ele sai convencido de que conferiu.
    """
    perto = difflib.get_close_matches(nome.lower(), sorted(candidatos), n=1, cutoff=0.6)
    return f" Você quis dizer '{perto[0]}'?" if perto else ""


def _aceitos(no: Mapping[str, Any]) -> list[str]:
    return sorted(set(no.get("campos", [])) | set(no.get("filhos", {})))


def _nome_livre_invalido(nome: str, dominio: str | None) -> str | None:
    """Valida o nome de uma chave de nível aberto. `None` = aceita.

    Só a CEX é fechada. O DEX fica aberto de propósito: `DEX_ADAPTER_MODULE`
    permite adapter próprio, e o id dele é do operador -- fechar aqui
    recusaria configuração legítima, que é a direção cara do erro.
    """
    if dominio != "cex":
        return None
    conhecidas = venues_conhecidas()
    if len(conhecidas) == len(_VARIANTES_INTERNAS):
        return None  # ccxt indisponível: não há lista contra a qual julgar
    if nome.lower() in conhecidas:
        return None
    return (
        f"venue desconhecida '{nome}': não está em ccxt.exchanges nem entre as "
        f"variantes aceitas.{_sugestao(nome, conhecidas)}"
    )


def _no_do_filho(no: Mapping[str, Any], nome: str) -> Mapping[str, Any] | None:
    filho = no.get("filhos", {}).get(nome)
    if filho is not None:
        return filho
    for padrao, destino in no.get("padroes", {}).items():
        if re.match(padrao, nome):
            return destino
    return None


def _caminhar(valor: Any, no: Mapping[str, Any], caminho: str, origem: str, erros: list[str]) -> None:
    if not isinstance(valor, Mapping):
        return
    campos = set(no.get("campos", []))
    livre = no.get("livre")
    for nome, sub in valor.items():
        if _e_comentario(nome):
            continue
        onde = f"{caminho}.{nome}" if caminho else nome

        filho = _no_do_filho(no, nome)
        if filho is not None:
            _caminhar(sub, filho, onde, origem, erros)
            continue

        if nome in campos:
            continue

        if livre is not None and isinstance(sub, Mapping):
            problema = _nome_livre_invalido(nome, livre.get("dominio"))
            if problema:
                erros.append(f"{origem}: em '{caminho or '(raiz)'}', {problema}")
                continue
            _caminhar(sub, livre.get("no", {}), onde, origem, erros)
            continue

        aceitos = _aceitos(no)
        detalhe = f" Aceitas em '{caminho or '(raiz)'}': {aceitos}." if aceitos else ""
        erros.append(
            f"{origem}: chave desconhecida '{onde}'.{_sugestao(nome, aceitos)}{detalhe}"
        )


def validar_settings(payload: Any, *, origem: str) -> list[str]:
    """Problemas encontrados, um por chave. Lista vazia = válido.

    Devolve em vez de levantar para que o chamador decida: o boot derruba, e os
    comandos de diagnóstico reportam sem trocar o relatório inteiro por um
    traceback -- eles são rodados justamente quando algo está errado.

    `origem` é o nome do arquivo. Com dois arquivos na precedência, dizer
    "chave desconhecida" sem dizer em qual deles manda o operador procurar no
    lugar errado.
    """
    erros: list[str] = []
    _caminhar(payload, _schema(), "", origem, erros)
    return erros


def exigir_settings_valido(cfg) -> None:
    """Derruba o comando se qualquer camada de arquivo tiver chave desconhecida.

    Chamada no boot, junto de `validate_setup_settings`: o valor de descobrir
    o typo está em descobri-lo antes do primeiro ciclo, não depois de uma
    ordem sair com a configuração que o operador achava que tinha mudado.
    """
    problemas = [
        erro
        for nome, payload in cfg.camadas_de_arquivo()
        for erro in validar_settings(payload, origem=nome)
    ]
    if problemas:
        raise ConfigError(
            "configuração com chave desconhecida — ela seria ignorada em "
            "silêncio, e o valor usado seria o default:\n  - "
            + "\n  - ".join(problemas)
        )
