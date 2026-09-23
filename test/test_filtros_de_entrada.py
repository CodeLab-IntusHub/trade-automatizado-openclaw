"""Os dois filtros que decidem se — e em que direção — uma entrada acontece.

`UNIQUE_TREND` restringe a direção das entradas. String vazia significa **sem
filtro**, e é isso que `decision.py:497` testa:

    if self.unique_trend:
        if self.unique_trend == 'LONG' and not is_long: ...

`_load_unique_trend_env` devolvia `""` para tudo que não fosse exatamente
`LONG` ou `SHORT`. Medido antes da correção:

    'LONG'       -> 'LONG'
    'LNOG'       -> ''        filtro sumiu, opera nos dois sentidos
    'LONGO'      -> ''        filtro sumiu
    'comprado'   -> ''        filtro sumiu
    'LONG,SHORT' -> ''        filtro sumiu

O operador restringe a direção e a restrição desaparece sem nada dizer — a
mesma forma do `CEX_SANDBOX=ture` e do `PROTECTIVE_STOP_LOSS_PCT=2,5`.

`comprado` incomoda em particular: o `_normalize_order_side_arg`, na mesma
`cli.py`, **aceita** `comprado`, `compra`, `vendido` e `venda`. O projeto
entende a palavra num lugar e a descarta no outro — é o mesmo desencontro que
`on`/`s`/`y` tinham entre o `sandbox` e os portões booleanos.

`CERTAINTY` é o limiar que decide se a entrada acontece. Ele já falhava
fechado, mas com `ValueError` cru: traceback, sem nomear a variável. E `70,5`
esbarra na mesma vírgula decimal da fatia anterior.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import ConfigError  # noqa: E402

# Palavras que o `_normalize_order_side_arg` já aceita para o mesmo conceito.
SINONIMOS_LONG = ["long", "LONG", "Long", " long ", "comprado", "compra"]
SINONIMOS_SHORT = ["short", "SHORT", "vendido", "venda"]

INVALIDOS = ["LNOG", "LONGO", "buy", "1", "LONG,SHORT", "ambos", "both"]


@pytest.mark.parametrize("valor", SINONIMOS_LONG)
def test_sinonimos_de_long_sao_aceitos(valor, monkeypatch) -> None:
    """`comprado` e `compra` já valem no `--side`; descartá-los aqui é o mesmo
    desencontro que `on`/`s`/`y` tinham entre o sandbox e os booleanos."""
    from workspace.cli import _load_unique_trend_env

    monkeypatch.setenv("UNIQUE_TREND", valor)
    assert _load_unique_trend_env() == "LONG"


@pytest.mark.parametrize("valor", SINONIMOS_SHORT)
def test_sinonimos_de_short_sao_aceitos(valor, monkeypatch) -> None:
    from workspace.cli import _load_unique_trend_env

    monkeypatch.setenv("UNIQUE_TREND", valor)
    assert _load_unique_trend_env() == "SHORT"


@pytest.mark.parametrize("valor", INVALIDOS)
def test_valor_desconhecido_nao_apaga_o_filtro(valor, monkeypatch) -> None:
    """O filtro sumir em silêncio é pior que o comando não rodar: o operador
    restringiu a direção e passa a operar nos dois sentidos."""
    from workspace.cli import _load_unique_trend_env

    monkeypatch.setenv("UNIQUE_TREND", valor)
    with pytest.raises(ConfigError) as exc:
        _load_unique_trend_env()
    mensagem = str(exc.value)
    assert "UNIQUE_TREND" in mensagem, mensagem
    assert valor.strip() in mensagem, "a mensagem precisa mostrar o valor recusado"


def test_mensagem_lista_o_que_e_aceito(monkeypatch) -> None:
    """Recusar sem dizer o que vale devolve o operador à documentação."""
    from workspace.cli import _load_unique_trend_env

    monkeypatch.setenv("UNIQUE_TREND", "LNOG")
    mensagem = str(pytest.raises(ConfigError, _load_unique_trend_env).value)
    assert "long" in mensagem.lower() and "short" in mensagem.lower()


def test_ausente_e_vazio_seguem_significando_sem_filtro(monkeypatch) -> None:
    """Não declarar continua sendo diferente de declarar errado. Aqui isso
    importa em dobro: vazio é um valor com significado (`sem filtro`), e não a
    ausência de um."""
    from workspace.cli import _load_unique_trend_env

    monkeypatch.delenv("UNIQUE_TREND", raising=False)
    assert _load_unique_trend_env() == ""
    monkeypatch.setenv("UNIQUE_TREND", "   ")
    assert _load_unique_trend_env() == ""


def test_contrato_com_o_decision_continua_maiusculo(monkeypatch) -> None:
    """`decision.py` compara com `'LONG'`/`'SHORT'` literais. Devolver
    minúsculo apagaria o filtro pelo outro lado, sem erro nenhum."""
    from workspace.cli import _load_unique_trend_env

    monkeypatch.setenv("UNIQUE_TREND", "comprado")
    assert _load_unique_trend_env() in {"LONG", "SHORT"}


# `70%%` fica de fora: `rstrip("%")` corta os dois sinais e o numero resolvido
# e o mesmo. Tolerar isso nao perde informacao nenhuma -- recusar seria rigor
# sem consequencia.
@pytest.mark.parametrize("valor", ["7O", "70,5", "setenta", "70pct", "7.0.0"])
def test_certainty_invalido_nomeia_a_variavel(valor, monkeypatch) -> None:
    """Já falhava fechado, mas com `ValueError` cru -- traceback, sem dizer
    qual variável nem o que se esperava dela."""
    from workspace.cli import _load_certainty_env

    monkeypatch.setenv("CERTAINTY", valor)
    with pytest.raises(ConfigError) as exc:
        _load_certainty_env()
    assert "CERTAINTY" in str(exc.value)


def test_certainty_com_virgula_recebe_a_dica(monkeypatch) -> None:
    from workspace.cli import _load_certainty_env

    monkeypatch.setenv("CERTAINTY", "70,5")
    assert "ponto" in str(pytest.raises(ConfigError, _load_certainty_env).value).lower()


@pytest.mark.parametrize("valor,esperado", [
    ("70", 70), ("70%", 70), ("0.7", 70), (" 70 ", 70), ("100", 100), ("1", 100),
])
def test_certainty_valido_continua_valendo(valor, esperado, monkeypatch) -> None:
    """A escala dupla (0-1 e 0-100) é parte do contrato e não pode se perder."""
    from workspace.cli import _load_certainty_env

    monkeypatch.setenv("CERTAINTY", valor)
    assert _load_certainty_env() == esperado


def test_certainty_ausente_cai_no_default(monkeypatch) -> None:
    from workspace.cli import _load_certainty_env

    monkeypatch.delenv("CERTAINTY", raising=False)
    assert _load_certainty_env() == 70


def test_a_copia_da_nado_usa_o_mesmo_vocabulario() -> None:
    """Os dois helpers estão duplicados em `nado/auto_trade_nado.py`, lidos das
    mesmas variáveis.

    Guard **estático** pelo mesmo motivo do vocabulário de booleanos: o módulo
    só importa com o SDK `nado_protocol`, e um guard silenciosamente skipado na
    máquina de quem desenvolve não guarda nada.
    """
    fonte = (ROOT / "workspace" / "nado" / "auto_trade_nado.py").read_text(encoding="utf-8")
    ofensas = [
        f"linha {n}: {linha.strip()}"
        for n, linha in enumerate(fonte.splitlines(), 1)
        if 'raw in {"LONG", "SHORT"}' in linha or "raw in {'LONG', 'SHORT'}" in linha
    ]
    assert ofensas == [], (
        "cópia própria do vocabulário de UNIQUE_TREND -- o filtro de direção "
        f"sumiria em silêncio por este caminho: {ofensas}"
    )
