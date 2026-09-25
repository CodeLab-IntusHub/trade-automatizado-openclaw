"""A entrega sai pelos canais do OpenClaw do proprio operador.

Ate aqui o Discord ia direto pela API REST, com um token de bot que a skill lia
do ambiente e ate do `~/.openclaw/openclaw.json`; o fallback para o OpenClaw
vinha desligado, entao uma falha descartava a mensagem. Agora todo canal passa
por `openclaw message send`: bot dedicado e uma conta dedicada no OpenClaw
(`--account`), e topico do Telegram e `--thread-id`. Nao ha canal padrao.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import cli

ENVS = (
    "SETUP_NOTIFY_ENTRY_CHANNEL",
    "SETUP_NOTIFY_ENTRY_TARGET",
    "SETUP_NOTIFY_ENTRY_ACCOUNT",
    "SETUP_NOTIFY_ENTRY_THREAD_ID",
    "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID",
    "SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT",
    "SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET",
    "SETUP_NOTIFY_ENTRY_WHATSAPP_ACCOUNT",
    "SETUP_NOTIFY_WHATSAPP_ENABLED",
    "SETUP_NOTIFY_ENTRY_ENABLED",
    "SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY",
    "DISCORD_BOT_TOKEN",
    "SETUP_NOTIFY_FALLBACK_OPENCLAW",
)


@pytest.fixture
def comandos(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Captura cada `openclaw message send` e proibe rede direta."""
    for nome in ENVS:
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY", "false")
    enviados: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        enviados.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"messageId": "m-1"}), stderr="")

    def sem_rede(*a: object, **k: object) -> None:
        raise AssertionError("a skill chamou a rede direto, por fora do OpenClaw")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(urllib.request, "urlopen", sem_rede)
    monkeypatch.setattr(cli, "_render_setup_chart_image", lambda *a, **k: None)
    return enviados


def _opcao(cmd: list[str], nome: str) -> str | None:
    return cmd[cmd.index(nome) + 1] if nome in cmd else None


def test_discord_sai_pelo_openclaw_mesmo_com_token_de_bot(
    comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-que-nao-deve-ser-usado")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "discord")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "channel:123")
    enviado = cli._send_setup_trade_notice("sinal")
    assert len(comandos) == 1
    assert comandos[0][1:3] == ["message", "send"]
    assert _opcao(comandos[0], "--channel") == "discord"
    assert enviado == {"discord_message_id": "m-1"}


def test_sem_canal_escolhido_nada_e_enviado(comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    """`telegram` era o canal padrao; agora canal e escolha do operador."""
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "12345")
    assert cli._send_setup_trade_notice("sinal") == {}
    assert comandos == []


def test_topico_do_telegram_vira_thread_id(comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "-100200")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_THREAD_ID", "77")
    cli._send_setup_trade_notice("sinal")
    assert _opcao(comandos[0], "--thread-id") == "77"


def test_bot_dedicado_e_conta_do_openclaw(comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "-100200")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_ACCOUNT", "bot-sinais")
    cli._send_setup_trade_notice("sinal")
    assert _opcao(comandos[0], "--account") == "bot-sinais"


def test_sem_conta_escolhida_o_openclaw_usa_a_dele(comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum `--account default` imposto: a conta padrao e a do OpenClaw."""
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "channel:9")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET", "+5511999999999")
    monkeypatch.setenv("SETUP_NOTIFY_WHATSAPP_ENABLED", "true")
    cli._send_setup_trade_notice("sinal")
    assert len(comandos) == 2
    assert all("--account" not in cmd for cmd in comandos)


def test_resposta_usa_o_id_guardado_sem_consultar_o_discord(
    comandos: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "discord")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "channel:123")
    cli._send_setup_trade_notice("atualizacao", reply_to_discord_message_id="m-entrada", include_chart=False)
    assert _opcao(comandos[0], "--reply-to") == "m-entrada"


def test_nenhum_caminho_direto_para_a_api_do_discord() -> None:
    fonte = (ROOT / "workspace" / "cli.py").read_text(encoding="utf-8")
    assert "discord.com/api" not in fonte
    assert "DISCORD_BOT_TOKEN" not in fonte
    assert "openclaw.json" not in fonte
