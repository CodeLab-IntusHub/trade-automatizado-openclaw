"""Hyperliquid: a rede declarada e config, nao um default.

A Hyperliquid deriva `sandbox` da rede selecionada (`HYPERLIQUID_NETWORK`:
`testnet` implica sandbox). Como isso sai de uma **variavel de ambiente**, ele
pertence a camada de ambiente -- abaixo de um `HYPERLIQUID_SANDBOX` explicito,
que responde a pergunta diretamente, e acima de qualquer arquivo.

Foi posicionar esse degrau enquanto o modelo de precedencia ainda assentava que
produziu tres posicoes erradas seguidas na PR #10, duas delas mandando ordem
para a mainnet. Por isso ele vem sozinho, com o caller junto.

Ha ainda uma contradicao que o adapter resolve em silencio e sempre a favor da
mainnet: `HyperliquidDexTrader.__init__` faz
`self.network = "testnet" if self.sandbox else "mainnet"`, **descartando** a
rede declarada. Com `HYPERLIQUID_NETWORK=testnet` e `HYPERLIQUID_SANDBOX=false`
-- o par que o `.env.example` distribuia -- quem escolheu testnet opera na
mainnet sem nenhum aviso.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import Settings, load_settings  # noqa: E402
from workspace.venues.sandbox import resolve_sandbox  # noqa: E402

ENVS_DE_REDE = ("HYPERLIQUID_NETWORK", "DEX_NETWORK", "HYPERLIQUID_SANDBOX", "DEX_SANDBOX")


def _settings(tmp_path: Path, *, versioned=None, local=None, env=None) -> Settings:
    (tmp_path / "settings.json").write_text(json.dumps(versioned or {}), encoding="utf-8")
    (tmp_path / "settings.local.json").write_text(json.dumps(local or {}), encoding="utf-8")
    return load_settings(root=tmp_path, env=env or {})


def _limpa_rede(monkeypatch) -> None:
    for nome in ENVS_DE_REDE:
        monkeypatch.delenv(nome, raising=False)


# --- o degrau na camada de ambiente -----------------------------------------


def test_env_default_vence_arquivo(tmp_path: Path) -> None:
    """Ele vem de uma env, entao vence arquivo -- como toda env.

    Coloca-lo abaixo da config de arquivo fazia um `venues.dex.sandbox: false`
    derrubar uma rede declarada por variavel de ambiente.
    """
    s = _settings(tmp_path, versioned={"venues": {"dex": {"sandbox": False}}})
    assert resolve_sandbox("dex", "hyperliquid", settings=s, env_default=True) is True


def test_env_de_sandbox_explicita_vence_o_env_default(tmp_path: Path) -> None:
    """`HYPERLIQUID_SANDBOX` responde a pergunta; a rede so a implica."""
    s = _settings(tmp_path, env={"HYPERLIQUID_SANDBOX": "false"})
    assert resolve_sandbox("dex", "hyperliquid", settings=s, env_default=True) is False


def test_sem_env_default_o_arquivo_decide(tmp_path: Path) -> None:
    s = _settings(tmp_path, versioned={"venues": {"dex": {"hyperliquid": {"sandbox": True}}}})
    assert resolve_sandbox("dex", "hyperliquid", settings=s) is True


# --- o caller ---------------------------------------------------------------


def test_sem_rede_declarada_o_settings_decide(tmp_path: Path, monkeypatch) -> None:
    """`network in {...}` e sempre um bool, nunca `None`.

    Passar esse bool incondicional injeta um `False` na camada de ambiente que
    ninguem escreveu: como a Hyperliquid e o unico DEX que chama o resolvedor,
    isso torna `venues.dex.*.sandbox` config morta e manda para a mainnet quem
    declarou sandbox no arquivo.
    """
    from workspace import cli

    _limpa_rede(monkeypatch)
    (tmp_path / "settings.local.json").write_text(
        json.dumps({"venues": {"dex": {"hyperliquid": {"sandbox": True}}}}), encoding="utf-8"
    )
    assert cli._load_hyperliquid_config("hyperliquid")["sandbox"] is True


def test_testnet_declarada_vence_o_arquivo(tmp_path: Path, monkeypatch) -> None:
    from workspace import cli

    _limpa_rede(monkeypatch)
    monkeypatch.setenv("HYPERLIQUID_NETWORK", "testnet")
    (tmp_path / "settings.local.json").write_text(
        json.dumps({"venues": {"dex": {"hyperliquid": {"sandbox": False}}}}), encoding="utf-8"
    )
    assert cli._load_hyperliquid_config("hyperliquid")["sandbox"] is True


def test_mainnet_declarada_nao_vira_sandbox(tmp_path: Path, monkeypatch) -> None:
    from workspace import cli

    _limpa_rede(monkeypatch)
    monkeypatch.setenv("HYPERLIQUID_NETWORK", "mainnet")
    assert cli._load_hyperliquid_config("hyperliquid")["sandbox"] is False


# --- a contradicao que o adapter resolvia em silencio -----------------------


def test_rede_e_sandbox_em_conflito_avisam(tmp_path: Path, monkeypatch, caplog) -> None:
    """`HYPERLIQUID_NETWORK=testnet` + `HYPERLIQUID_SANDBOX=false` era o par que
    o `.env.example` distribuia. O explicito continua vencendo, mas o operador
    precisa saber que a rede que ele declarou foi descartada."""
    from workspace import cli

    _limpa_rede(monkeypatch)
    monkeypatch.setenv("HYPERLIQUID_NETWORK", "testnet")
    monkeypatch.setenv("HYPERLIQUID_SANDBOX", "false")
    with caplog.at_level("WARNING"):
        cfg = cli._load_hyperliquid_config("hyperliquid")
    assert cfg["sandbox"] is False
    assert "testnet" in caplog.text and "mainnet" in caplog.text


def test_rede_e_sandbox_de_acordo_nao_avisam(tmp_path: Path, monkeypatch, caplog) -> None:
    from workspace import cli

    _limpa_rede(monkeypatch)
    monkeypatch.setenv("HYPERLIQUID_NETWORK", "testnet")
    monkeypatch.setenv("HYPERLIQUID_SANDBOX", "true")
    with caplog.at_level("WARNING"):
        cfg = cli._load_hyperliquid_config("hyperliquid")
    assert cfg["sandbox"] is True
    assert caplog.text == ""


# --- o exemplo ---------------------------------------------------------------


def test_env_example_nao_traz_mais_sandbox_da_hyperliquid() -> None:
    """Com o caller migrado, o carve-out do guard da fatia 1 deixa de existir:
    `HYPERLIQUID_SANDBOX=false` ativo vencia a rede, entao quem copiava o
    exemplo e escolhia testnet ia para a mainnet."""
    linhas = (ROOT / "workspace" / ".env.example").read_text(encoding="utf-8").splitlines()
    ativas = [ln for ln in linhas if "_SANDBOX=" in ln and not ln.lstrip().startswith("#")]
    assert ativas == [], f"env de sandbox descomentada mata o settings: {ativas}"
