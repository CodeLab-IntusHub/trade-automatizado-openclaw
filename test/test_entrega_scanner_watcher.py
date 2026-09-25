"""Scanner e watcher entregam pelo mesmo caminho do `setup-live`.

Os dois tinham a propria copia da entrega: Discord direto pela API REST, com
token de bot lido do ambiente, de um `.env` e ate do `~/.openclaw/openclaw.json`;
o fallback para o OpenClaw vinha desligado, e os defaults divergiam do `cli.py`
(WhatsApp ligado so por ter destino, conta `default`, audiencia
"@Intus Club Member" fixa). Agora os dois chamam `_send_setup_trade_notice`:
mesma configuracao, mesmos canais do OpenClaw do operador, nenhum padrao.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import cli

scanner = importlib.import_module("workspace.ccxt_entry_scanner")
watcher = importlib.import_module("workspace.discord_signal_watcher")

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
    "SETUP_NOTIFY_DISCORD_AUDIENCE",
    "DISCORD_BOT_TOKEN",
    "SETUP_NOTIFY_FALLBACK_OPENCLAW",
    "SETUP_NOTIFY_DISCORD_DIRECT",
)


@pytest.fixture
def comandos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[list[str]]:
    """Captura cada `openclaw message send` e proibe rede direta."""
    for nome in ENVS:
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("SETUP_NOTIFY_REQUIRE_CHART_FOR_ENTRY", "false")
    enviados: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        enviados.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"messageId": "m-1"}), stderr="")

    def sem_rede(*a: object, **k: object) -> None:
        raise AssertionError("chamou a rede direto, por fora do OpenClaw")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(urllib.request, "urlopen", sem_rede)
    monkeypatch.setattr(cli, "_render_setup_chart_image", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_signal_chart_image", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "NOTIFY_BLOCKING", True)
    monkeypatch.setattr(scanner, "OUTBOX_PATH", tmp_path / "outbox.jsonl")
    monkeypatch.setattr(scanner, "_record_dashboard_signals", None, raising=False)
    return enviados


def _opcao(cmd: list[str], nome: str) -> str | None:
    return cmd[cmd.index(nome) + 1] if nome in cmd else None


def _sinal() -> dict:
    return {
        "exchange": "hyperliquid",
        "symbol": "WLD/USDC:USDC",
        "setup": "institutional-strict",
        "side": "long",
        "timeframe": "1h",
        "reason": "teste",
        "entry_price": 1.2345,
        "stop_price": 1.1111,
        "take_profit": 1.5555,
        "targets": [1.3, 1.4, 1.5, 1.6],
        "leverage": 5,
        "risk_profile": "moderate",
        "created_at": 1784846103.5,
        "bar_at": "2026-07-25T13:00:00+00:00",
    }


def _entrada() -> dict[str, str]:
    linha = (
        "2026-09-25 10:00:00 INFO setup-live entry | hybrid BTC/USDT | side=long | mode=dry-run "
        "| entry=100 | stop=95 | tp=110 | targets=105,110,115,120 | reason=teste"
    )
    match = watcher.ENTRY_RE.match(linha)
    assert match is not None
    return match.groupdict()


def _publicar_scanner() -> None:
    scanner._send_signals([_sinal()])


def _publicar_watcher() -> None:
    watcher._send([_entrada()])


PUBLICADORES = pytest.mark.parametrize("publicar", [_publicar_scanner, _publicar_watcher], ids=["scanner", "watcher"])


@PUBLICADORES
def test_sai_pelo_openclaw_no_canal_escolhido(comandos, monkeypatch, publicar) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "-100200")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_THREAD_ID", "77")
    publicar()
    assert len(comandos) == 1
    assert comandos[0][1:3] == ["message", "send"]
    assert _opcao(comandos[0], "--channel") == "telegram"
    assert _opcao(comandos[0], "--thread-id") == "77"


@PUBLICADORES
def test_discord_sai_pelo_openclaw_mesmo_com_token_de_bot(comandos, monkeypatch, publicar) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token-que-nao-deve-ser-usado")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "123")
    publicar()
    assert len(comandos) == 1
    assert _opcao(comandos[0], "--channel") == "discord"
    assert _opcao(comandos[0], "--target") == "channel:123"


@PUBLICADORES
def test_sem_destino_nada_e_enviado(comandos, publicar) -> None:
    publicar()
    assert comandos == []


@PUBLICADORES
def test_sem_conta_escolhida_o_openclaw_usa_a_dele(comandos, monkeypatch, publicar) -> None:
    """Scanner e watcher impunham `--account default`."""
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "123")
    publicar()
    assert all("--account" not in cmd for cmd in comandos)


@PUBLICADORES
def test_whatsapp_so_com_opt_in(comandos, monkeypatch, publicar) -> None:
    """O scanner ligava o WhatsApp so por haver destino; o `cli.py` exige opt-in."""
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET", "+5511999999999")
    publicar()
    assert comandos == []


@PUBLICADORES
def test_sem_audiencia_fixa(comandos, monkeypatch, publicar) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "telegram")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "-100200")
    publicar()
    mensagem = _opcao(comandos[0], "--message") or ""
    assert "club member" not in mensagem.lower()


def test_audiencia_configurada_aparece(comandos, monkeypatch) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_DISCORD_AUDIENCE", "@Membros")
    assert "@Membros" in scanner._format_signal_notice(_sinal())
    assert "@Membros" in watcher._format_message(_entrada())


def test_scanner_entrega_o_grafico_que_ele_renderizou(comandos, monkeypatch, tmp_path) -> None:
    """O scanner renderiza o grafico no widget canonico; a entrega usa esse, sem re-renderizar."""
    grafico = tmp_path / "grafico.png"
    grafico.write_bytes(b"png")
    monkeypatch.setattr(scanner, "_signal_chart_image", lambda *a, **k: grafico)
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID", "123")
    _publicar_scanner()
    assert _opcao(comandos[0], "--media") == str(grafico)


def test_scanner_registra_o_resultado_da_entrega_no_outbox(comandos, monkeypatch) -> None:
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_CHANNEL", "discord")
    monkeypatch.setenv("SETUP_NOTIFY_ENTRY_TARGET", "channel:123")
    _publicar_scanner()
    eventos = [json.loads(linha) for linha in scanner.OUTBOX_PATH.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in eventos] == ["signal_detected", "publish_attempted"]
    assert eventos[-1]["delivery"] == {"discord_message_id": "m-1"}


@pytest.mark.parametrize("arquivo", ["ccxt_entry_scanner.py", "discord_signal_watcher.py"])
def test_nenhum_caminho_direto_para_a_api_do_discord(arquivo: str) -> None:
    fonte = (ROOT / "workspace" / arquivo).read_text(encoding="utf-8")
    assert "discord.com/api" not in fonte
    assert "DISCORD_BOT_TOKEN" not in fonte
    assert "openclaw.json" not in fonte
    assert "urllib" not in fonte


ENTREGA_NO_CONFIG_ENV = (
    "SETUP_NOTIFY_ENTRY_ENABLED",
    "SETUP_NOTIFY_ENTRY_CHANNEL",
    "SETUP_NOTIFY_ENTRY_TARGET",
    "SETUP_NOTIFY_ENTRY_ACCOUNT",
    "SETUP_NOTIFY_ENTRY_THREAD_ID",
    "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID",
    "SETUP_NOTIFY_ENTRY_DISCORD_ACCOUNT",
    "SETUP_NOTIFY_WHATSAPP_ENABLED",
    "SETUP_NOTIFY_ENTRY_WHATSAPP_TARGET",
    "SETUP_NOTIFY_ENTRY_WHATSAPP_ACCOUNT",
)


def test_config_env_carrega_toda_a_configuracao_de_entrega(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A allowlist aceitava canal e destino, mas descartava em silencio conta,
    topico do Telegram e WhatsApp -- a entrega saia sem o topico escolhido."""
    from workspace import run

    for nome in ENTREGA_NO_CONFIG_ENV:
        monkeypatch.delenv(nome, raising=False)
    arquivo = tmp_path / "config.env"
    arquivo.write_text("".join(f"{nome}=valor\n" for nome in ENTREGA_NO_CONFIG_ENV), encoding="utf-8")
    run._load_key_value_file(arquivo, allowed_keys=run.NON_SECRET_CONFIG_ENV)
    assert [n for n in ENTREGA_NO_CONFIG_ENV if os.environ.get(n) != "valor"] == []
