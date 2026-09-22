"""Os portoes booleanos que sobraram do `_load_bool_env`.

O resolvedor de sandbox ganhou vocabulario com os dois lados declarados: valor
fora da lista levanta em vez de virar `False`. Os outros oito portoes ficaram
para tras, e num deles o silencio e pior que no sandbox:
`NADO_REQUIRE_LINKED_SIGNER` tem default `True` -- ele **protege** --, entao um
valor nao reconhecido *desliga* a protecao, e nao ha nem o consolo de o default
ser o lado seguro.

Medido antes da correcao, com o portao valendo `True` por default:

    'ture'       -> False   protecao desligada
    'on'         -> False   protecao desligada
    's'          -> False   protecao desligada
    'y'          -> False   protecao desligada
    'verdadeiro' -> False   protecao desligada

`on`, `s` e `y` sao o caso que mais incomoda: eles sao **validos** no
vocabulario que o `sandbox` usa. Quem aprendeu a escrever `CEX_SANDBOX=on`
escreve `NADO_REQUIRE_LINKED_SIGNER=on` e desliga a verificacao de linked
signer sem nada dizer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.cli import _load_bool_env  # noqa: E402
from workspace.config import ConfigError  # noqa: E402

# Os oito portoes que ainda liam pelo helper antigo. O default importa: onde
# ele e `True`, o valor nao reconhecido *desliga* uma protecao.
PORTOES = {
    "NADO_REQUIRE_LINKED_SIGNER": True,
    "KRAKEN_API_IS_SUBACCOUNT": False,
    "KRAKEN_REQUIRE_SUBACCOUNT": False,
    "KRAKEN_ALLOW_MAIN_ACCOUNT": False,
    "NADO_ALLOW_OWNER_FALLBACK": False,
    "DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK": False,
    "SETUP_NOTIFY_MONITORED_ON_START": False,
    "SETUP_NOTIFY_MONITORED_FORCE": False,
}


@pytest.mark.parametrize("valor", ["ture", "tru", "verdadeiro", "truthy", "2", "-1", "nao-sei"])
def test_valor_desconhecido_levanta_em_vez_de_virar_falso(valor, monkeypatch) -> None:
    monkeypatch.setenv("NADO_REQUIRE_LINKED_SIGNER", valor)
    with pytest.raises(ConfigError) as exc:
        _load_bool_env("NADO_REQUIRE_LINKED_SIGNER", True)
    # A mensagem precisa nomear a variavel que o operador escreveu.
    assert "NADO_REQUIRE_LINKED_SIGNER" in str(exc.value)


@pytest.mark.parametrize("valor", ["on", "s", "y", "yes", "sim", "true", "1", "TRUE", " True "])
def test_vocabulario_verdadeiro_e_o_mesmo_do_sandbox(valor, monkeypatch) -> None:
    """`on`, `s` e `y` valiam no sandbox e viravam `False` aqui."""
    monkeypatch.setenv("KRAKEN_REQUIRE_SUBACCOUNT", valor)
    assert _load_bool_env("KRAKEN_REQUIRE_SUBACCOUNT", False) is True


@pytest.mark.parametrize("valor", ["off", "n", "nao", "no", "false", "0", "FALSE", " False "])
def test_vocabulario_falso_e_o_mesmo_do_sandbox(valor, monkeypatch) -> None:
    monkeypatch.setenv("NADO_REQUIRE_LINKED_SIGNER", valor)
    assert _load_bool_env("NADO_REQUIRE_LINKED_SIGNER", True) is False


@pytest.mark.parametrize("nome,padrao", sorted(PORTOES.items()))
def test_ausente_e_vazio_devolvem_o_default(nome, padrao, monkeypatch) -> None:
    """Nao declarar continua sendo diferente de declarar errado."""
    monkeypatch.delenv(nome, raising=False)
    assert _load_bool_env(nome, padrao) is padrao
    monkeypatch.setenv(nome, "   ")
    assert _load_bool_env(nome, padrao) is padrao


@pytest.mark.parametrize("nome,padrao", sorted(PORTOES.items()))
def test_typo_levanta_em_todos_os_portoes(nome, padrao, monkeypatch) -> None:
    """O defeito valia para os oito, nao so para o mais perigoso."""
    monkeypatch.setenv(nome, "ture")
    with pytest.raises(ConfigError):
        _load_bool_env(nome, padrao)


def test_comentario_inline_continua_sendo_removido(monkeypatch) -> None:
    """`_clean_literal_env` corta o `#`; a correcao nao pode perder isso --
    `KRAKEN_ALLOW_MAIN_ACCOUNT=false  # legado` viraria `ConfigError` no boot."""
    monkeypatch.setenv("KRAKEN_ALLOW_MAIN_ACCOUNT", "false  # legado/opcional")
    assert _load_bool_env("KRAKEN_ALLOW_MAIN_ACCOUNT", False) is False


def test_nenhum_modulo_guarda_a_propria_copia_do_vocabulario() -> None:
    """Corrigir so o `cli` repetiria o defeito de origem do sandbox.

    `NADO_REQUIRE_LINKED_SIGNER` e lido em **tres** lugares -- `cli.py` e os
    dois pontos de entrada da Nado --, cada um com a sua copia do `in {"1",
    "true", "yes", "sim"}`, e nos tres o default e `True`: o typo desliga a
    verificacao de linked signer.

    Este guard e **estatico** de proposito. Os dois modulos da Nado so
    importam com o SDK (`nado_protocol`) presente, e o `example.py` ainda
    depende de `nado_integration` no `sys.path` -- exercita-los aqui tornaria
    o guard silenciosamente skipado na maquina de desenvolvimento, que e
    exatamente onde ele precisa falhar. O teste de comportamento do
    `_env_bool` da Nado vem logo abaixo, condicionado ao SDK.
    """
    COPIA = '{"1", "true", "yes", "sim"}'
    ofensas = [
        f"{rel}:{n}"
        for rel in ("workspace/nado/auto_trade_nado.py", "workspace/nado/example.py")
        for n, linha in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1)
        if COPIA in linha and "return raw.lower() in" in linha
    ]
    assert ofensas == [], (
        "portao booleano com vocabulario proprio (so o lado verdadeiro "
        f"declarado, o resto vira False): {ofensas}"
    )


def test_env_bool_da_nado_usa_o_vocabulario_compartilhado(monkeypatch) -> None:
    pytest.importorskip("nado_protocol", reason="os modulos da Nado so importam com o SDK")
    from workspace.nado import auto_trade_nado

    monkeypatch.setenv("NADO_REQUIRE_LINKED_SIGNER", "ture")
    with pytest.raises(ConfigError):
        auto_trade_nado._env_bool("NADO_REQUIRE_LINKED_SIGNER", True)

    monkeypatch.setenv("NADO_REQUIRE_LINKED_SIGNER", "on")
    assert auto_trade_nado._env_bool("NADO_REQUIRE_LINKED_SIGNER", True) is True

    monkeypatch.delenv("NADO_REQUIRE_LINKED_SIGNER", raising=False)
    assert auto_trade_nado._env_bool("NADO_REQUIRE_LINKED_SIGNER", True) is True


def test_hyperliquid_to_bool_nao_engole_lixo_no_campo_sandbox() -> None:
    """O quinto leitor de `sandbox`, a jusante do resolvedor.

    `HyperliquidDexTrader.__init__` recoage o `sandbox` que recebe, com default
    `False` -- producao. Hoje o resolvedor entrega um `bool` de verdade, entao
    a recoercao e inofensiva; mas um `"ture"` chegando por qualquer caminho
    resolvia para producao em silencio. `None` e string vazia continuam
    devolvendo o default: nao declarar e diferente de declarar errado.
    """
    from workspace.venues.hyperliquid_dex import _to_bool

    assert _to_bool(None, True) is True
    assert _to_bool("", True) is True
    assert _to_bool("on", False) is True
    assert _to_bool("off", True) is False
    assert _to_bool(True, False) is True
    with pytest.raises(ConfigError):
        _to_bool("ture", False)
