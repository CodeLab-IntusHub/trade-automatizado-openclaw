"""Não existe venue padrão: cada operador escolhe onde opera.

Até a v1.8.0, `DEX_ID` ausente virava `nado` e `CEX_ID` ausente virava
`kraken` — a escolha da instância original aplicada a quem não escolheu nada.
Agora venue não escolhida fica vazia, e o comando que precisa dela para com uma
mensagem que diz o que escolher. Um comando que não precisa daquela ponta
segue com um substituto que recusa operar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import cli
from workspace.venues.config import selected_venues, venue_summary

ENVS_DE_VENUE = (
    "DEX_ID",
    "TRADE_DEX_ID",
    "PRIMARY_DEX",
    "CEX_ID",
    "TRADE_CEX_ID",
    "PRIMARY_CEX",
)


@pytest.fixture
def sem_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ENVS_DE_VENUE:
        monkeypatch.delenv(nome, raising=False)
    # `build_engine` carrega o `.env` do operador; aqui não pode.
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)


class _FakeCex:
    venue = "futures"
    account = "flex"
    account_symbol = ""
    api_fingerprint = "test"
    sandbox = False

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def get_symbol_to_product_map(
        self, product_filter: object = None
    ) -> dict[str, str]:
        return {"BTC/USDT": "BTC/USD:USD"}


class _FakeDex:
    def get_symbol_to_product_map(
        self, product_filter: object = None
    ) -> dict[str, str]:
        return {"ETH/USDT": "ETH/USDC:USDC"}


def test_sem_escolha_nenhuma_venue_e_assumida(sem_venue: None) -> None:
    selecao = selected_venues()
    assert selecao.dex_id == ""
    assert selecao.cex_id == ""


def test_a_escolha_do_operador_e_respeitada(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEX_ID", "Hyperliquid")
    monkeypatch.setenv("CEX_ID", "bybit")
    selecao = selected_venues()
    assert (selecao.dex_id, selecao.cex_id) == ("hyperliquid", "bybit")


def test_dex_exigida_e_nao_escolhida_para_com_mensagem(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "kraken")
    monkeypatch.setattr(cli, "KrakenTrader", _FakeCex)
    with pytest.raises(SystemExit) as erro:
        cli.build_engine(require_nado=True, require_kraken=False)
    assert "DEX_ID" in str(erro.value)
    assert "nenhuma foi escolhida" in str(erro.value)


def test_cex_exigida_e_nao_escolhida_para_com_mensagem(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEX_ID", "hyperliquid")
    monkeypatch.setattr(cli, "_build_hyperliquid_trader", lambda *a, **k: _FakeDex())
    with pytest.raises(SystemExit) as erro:
        cli.build_engine(require_nado=False, require_kraken=True)
    assert "CEX_ID" in str(erro.value)
    assert "nenhuma foi escolhida" in str(erro.value)


def test_nenhuma_venue_escolhida_para_com_mensagem(sem_venue: None) -> None:
    with pytest.raises(SystemExit) as erro:
        cli.build_engine(require_nado=False, require_kraken=False)
    assert "DEX_ID" in str(erro.value) and "CEX_ID" in str(erro.value)


def test_so_cex_escolhida_opera_sem_dex(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "kraken")
    monkeypatch.setenv("KRAKEN_API_KEY", "k")
    monkeypatch.setenv("KRAKEN_API_SECRET", "s")
    monkeypatch.setattr(cli, "KrakenTrader", _FakeCex)
    engine = cli.build_engine(require_nado=False, require_kraken=True)
    assert engine.dex_id == ""
    assert engine.nado.get_all_positions() == []
    with pytest.raises(RuntimeError):
        engine.nado.place_market_order("BTC/USDT", 1, True)


def test_so_dex_escolhida_opera_sem_cex(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEX_ID", "hyperliquid")
    monkeypatch.setattr(cli, "_build_hyperliquid_trader", lambda *a, **k: _FakeDex())
    engine = cli.build_engine(require_nado=True, require_kraken=False)
    assert engine.cex_id == ""
    assert engine.kraken.get_symbol_to_product_map() == {"ETH/USDT": 0}
    assert engine.kraken.get_all_positions() == []
    with pytest.raises(RuntimeError):
        engine.kraken.place_market_order("ETH/USDT", 1, True)


def test_resumo_de_venues_sem_escolha_nao_quebra(sem_venue: None) -> None:
    resumo = venue_summary()
    assert resumo["dex_id"] == ""
    assert resumo["cex_id"] == ""
    assert resumo["dex_adapter"] == "nao_escolhida"
    assert resumo["cex_adapter"] == "nao_escolhida"
    assert resumo["cex_credentials_configured"] is False


def test_env_example_nao_escolhe_venue() -> None:
    exemplo = (ROOT / "workspace" / ".env.example").read_text(encoding="utf-8")
    linhas = {
        linha.split("=", 1)[0]: linha.split("=", 1)[1]
        for linha in exemplo.splitlines()
        if linha.startswith(("DEX_ID=", "CEX_ID="))
    }
    assert linhas["DEX_ID"].split("#", 1)[0].strip() == ""
    assert linhas["CEX_ID"].split("#", 1)[0].strip() == ""


def test_nenhum_default_de_venue_no_resolvedor() -> None:
    fonte = (ROOT / "workspace" / "venues" / "config.py").read_text(encoding="utf-8")
    assert 'or "nado"' not in fonte
    assert 'or "kraken"' not in fonte


def _recorder(tmp_path: Path):
    from workspace.trade_dashboard import TradeDashboardRecorder

    return TradeDashboardRecorder(
        state_path=tmp_path / "dashboard.json",
        html_path=tmp_path / "dashboard.html",
        setup_state_path=tmp_path / "setup_live_state.json",
    )


def test_dashboard_com_so_cex_sincroniza_sem_exigir_dex(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from workspace import run

    monkeypatch.setattr(run, "_load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("CEX_ID", "kraken")
    monkeypatch.setenv("KRAKEN_API_KEY", "k")
    monkeypatch.setenv("KRAKEN_API_SECRET", "s")

    class _CexComPosicoes(_FakeCex):
        def get_all_positions(self) -> list:
            return []

    monkeypatch.setattr(cli, "KrakenTrader", _CexComPosicoes)
    recorder = _recorder(tmp_path)
    recorder.sync_live_exposures(flush=False)
    assert recorder.state["live_exposures"]["error"] == ""


def test_dashboard_sem_venue_registra_erro_em_vez_de_encerrar(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`SystemExit` nao e `Exception`: sem tratamento, derrubava o publisher."""
    from workspace import run

    monkeypatch.setattr(run, "_load_env_file", lambda *a, **k: None)
    recorder = _recorder(tmp_path)
    recorder.sync_live_exposures(flush=False)
    assert "Nenhuma venue escolhida" in recorder.state["live_exposures"]["error"]


def _doctor_sem_venv(monkeypatch: pytest.MonkeyPatch):
    from workspace import run

    monkeypatch.setattr(run, "_ensure_venv_ready", dict)
    monkeypatch.setattr(
        run,
        "_dependency_status",
        lambda python=None: {n: True for n in run.PROBED_MODULES},
    )
    return run


def test_doctor_reprova_sem_venue_escolhida(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _doctor_sem_venv(monkeypatch)
    relatorio = run.doctor()
    checks = {c["name"]: c for c in relatorio["checks"]}
    assert checks["venue_escolhida"]["ok"] is False
    assert "venue_escolhida" in run.BLOCKING_CHECKS
    assert relatorio["status"] == "attention"
    # sem CEX escolhida, nao ha credencial de CEX para cobrar
    assert "cex_credentials" not in checks


def test_doctor_aceita_so_uma_venue(
    sem_venue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CEX_ID", "bybit")
    run = _doctor_sem_venv(monkeypatch)
    checks = {c["name"]: c for c in run.doctor()["checks"]}
    assert checks["venue_escolhida"]["ok"] is True
    assert "cex_credentials" in checks
    assert not any(
        nome.startswith(("nado_", "hyperliquid_", "dex_adapter")) for nome in checks
    )
