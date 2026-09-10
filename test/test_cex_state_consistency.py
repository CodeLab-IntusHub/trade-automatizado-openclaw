"""Estado nao pode registrar stop nativo que a corretora nao tem mais."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("ccxt", reason="ccxt e dependencia base; ausente so em ambiente local incompleto")

import workspace.cli as cli  # noqa: E402


def test_falha_na_troca_limpa_a_referencia_do_stop_cancelado() -> None:
    """`replace_stop_loss` cancela antes de criar. Se a criacao falha, a
    referencia antiga aponta para uma ordem morta -- e o ciclo seguinte tenta
    cancelar esse id de novo, gerando OrderNotFound sobre o erro real."""
    state = SimpleNamespace(
        metadata={"native_orders": {"kraken": {"sl": {"id": "old-sl", "tracked": True}}}}
    )
    assert cli._role_stop_order_ref(state, "kraken").get("id") == "old-sl"

    cli._invalidate_native_stop_ref(state, "kraken", reason="replace_failed")

    ref = cli._role_stop_order_ref(state, "kraken")
    assert not ref.get("id"), "a referencia morta tem de sair do estado"
    assert ref.get("tracked") is False
    assert ref.get("invalidated_reason") == "replace_failed"


def test_invalidar_referencia_e_seguro_em_estado_sem_ordens() -> None:
    for metadata in ({}, {"native_orders": None}, {"native_orders": {"kraken": {}}}):
        cli._invalidate_native_stop_ref(SimpleNamespace(metadata=metadata), "kraken", reason="x")
