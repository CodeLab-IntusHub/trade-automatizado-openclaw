"""O badge do `render_trade_chart.js` mostra a marca configurada, não uma fixa.

O renderer gera um HTML e tira um screenshot dele; o badge da imagem é o
`<div class="badge">` desse HTML. Os testes chamam o `html()` de verdade pelo
`node` — sem Chromium — com `SETUP_NOTIFY_BRAND` controlada, e leem o badge.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "workspace" / "render_trade_chart.js"
SINAL = {
    "symbol": "BTC/USDT",
    "side": "long",
    "setup": "bollinger-rsi",
    "timeframe": "1h",
    "entry_price": 100,
    "stop_price": 95,
    "targets": [105, 110],
}

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node ausente")


def _html(marca: str | None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "SETUP_NOTIFY_BRAND"}
    if marca is not None:
        env["SETUP_NOTIFY_BRAND"] = marca
    script = (
        "const { html } = require(process.argv[1]);"
        "process.stdout.write(html(JSON.parse(process.argv[2])));"
    )
    resultado = subprocess.run(
        ["node", "-e", script, str(RENDERER), json.dumps(SINAL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=True,
    )
    return resultado.stdout


def _badges(html: str) -> list[str]:
    return re.findall(r'<div class="badge">(.*?)</div>', html)


def test_o_badge_mostra_a_marca_configurada() -> None:
    assert _badges(_html("MARCA DE TESTE")) == ["MARCA DE TESTE"]


def test_sem_marca_configurada_nao_ha_badge() -> None:
    """Mesma regra do texto do sinal: marca vazia não é exibida."""
    html = _html(None)
    assert "<canvas" in html  # o HTML é gerado mesmo sem marca
    assert _badges(html) == []
    assert _badges(_html("   ")) == []


def test_a_marca_e_escapada() -> None:
    assert _badges(_html("<b>X</b>")) == ["&lt;b&gt;X&lt;/b&gt;"]


def test_nenhuma_marca_escrita_no_renderer() -> None:
    fonte = RENDERER.read_text(encoding="utf-8")
    for marca in ("INTUSCRIPTO", "ASPIRA"):
        assert marca not in fonte.upper(), f"marca fixa no renderer: {marca}"
