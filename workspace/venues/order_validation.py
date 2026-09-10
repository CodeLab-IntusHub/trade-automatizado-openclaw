"""Confirmacao de ordem de protecao, compartilhada pelos adapters de venue.

Os chamadores de `place_stop_loss`/`place_take_profit` so testam
`if order is None`. Sem esta checagem, qualquer objeto devolvido pela corretora
-- inclusive uma rejeicao estruturada -- conta como "protecao anexada", e a
posicao fica sem stop sem que nada registre isso.

Mora num modulo proprio porque os tres adapters (generico CCXT, Hyperliquid e
Kraken) tem o mesmo problema; uma copia por adapter garantiria que as copias
divergissem.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "REJECTED_ORDER_STATUS",
    "UnconfirmedOrderError",
    "VenueCapabilityError",
    "validate_order_response",
    "wrap_replace_failure",
]

# Denylist, nao allowlist: o CCXT repassa status nao mapeados das venues
# ("active", "triggered", "working"...). Uma allowlist rejeitaria ordem aceita
# -- o chamador marcaria a posicao como desprotegida e um retry anexaria um
# segundo stop para a mesma quantidade.
REJECTED_ORDER_STATUS = frozenset({"canceled", "cancelled", "rejected", "expired", "failed"})


class VenueCapabilityError(RuntimeError):
    """A venue nao confirmou a operacao, ou nao consegue executa-la.

    Existe para que "a corretora nao confirmou" nunca seja confundido com
    sucesso. Todo caminho que protege posicao levanta isto em vez de seguir.
    """


class UnconfirmedOrderError(VenueCapabilityError):
    """A ordem pode ter sido criada, mas o bot nao consegue rastrea-la.

    Distinto de "nao existe": quem trata isto nao pode recomendar retry, que
    empilharia uma segunda ordem sobre uma viva e invisivel.
    """


def validate_order_response(response: Any, *, exchange_id: str, what: str) -> dict[str, Any]:
    """Confirma que a corretora aceitou a ordem de protecao."""
    if not isinstance(response, dict):
        raise VenueCapabilityError(
            f"{exchange_id} nao confirmou {what}: resposta inesperada ({type(response).__name__})"
        )
    status = str(response.get("status") or "").lower()
    if status in REJECTED_ORDER_STATUS:
        raise VenueCapabilityError(
            f"{exchange_id} rejeitou {what}: status={status!r} (ordem {response.get('id')})"
        )
    if not response.get("id"):
        # Sem id nao da para cancelar nem substituir depois. Tratar como
        # sucesso deixaria um stop possivelmente vivo e irrastreavel.
        raise UnconfirmedOrderError(
            f"{exchange_id} nao devolveu id para {what}: a ordem PODE ter sido criada "
            "e este bot nao consegue rastrea-la. Confira as ordens abertas na corretora "
            "antes de tentar de novo -- uma nova tentativa empilharia um segundo stop."
        )
    return response


def wrap_replace_failure(exc: BaseException, *, symbol: object, cancelled_order_id: str) -> VenueCapabilityError:
    """Erro de substituicao de stop, deixando claro que a posicao ficou nua.

    `replace_stop_loss` cancela o stop vivo antes de criar o novo. Sem este
    aviso o log diz apenas que a troca falhou -- e nao que a posicao ficou sem
    stop nenhum, que e a parte urgente.
    """
    if isinstance(exc, UnconfirmedOrderError):
        # Caso ambiguo: pode haver um stop novo, vivo e sem id. Nao afirmar
        # ausencia nem mandar retentar -- as duas coisas causariam dano.
        return UnconfirmedOrderError(f"{exc} | O stop anterior ({cancelled_order_id}) ja foi cancelado.")
    return VenueCapabilityError(
        f"{type(exc).__name__}: {exc} | ATENCAO: o stop anterior ({cancelled_order_id}) "
        f"JA FOI CANCELADO, entao {symbol} esta sem stop na corretora ate uma nova "
        "tentativa ter sucesso."
    )
