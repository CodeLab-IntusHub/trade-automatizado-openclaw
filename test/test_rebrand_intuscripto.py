"""O rebrand Aspira -> IntusCripto, e as três coisas que ele não pode arrastar.

"Aspira" era o nome do OpenClaw onde esta skill foi desenvolvida; o produto
hoje é IntusCripto. Renomear é legítimo — mas duas superfícies com `aspira` no
nome **espelham estado que vive fora deste repositório**, e renomeá-las aqui
troca uma inconsistência cosmética por uma quebra silenciosa:

1. **Caminhos de estado** (`~/.openclaw/state/aspira-trading-whatsapp-scanner*`)
   já existem na máquina de quem opera. Renomear faz o scanner não achar o
   estado anterior e recomeçar do zero, sem erro.
2. **`pine_title` / `*_layout_name`** nomeiam layouts e estudos que existem na
   conta TradingView, e o renderer casa por string
   (`tradingview_sandbox_render.js:145` derruba o render quando o `pine_title`
   não está no layout).
Havia uma terceira — o campo `schema` do sinal, preservado enquanto não se
sabia se algo lia o outbox. Em 24/09/2026 o autor confirmou que nada lê, e ele
passou a ter o nome novo; o teste abaixo agora trava o nome **novo**.

Estes testes existem porque as duas são invisíveis: nada falha na suíte se
alguém "terminar o rebrand" e arrastar as duas junto.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_caminhos_de_estado_nao_foram_renomeados() -> None:
    """Renomear perde o estado de quem já opera, em silêncio."""
    from workspace import trade_dashboard

    assert trade_dashboard.DEFAULT_WHATSAPP_SCANNER_LOG_PATH.name == (
        "aspira-trading-whatsapp-scanner.log"
    )
    assert trade_dashboard.DEFAULT_WHATSAPP_SCANNER_STATE_PATH.name == (
        "aspira-trading-whatsapp-scanner-state.json"
    )


def test_campos_que_espelham_o_tradingview_seguem_no_nome_antigo() -> None:
    """`pine_title` é casado contra o estudo presente no layout. Renomear aqui
    sem renomear no TradingView quebra o render."""
    payload = json.loads(
        (ROOT / "references" / "pine-setups" / "tradingview-managed-layouts.json")
        .read_text(encoding="utf-8")
    )
    espelhos = []
    for setup, layout in (payload.get("layouts") or {}).items():
        for campo in ("layout_name", "tradingview_actual_layout_name", "pine_title"):
            valor = layout.get(campo)
            if valor:
                espelhos.append((setup, campo, valor))
    assert espelhos, "nenhum campo-espelho encontrado -- o teste não exercita nada"
    renomeados = [e for e in espelhos if "IntusCripto" in e[2]]
    assert renomeados == [], (
        "campo que espelha a conta TradingView foi renomeado; o renderer casa "
        f"por string e vai falhar: {renomeados}"
    )


def test_schema_do_sinal_usa_o_nome_novo() -> None:
    """A terceira superficie, fechada quando se confirmou que nada le o outbox.
    Nao sobra campo de convivencia com o nome antigo."""
    from workspace.ccxt_entry_scanner import _structured_signal_call

    payload = _structured_signal_call(
        {"symbol": "ETH/USDT", "setup": "grid", "side": "long", "targets": [1, 2, 3, 4]}
    )
    assert payload["schema"] == "intuscripto.trading.signal_call.v1"
    assert "schema_canonico" not in payload


def test_os_pine_foram_renomeados_e_nao_sobrou_orfao() -> None:
    """A parte inerte do rebrand: arquivo e nome do estudo andam juntos."""
    pine = ROOT / "references" / "pine-setups"
    assert list(pine.glob("aspira_*.pine")) == [], "sobrou .pine com o nome antigo"
    arquivos = sorted(pine.glob("intuscripto_*.pine"))
    assert len(arquivos) == 13, f"esperava 13 .pine renomeados, achei {len(arquivos)}"
    for f in arquivos:
        conteudo = f.read_text(encoding="utf-8")
        assert "Aspira" not in conteudo, f"{f.name} ainda nomeia o estudo como Aspira"


def test_o_mapping_aponta_para_arquivos_que_existem() -> None:
    """Renomear arquivo e esquecer o índice deixa o mapa apontando para o vazio
    -- e nada na suíte falharia por isso."""
    pine = ROOT / "references" / "pine-setups"
    mapping = json.loads((pine / "mapping.json").read_text(encoding="utf-8"))
    referenciados = [
        nome
        for grupo in mapping.values()
        if isinstance(grupo, dict)
        for nome in grupo.values()
        if isinstance(nome, str) and nome.endswith(".pine")
    ]
    assert referenciados, "nenhum .pine referenciado -- o teste não exercita nada"
    faltando = [nome for nome in referenciados if not (pine / nome).exists()]
    assert faltando == [], f"mapping.json aponta para arquivo inexistente: {faltando}"


def test_a_marca_exibida_e_a_nova() -> None:
    """O que o operador vê na entrega."""
    exemplo = (ROOT / "workspace" / ".env.example").read_text(encoding="utf-8")
    assert "SETUP_NOTIFY_BRAND=INTUSCRIPTO" in exemplo
    assert "ASPIRA TRADE" not in exemplo
