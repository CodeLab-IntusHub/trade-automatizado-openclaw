"""Conversoes de ponto fixo da Nado, sem depender do SDK.

Sao aritmetica pura. Moram aqui, e nao em `nado_integration`, para que quem
so precisa converter um valor nao precise ter `nado-protocol` instalado.
"""

from __future__ import annotations

__all__ = ["from_x18", "from_x6"]


def from_x18(value) -> float:
    """Converte um valor x18 (string ou int) para float."""
    return int(value) / 1e18


def from_x6(value) -> float:
    """Converte um valor x6 (string ou int) para float."""
    return int(value) / 1e6
