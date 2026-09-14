"""Fundacao de configuracao: uma fonte, uma precedencia, um vocabulario.

Hoje ha 35 helpers de leitura de env espalhados, com vocabulario de booleano
que so define o lado verdadeiro -- entao qualquer valor desconhecido (um typo
como `ture`) resolve para falso em silencio. Em `CEX_SANDBOX` isso significa
producao.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import ConfigError, Settings, load_settings  # noqa: E402


def _settings(tmp_path: Path, *, versioned=None, local=None, env=None) -> Settings:
    if versioned is not None:
        (tmp_path / "settings.json").write_text(json.dumps(versioned), encoding="utf-8")
    if local is not None:
        (tmp_path / "settings.local.json").write_text(json.dumps(local), encoding="utf-8")
    return load_settings(root=tmp_path, env=env or {})


# --- precedencia ------------------------------------------------------------

def test_precedencia_env_vence_local_vence_versionado_vence_default(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={"cex": {"id": "kraken"}},
        local={"cex": {"id": "bybit"}},
        env={"CEX_ID": "okx"},
    )
    assert s.get_str("cex.id", env="CEX_ID", default="nada") == "okx"

    s = _settings(tmp_path, versioned={"cex": {"id": "kraken"}}, local={"cex": {"id": "bybit"}})
    assert s.get_str("cex.id", env="CEX_ID", default="nada") == "bybit"

    s = _settings(tmp_path, versioned={"cex": {"id": "kraken"}}, local={})
    assert s.get_str("cex.id", env="CEX_ID", default="nada") == "kraken"

    s = _settings(tmp_path, versioned={}, local={})
    assert s.get_str("cex.id", env="CEX_ID", default="nada") == "nada"


def test_cadeia_de_aliases_respeita_a_ordem(tmp_path: Path) -> None:
    """Nomes alternativos existem hoje em tres copias do mesmo helper."""
    s = _settings(tmp_path, env={"KRAKEN_API_KEY_": "b"})
    assert s.get_str("cex.key", env=["KRAKEN_API_KEY", "KRAKEN_API_KEY_"], default="") == "b"

    s = _settings(tmp_path, env={"KRAKEN_API_KEY": "a", "KRAKEN_API_KEY_": "b"})
    assert s.get_str("cex.key", env=["KRAKEN_API_KEY", "KRAKEN_API_KEY_"], default="") == "a"


def test_origem_do_valor_e_rastreavel(tmp_path: Path) -> None:
    """Sem isto, "por que esse valor?" vira arqueologia em 35 helpers."""
    s = _settings(tmp_path, versioned={"a": {"b": 1}}, local={}, env={"A_B": "2"})
    assert s.origin("a.b", env="A_B").layer == "env"
    s = _settings(tmp_path, versioned={"a": {"b": 1}}, local={})
    assert s.origin("a.b", env="A_B").layer == "settings.json"


# --- vocabulario de booleano ------------------------------------------------

@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "sim", "on", "y"])
def test_booleano_verdadeiro(tmp_path: Path, valor) -> None:
    assert _settings(tmp_path, env={"F": valor}).get_bool("f", env="F") is True


@pytest.mark.parametrize("valor", ["0", "false", "FALSE", "no", "nao", "off", "n"])
def test_booleano_falso(tmp_path: Path, valor) -> None:
    assert _settings(tmp_path, env={"F": valor}).get_bool("f", env="F") is False


@pytest.mark.parametrize("valor", ["ture", "sandbox", "maybe", "2"])
def test_booleano_ilegivel_falha_em_vez_de_virar_falso(tmp_path: Path, valor) -> None:
    """O defeito central: "nao esta no conjunto verdadeiro" virava falso.

    Em `CEX_SANDBOX`, falso significa dinheiro real.
    """
    s = _settings(tmp_path, env={"F": valor})
    with pytest.raises(ConfigError, match="(?i)booleano"):
        s.get_bool("f", env="F")


def test_env_vazia_conta_como_nao_definida(tmp_path: Path) -> None:
    """`export CEX_SANDBOX=` e quase sempre acidente de script, nao escolha.

    Tratar como "ausente" faz cair no default (ou no erro de obrigatoria), que
    e mais honesto que inventar um booleano a partir de string vazia.
    """
    s = _settings(tmp_path, env={"F": ""})
    with pytest.raises(ConfigError, match="(?i)obrigat"):
        s.get_bool("f", env="F")
    assert _settings(tmp_path, env={"F": ""}).get_bool("f", env="F", default=True) is True


def test_booleano_sem_default_e_obrigatorio(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="(?i)obrigat"):
        _settings(tmp_path).get_bool("cex.sandbox", env="CEX_SANDBOX")
    assert _settings(tmp_path).get_bool("cex.sandbox", env="CEX_SANDBOX", default=True) is True


# --- tipos ------------------------------------------------------------------

def test_tipos_coagem_e_falham_com_a_chave_no_erro(tmp_path: Path) -> None:
    s = _settings(tmp_path, env={"N": "12", "X": "1.5", "L": "BTC, ETH ,SOL", "J": '{"a":1}'})
    assert s.get_int("n", env="N") == 12
    assert s.get_float("x", env="X") == 1.5
    assert s.get_list("l", env="L") == ["BTC", "ETH", "SOL"]
    assert s.get_json("j", env="J") == {"a": 1}

    s = _settings(tmp_path, env={"N": "doze"})
    with pytest.raises(ConfigError, match="N"):
        s.get_int("n", env="N")


def test_valor_de_env_nao_perde_conteudo_apos_cerquilha(tmp_path: Path) -> None:
    """Os leitores atuais cortam no primeiro `#` ANTES de remover aspas, entao
    nem aspas protegem -- e isso corrompe passphrase vinda do secret manager.
    Corte de comentario e coisa de parser de arquivo .env, nao de valor que ja
    esta no ambiente."""
    s = _settings(tmp_path, env={"P": "senha#comcerquilha"})
    assert s.get_str("p", env="P", default="") == "senha#comcerquilha"


# --- segredos ---------------------------------------------------------------

def test_segredo_guarda_o_nome_da_env_nunca_o_valor(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={"cex": {"credentials": {"api_key": {"env": ["KRAKEN_API_KEY", "CEX_API_KEY"]}}}},
        env={"CEX_API_KEY": "segredo-real"},
    )
    assert s.secret("cex.credentials.api_key") == "segredo-real"


def test_segredo_literal_no_arquivo_e_recusado(tmp_path: Path) -> None:
    """Deixar um segredo entrar no settings versionado e o pior desfecho."""
    s = _settings(tmp_path, versioned={"cex": {"credentials": {"api_key": "chave-crua"}}})
    with pytest.raises(ConfigError, match="(?i)segredo|env"):
        s.secret("cex.credentials.api_key")


# --- higiene do arquivo -----------------------------------------------------

def test_json_invalido_falha_nomeando_o_arquivo(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{ isso nao e json", encoding="utf-8")
    with pytest.raises(ConfigError, match="settings.json"):
        load_settings(root=tmp_path, env={})


def test_ausencia_de_arquivo_nao_e_erro(tmp_path: Path) -> None:
    assert load_settings(root=tmp_path, env={}).get_str("x.y", env="XY", default="ok") == "ok"


def test_setups_sao_enderecaveis_por_chave(tmp_path: Path) -> None:
    """Requisito: cada setup tem as suas vars no settings, nada hardcoded."""
    s = _settings(
        tmp_path,
        versioned={"setups": {"divergence-and-volume-4h": {"rsi_period": 14, "volume_factor": 1.5}}},
    )
    assert s.get_int("setups.divergence-and-volume-4h.rsi_period", env="RSI_PERIOD_4H") == 14
    assert s.get_float("setups.divergence-and-volume-4h.volume_factor", env="VOL_FACTOR_4H") == 1.5
