"""A chave da DEX pode sacar? (ADR 0007 com o adendo de 25/09, ROADMAP 1.7)

Nao precisa de rede: a pergunta e *qual* chave o operador configurou.

- Hyperliquid: a API wallet (agent) nao saca -- "API wallets (also known as
  agent wallets) can perform actions on behalf of an account without having
  withdrawal permissions" (app.hyperliquid.xyz/API). Se o endereco derivado da
  chave e o da conta, e a chave principal, e ela saca.
- Nado: a owner key e a carteira: saca. O linked signer "assina executes em
  nome da subconta", e saque e um execute -- a documentacao nao fecha a
  questao, entao fica "nao verificado".

Como na CEX: e aviso; `BLOQUEAR_SAQUE=sim` torna bloqueio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import run
from workspace.venues import permissao_de_saque as ps

# Conta 0 do Hardhat: chave de teste publica, endereco conhecido.
CHAVE_TESTE = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ENDERECO_TESTE = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
OUTRO_ENDERECO = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

ENVS_DEX = (
    "HYPERLIQUID_PRIVATE_KEY", "HYPERLIQUID_API_PRIVATE_KEY", "HYPERLIQUID_AGENT_PRIVATE_KEY",
    "HYPERLIQUID_WALLET_ADDRESS", "HYPERLIQUID_ACCOUNT_ADDRESS",
    "NADO_OWNER_PRIVATE_KEY", "NADO_PRIVATE_KEY", "PRIVATE_KEY", "NADO_LINKED_SIGNER_PRIVATE_KEY",
    "BLOQUEAR_SAQUE", "CEX_ID",
)


@pytest.fixture
def limpo(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for nome in ENVS_DEX:
        monkeypatch.delenv(nome, raising=False)
    return monkeypatch


def test_hyperliquid_chave_principal_saca(limpo) -> None:
    limpo.setenv("HYPERLIQUID_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", ENDERECO_TESTE.lower())
    assert ps.verificar_dex("hyperliquid").estado == ps.PODE_SACAR


def test_hyperliquid_api_wallet_nao_saca(limpo) -> None:
    limpo.setenv("HYPERLIQUID_AGENT_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", OUTRO_ENDERECO)
    assert ps.verificar_dex("hyperliquid").estado == ps.SEM_SAQUE


def test_hyperliquid_chave_invalida_e_erro_sem_vazar(limpo) -> None:
    limpo.setenv("HYPERLIQUID_PRIVATE_KEY", "0xnaoehex-SEGREDO")
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", ENDERECO_TESTE)
    veredicto = ps.verificar_dex("hyperliquid")
    assert veredicto.estado == ps.ERRO
    assert "SEGREDO" not in veredicto.detalhe


def test_hyperliquid_sem_credencial_nao_se_aplica(limpo) -> None:
    assert ps.verificar_dex("hyperliquid") is None


def test_nado_owner_key_saca(limpo) -> None:
    limpo.setenv("NADO_OWNER_PRIVATE_KEY", CHAVE_TESTE)
    veredicto = ps.verificar_dex("nado")
    assert veredicto.estado == ps.PODE_SACAR
    assert "NADO_LINKED_SIGNER_PRIVATE_KEY" in veredicto.detalhe


def test_nado_com_linked_signer_nao_e_verificavel(limpo) -> None:
    limpo.setenv("NADO_OWNER_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("NADO_LINKED_SIGNER_PRIVATE_KEY", CHAVE_TESTE)
    assert ps.verificar_dex("nado").estado == ps.NAO_VERIFICAVEL


def test_dex_por_adapter_nao_e_verificavel(limpo) -> None:
    assert ps.verificar_dex("dydx").estado == ps.NAO_VERIFICAVEL


# --- doctor e comando de trade ----------------------------------------------


def _check(relatorio: dict) -> dict | None:
    return next((c for c in relatorio["checks"] if c["name"] == "dex_key_sem_saque"), None)


def _reprovados(relatorio: dict) -> list[str]:
    return [c["name"] for c in relatorio["checks"] if c["name"] in relatorio["blocking_checks"] and not c["ok"]]


def test_doctor_avisa_chave_principal_da_hyperliquid(limpo) -> None:
    limpo.setenv("DEX_ID", "hyperliquid")
    limpo.setenv("HYPERLIQUID_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", ENDERECO_TESTE)
    relatorio = run.doctor()
    check = _check(relatorio)
    assert check is not None and check["ok"] is False and check["verificado"] is True
    assert "dex_key_sem_saque" not in _reprovados(relatorio)
    limpo.setenv("BLOQUEAR_SAQUE", "sim")
    assert "dex_key_sem_saque" in _reprovados(run.doctor())


def test_doctor_sem_dex_nao_tem_o_check(limpo) -> None:
    limpo.delenv("DEX_ID", raising=False)
    limpo.setenv("CEX_ID", "binance")
    assert _check(run.doctor()) is None


def test_trade_recusado_com_chave_principal_e_bloqueio_ligado(limpo) -> None:
    limpo.setenv("DEX_ID", "hyperliquid")
    limpo.setenv("CEX_ID", "binance")
    limpo.setenv("HYPERLIQUID_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", ENDERECO_TESTE)
    limpo.setenv("BLOQUEAR_SAQUE", "sim")
    limpo.setenv("AUTORIZAR_TRADE_REAL", "sim")
    limpo.setenv("DELTA_NEUTRAL_NO_BOOTSTRAP", "1")
    executados: list = []
    limpo.setattr(run.subprocess, "call", lambda cmd, **k: executados.append(cmd) or 0)
    assert run._run_cli(["abrir", "ETH/USDT", "--margem-usd", "20"]) == 2
    assert executados == []


# --- achados do review da #47 -------------------------------------------------


def test_endereco_sem_0x_ainda_reconhece_a_chave_principal(limpo) -> None:
    """Falso "seguro": sem o prefixo, a chave principal passava por API wallet."""
    limpo.setenv("HYPERLIQUID_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("HYPERLIQUID_WALLET_ADDRESS", ENDERECO_TESTE[2:])
    assert ps.verificar_dex("hyperliquid").estado == ps.PODE_SACAR


def test_hyperliquid_configurada_pelo_dex_config_json(limpo) -> None:
    """O adapter aceita chave e conta pelo DEX_CONFIG_JSON; o check nao pode sumir."""
    import json

    limpo.delenv("DEX_CONFIG_JSON", raising=False)
    limpo.setenv("DEX_CONFIG_JSON", json.dumps({"wallet_address": ENDERECO_TESTE, "private_key": CHAVE_TESTE}))
    assert ps.verificar_dex("hyperliquid").estado == ps.PODE_SACAR


def test_nado_com_fallback_para_owner_ligado_saca(limpo) -> None:
    """Com linked signer, mas fallback para a owner key ligado e confirmado,
    a skill pode assinar com a owner key: o check diz isso."""
    limpo.setenv("NADO_OWNER_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("NADO_LINKED_SIGNER_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("NADO_ALLOW_OWNER_FALLBACK", "true")
    limpo.setenv("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK", "true")
    veredicto = ps.verificar_dex("nado")
    assert veredicto.estado == ps.PODE_SACAR
    assert "NADO_ALLOW_OWNER_FALLBACK" in veredicto.detalhe


def test_nado_fallback_pedido_sem_confirmacao_nao_liga(limpo) -> None:
    limpo.setenv("NADO_OWNER_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("NADO_LINKED_SIGNER_PRIVATE_KEY", CHAVE_TESTE)
    limpo.setenv("NADO_ALLOW_OWNER_FALLBACK", "true")
    limpo.delenv("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK", raising=False)
    assert ps.verificar_dex("nado").estado == ps.NAO_VERIFICAVEL
