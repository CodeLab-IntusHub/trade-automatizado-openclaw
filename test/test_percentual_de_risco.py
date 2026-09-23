"""Percentual de risco lido do ambiente não cai mais no default em silêncio.

`_pct_from_env` e `_notice_pct_from_env` faziam

    try:
        return _parse_pct_value(raw)
    except (TypeError, ValueError):
        return default

e o que elas alimentam é **stop loss e take profit**:
`PROTECTIVE_STOP_LOSS_PCT`, `MAX_PAIR_LOSS_PCT`, `SETUP_NOTIFY_STOP_LOSS_PCT`.

Medido antes da correção, com `default=0.03`:

    '2.5'         -> 0.025
    '2,5'         -> 0.030   valor descartado, stop 20% mais largo
    'dois e meio' -> 0.030   valor descartado
    '2.5pct'      -> 0.030   valor descartado
    '2.5.0'       -> 0.030   valor descartado

O caso que decide esta fatia é **`2,5`**. A vírgula decimal é a escrita natural
em português, e ela não produz erro nenhum: produz um stop mais largo que o
pretendido, calado. É o mesmo formato de defeito do `CEX_SANDBOX=ture` e do
`NADO_REQUIRE_LINKED_SIGNER=on` — valor que o operador escreveu, descartado sem
aviso, com o default ocupando o lugar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import ConfigError  # noqa: E402

# Os quatro nomes que `_notice_stop_loss_pct` consulta, na ordem.
ENVS_DE_STOP = (
    "SETUP_TEST_STOP_LOSS_PCT",
    "SETUP_NOTIFY_STOP_LOSS_PCT",
    "PROTECTIVE_STOP_LOSS_PCT",
    "MAX_PAIR_LOSS_PCT",
)

INVALIDOS = ["2,5", "dois e meio", "2.5pct", "2.5.0", "--2.5", "2,5%"]


def _limpa(monkeypatch) -> None:
    for nome in ENVS_DE_STOP + ("PROTECTIVE_TAKE_PROFIT_PCT", "SETUP_NOTIFY_TAKE_PROFIT_PCT"):
        monkeypatch.delenv(nome, raising=False)


@pytest.mark.parametrize("valor", INVALIDOS)
def test_stop_invalido_levanta_em_vez_de_virar_default(valor, monkeypatch) -> None:
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", valor)
    with pytest.raises(ConfigError) as exc:
        _notice_stop_loss_pct()
    mensagem = str(exc.value)
    assert "PROTECTIVE_STOP_LOSS_PCT" in mensagem, mensagem
    assert valor in mensagem, "a mensagem precisa mostrar o valor recusado"


def test_mensagem_cita_a_virgula_decimal(monkeypatch) -> None:
    """A vírgula é o erro mais provável aqui, e a correção não é óbvia para
    quem escreve números em português. Dizer "valor inválido" e parar devolve o
    operador ao mesmo lugar."""
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", "2,5")
    with pytest.raises(ConfigError) as exc:
        _notice_stop_loss_pct()
    assert "ponto" in str(exc.value).lower(), str(exc.value)


@pytest.mark.parametrize("valor,esperado", [
    ("2.5", 0.025), ("2.5%", 0.025), (" 2.5 ", 0.025), ("0.025", 0.025),
    ("2.5 %", 0.025), ("10", 0.10), ("1", 1.0), ("0", 0.0),
])
def test_valores_validos_continuam_valendo(valor, esperado, monkeypatch) -> None:
    """A correção não pode estreitar o que já era aceito: `2.5%`, espaço em
    volta e o valor já em fração estavam todos funcionando."""
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", valor)
    assert _notice_stop_loss_pct() == pytest.approx(esperado)


def test_env_ausente_ou_em_branco_cai_no_default(monkeypatch) -> None:
    """Não declarar segue sendo diferente de declarar errado -- sem isso, todo
    percentual viraria obrigatório.

    Quem trata a variável em branco aqui é o `_first_env`, que já a considera
    ausente; o ramo de vazio do parser é outro caminho, exercitado abaixo.
    Eram dois caminhos e este teste cobria só um: uma mutação que removia o
    ramo do parser sobreviveu intacta.
    """
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    assert _notice_stop_loss_pct() == pytest.approx(0.03)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", "   ")
    assert _notice_stop_loss_pct() == pytest.approx(0.03)


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_percentual_vazio_vindo_de_argumento_e_zero(vazio) -> None:
    """O outro caminho do parser: `--stop-loss ""` na linha de comando.

    Aqui não há `_first_env` filtrando antes, então o ramo de vazio é o que
    impede um `float("")` virar erro no meio de um argumento opcional.
    """
    from workspace.cli import _parse_pct_value

    assert _parse_pct_value(vazio, "--stop-loss") == 0.0


def test_negativo_continua_recusado(monkeypatch) -> None:
    """`_parse_pct_value` já recusava negativo; a mudança de excecao não pode
    perder isso."""
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", "-2.5")
    with pytest.raises(ConfigError):
        _notice_stop_loss_pct()


def test_erro_nomeia_a_variavel_que_de_fato_carregou_o_valor(monkeypatch) -> None:
    """São quatro nomes na cadeia. Citar sempre o primeiro mandaria o operador
    mexer numa variável que ele não definiu -- o mesmo defeito que o
    `HYPERLIQUID_NETWORK`/`DEX_NETWORK` teve no aviso de sandbox."""
    from workspace.cli import _notice_stop_loss_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("MAX_PAIR_LOSS_PCT", "2,5")
    with pytest.raises(ConfigError) as exc:
        _notice_stop_loss_pct()
    assert "MAX_PAIR_LOSS_PCT" in str(exc.value)
    assert "SETUP_TEST_STOP_LOSS_PCT" not in str(exc.value)


def test_take_profit_tem_o_mesmo_tratamento(monkeypatch) -> None:
    """Corrigir só o stop deixaria o par assimétrico, e o take profit decide
    onde o capital sai da posição."""
    from workspace.cli import _notice_take_profit_pct

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_TAKE_PROFIT_PCT", "2,5")
    with pytest.raises(ConfigError):
        _notice_take_profit_pct()


def test_scanner_usa_o_mesmo_vocabulario(monkeypatch) -> None:
    """O scanner tem a sua própria cópia do helper, com os mesmos nomes de
    variável. Corrigir só o `cli` repetiria o defeito de origem do sandbox --
    dois leitores, uma pergunta, dois vereditos."""
    import importlib

    _limpa(monkeypatch)
    monkeypatch.setenv("PROTECTIVE_STOP_LOSS_PCT", "2,5")
    scanner = importlib.import_module("workspace.ccxt_entry_scanner")
    try:
        with pytest.raises(ConfigError):
            importlib.reload(scanner)
    finally:
        monkeypatch.delenv("PROTECTIVE_STOP_LOSS_PCT", raising=False)
        importlib.reload(scanner)


def test_tamanho_de_posicao_invalido_nomeia_a_variavel(monkeypatch) -> None:
    """`_load_optional_float_arg` já falhava fechado, mas com `ValueError` cru:
    traceback, sem dizer qual variável estava errada. Ele decide `MARGIN_USD` —
    o tamanho da posição."""
    from workspace.cli import _load_optional_float_arg

    monkeypatch.delenv("MARGIN_USD", raising=False)
    monkeypatch.setenv("MARGIN_USD", "1.000,50")
    with pytest.raises(ConfigError) as exc:
        _load_optional_float_arg(None, "MARGIN_USD", "DEFAULT_MARGIN_USD")
    assert "MARGIN_USD" in str(exc.value)


def test_tamanho_de_posicao_valido_continua_valendo(monkeypatch) -> None:
    from workspace.cli import _load_optional_float_arg

    monkeypatch.setenv("MARGIN_USD", "150.5")
    assert _load_optional_float_arg(None, "MARGIN_USD") == pytest.approx(150.5)
    monkeypatch.delenv("MARGIN_USD", raising=False)
    assert _load_optional_float_arg(None, "MARGIN_USD") == 0.0
    assert _load_optional_float_arg(12.5, "MARGIN_USD") == pytest.approx(12.5)
