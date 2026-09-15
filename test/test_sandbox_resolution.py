"""Sandbox: uma pergunta, um veredito.

`sandbox` decide se a ordem vai para dinheiro de brinquedo ou dinheiro real.
Hoje quatro lugares respondem essa mesma pergunta com regras diferentes:

| onde | precedencia | vocabulario | default |
|---|---|---|---|
| `_load_cex_sandbox` (cli) | generica `CEX_SANDBOX` ganha | `{1,true,yes,sim}` | kraken -> True |
| `_load_pair_cex_sandbox` (cli) | especifica `<PREFIX>_SANDBOX` ganha | idem | kraken -> True |
| `venue_summary` (venues.config) | generica ganha | string crua | `"true"`/`"false"` |
| `run.py` safe_defaults | generica, senao o summary | string crua | `"false"` |

Alem de discordarem entre si, os dois primeiros tratam qualquer palavra fora
do vocabulario como falso -- e falso aqui significa producao. `CEX_SANDBOX=ture`
basta.

Estes testes fixam o contrato unico antes da implementacao existir.
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
from workspace.venues.sandbox import (  # noqa: E402
    default_sandbox,
    resolve_sandbox,
    sandbox_env_names,
    venue_chain,
)


@pytest.fixture(autouse=True)
def _isola_settings_local(tmp_path: Path, monkeypatch) -> None:
    """Isola a suite do `settings.local.json` real da maquina.

    `_local_settings_path` procura, em ordem: `DELTA_NEUTRAL_SETTINGS_DIR`,
    `~/.config/openclaw/<skill>/` e a raiz do repo -- devolvendo o **primeiro
    que existir**. Por isso apontar o override para um `tmp_path` vazio nao
    basta: sem arquivo la, a busca cai no home e a suite passa a medir o
    settings do operador. E o home precisa ser falso tambem, porque ha teste
    que remove o override de proposito para exercitar o fallback.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))


def _settings(tmp_path: Path, *, versioned=None, local=None, env=None) -> Settings:
    (tmp_path / "settings.json").write_text(json.dumps(versioned or {}), encoding="utf-8")
    (tmp_path / "settings.local.json").write_text(json.dumps(local or {}), encoding="utf-8")
    return load_settings(root=tmp_path, env=env or {})


# --- o defeito que motivou a mudanca ----------------------------------------


def test_typo_no_sandbox_nao_vira_producao_em_silencio(tmp_path: Path) -> None:
    """`ture` nao e falso: e erro de quem digitou, e precisa parar o boot.

    Este e o defeito concreto. Nos leitores antigos o valor caia no `else`
    implicito e o bot abria ordem com dinheiro real achando que estava em
    sandbox.
    """
    s = _settings(tmp_path, env={"CEX_SANDBOX": "ture"})
    with pytest.raises(ConfigError) as exc:
        resolve_sandbox("cex", "binance", settings=s)
    assert "ture" in str(exc.value)


def test_vocabulario_aceita_os_dois_lados(tmp_path: Path) -> None:
    for valor in ("1", "true", "yes", "sim", "on", "y", "s", "TRUE", " true "):
        s = _settings(tmp_path, env={"CEX_SANDBOX": valor})
        assert resolve_sandbox("cex", "binance", settings=s) is True, valor
    for valor in ("0", "false", "no", "nao", "não", "off", "n", "FALSE"):
        s = _settings(tmp_path, env={"CEX_SANDBOX": valor})
        assert resolve_sandbox("cex", "binance", settings=s) is False, valor


# --- precedencia unica ------------------------------------------------------


def test_env_especifica_vence_env_generica(tmp_path: Path) -> None:
    """Antes, `_load_cex_sandbox` dizia o contrario de `_load_pair_cex_sandbox`
    para exatamente este ambiente."""
    s = _settings(tmp_path, env={"CEX_SANDBOX": "false", "BINANCE_SANDBOX": "true"})
    assert resolve_sandbox("cex", "binance", settings=s) is True


def test_env_vence_settings(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"sandbox": True}}},
        env={"CEX_SANDBOX": "false"},
    )
    assert resolve_sandbox("cex", "binance", settings=s) is False


def test_settings_por_venue_vence_settings_generico(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"sandbox": False, "binance": {"sandbox": True}}}},
    )
    assert resolve_sandbox("cex", "binance", settings=s) is True


def test_settings_sozinho_decide(tmp_path: Path) -> None:
    """Sem env nenhuma, o arquivo manda -- hoje o settings e letra morta aqui."""
    s = _settings(tmp_path, versioned={"venues": {"cex": {"sandbox": True}}})
    assert resolve_sandbox("cex", "binance", settings=s) is True


def test_env_vazia_conta_como_nao_definida(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"sandbox": True}}},
        env={"CEX_SANDBOX": ""},
    )
    assert resolve_sandbox("cex", "binance", settings=s) is True


# --- defaults ---------------------------------------------------------------


def test_default_kraken_e_sandbox_e_o_resto_nao(tmp_path: Path) -> None:
    """Default conservador so existe para a Kraken; toda outra CEX nasce em
    producao. Fica explicito num teste porque e uma assimetria perigosa que
    antes so aparecia lida de dentro do helper."""
    s = _settings(tmp_path)
    assert resolve_sandbox("cex", "kraken", settings=s) is True
    assert resolve_sandbox("cex", "krakenfutures", settings=s) is True
    assert resolve_sandbox("cex", "binance", settings=s) is False
    assert default_sandbox("cex", "kraken") is True
    assert default_sandbox("cex", "binance") is False


def test_dex_usa_a_familia_dex(tmp_path: Path) -> None:
    s = _settings(tmp_path, env={"DEX_SANDBOX": "true"})
    assert resolve_sandbox("dex", "hyperliquid", settings=s) is True
    s = _settings(tmp_path, env={"DEX_SANDBOX": "true", "HYPERLIQUID_SANDBOX": "false"})
    assert resolve_sandbox("dex", "hyperliquid", settings=s) is False


# --- nome de env ------------------------------------------------------------


def test_prefixo_com_pontuacao_gera_nome_de_env_valido() -> None:
    """`binance.us` virava `BINANCE.US_SANDBOX` num dos helpers -- nome que
    nenhum shell consegue exportar, entao a env especifica era inalcancavel."""
    assert sandbox_env_names("cex", "binance.us") == ("BINANCE_US_SANDBOX", "CEX_SANDBOX")
    assert all(nome.replace("_", "").isalnum() for nome in sandbox_env_names("cex", "binance.us"))


def test_venue_vazia_cai_direto_na_generica() -> None:
    assert sandbox_env_names("cex", "") == ("CEX_SANDBOX",)


# --- os chamadores concordam ------------------------------------------------


def test_os_dois_caminhos_do_cli_dao_a_mesma_resposta(monkeypatch) -> None:
    """O par de helpers do cli respondia diferente para o mesmo ambiente.
    Este teste falha se algum deles voltar a ter regra propria."""
    from workspace import cli

    monkeypatch.setenv("CEX_SANDBOX", "false")
    monkeypatch.setenv("BINANCE_SANDBOX", "true")
    assert cli._load_cex_sandbox("binance") == cli._load_pair_cex_sandbox("binance") is True


def test_resumo_de_venue_concorda_com_o_resolvedor(monkeypatch) -> None:
    """`venue_summary` alimenta o painel e o `run.py`. Se ele disser `false`
    enquanto a ordem vai para sandbox, o operador le o oposto do que acontece."""
    from workspace.venues import config as venues_config

    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.setenv("CEX_SANDBOX", "false")
    monkeypatch.setenv("BINANCE_SANDBOX", "true")
    assert venues_config.venue_summary()["cex_sandbox"] == "true"


# --- o diagnostico continua respondendo ------------------------------------


def test_setup_check_reporta_config_invalida_em_vez_de_estourar(monkeypatch) -> None:
    """`setup-check` e rodado justamente quando algo esta errado.

    Antes da validacao existir nada estourava; agora `venue_summary` levanta
    `ConfigError` num typo, e o comando de diagnostico precisa transformar isso
    em achado do relatorio -- senao o operador troca um valor errado por um
    traceback e fica sem diagnostico nenhum.
    """
    import workspace.run as run

    def explode() -> dict:
        raise ConfigError("valor booleano invalido para 'venues.cex.sandbox': 'ture'")

    monkeypatch.setattr(run, "venue_summary", explode)
    monkeypatch.setattr(run, "_ensure_venv_ready", lambda: {})
    monkeypatch.setattr(run, "_dependency_status", lambda python=None: {name: True for name in run.PROBED_MODULES})

    report = run.setup_check()
    assert "ture" in str(report["venues_error"])
    assert report["venues"] == {}


def test_env_example_nao_traz_sandbox_descomentada() -> None:
    """O `.env.example` vence o settings por desenho.

    Enquanto `CEX_SANDBOX=false` vinha descomentado, quem copiava o exemplo
    ganhava producao fixada no ambiente e o settings nascia inoperante -- foi
    exatamente o que aconteceu com as `TRIANGLE_*` na fatia anterior.
    """
    linhas = (ROOT / "workspace" / ".env.example").read_text(encoding="utf-8").splitlines()
    ativas = [ln for ln in linhas if "_SANDBOX=" in ln and not ln.lstrip().startswith("#")]
    # `HYPERLIQUID_SANDBOX` segue ativa: a Hyperliquid ainda nao consome o
    # resolvedor, entao comenta-la aqui a deixaria sem configuracao nenhuma.
    # Ela sai na fatia que migra o caller.
    ativas = [ln for ln in ativas if not ln.startswith("HYPERLIQUID_SANDBOX")]
    assert ativas == [], f"env de sandbox descomentada mata o settings: {ativas}"


def test_settings_example_usa_as_chaves_que_o_codigo_le(tmp_path: Path) -> None:
    """Exemplo que nao resolve e pior que exemplo nenhum: ele ensina errado."""
    exemplo = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    s = _settings(tmp_path, versioned=exemplo)
    # A familia inteira, nao so o id exato: `venues.cex.kraken` precisa
    # alcancar as variantes, senao o exemplo manda `krakenfutures` para
    # producao.
    for vid in ("kraken", "krakenfutures", "kraken-futures", "kraken-spot"):
        assert resolve_sandbox("cex", vid, settings=s) is True, vid
    assert resolve_sandbox("cex", "binance", settings=s) is False


def test_cmd_venues_explica_em_vez_de_dar_traceback(monkeypatch) -> None:
    """`venues` e o comando que existe para mostrar a configuracao."""
    import argparse

    from workspace import cli

    monkeypatch.setenv("CEX_ID", "binance")
    monkeypatch.setenv("CEX_SANDBOX", "ture")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_venues(argparse.Namespace())
    assert "ture" in str(exc.value)


# --- achados do code-review da PR #10 ---------------------------------------


def test_familia_vale_tambem_para_as_chaves_de_settings(tmp_path: Path) -> None:
    """A familia existia so para env: `venues.cex.kraken.sandbox` nao alcancava
    `krakenfutures`, que caia na chave generica e ia para producao."""
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"sandbox": False, "kraken": {"sandbox": True}}}},
    )
    for vid in ("kraken", "krakenfutures", "kraken-futures", "kraken-spot"):
        assert resolve_sandbox("cex", vid, settings=s) is True, vid
    assert resolve_sandbox("cex", "binance", settings=s) is False


def test_chave_da_propria_venue_vence_a_da_familia(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        versioned={
            "venues": {"cex": {"kraken": {"sandbox": True}, "krakenfutures": {"sandbox": False}}}
        },
    )
    assert resolve_sandbox("cex", "krakenfutures", settings=s) is False
    assert resolve_sandbox("cex", "kraken", settings=s) is True


def test_exemplo_nao_distribui_sandbox_generico(tmp_path: Path) -> None:
    """Um `venues.<tipo>.sandbox: false` no exemplo derruba o default derivado
    de quem copiar -- a mesma classe da env descomentada no `.env.example`."""
    exemplo = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    for tipo, bloco in (exemplo.get("venues") or {}).items():
        assert "sandbox" not in bloco, f"venues.{tipo}.sandbox no exemplo derruba default derivado"


def test_camada_local_vence_chave_mais_especifica_do_versionado(tmp_path: Path) -> None:
    """Camada e o eixo externo. Ordenar so por especificidade fazia o arquivo
    do time derrubar o do operador -- o oposto do que o sistema promete."""
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"binance": {"sandbox": False}}}},
        local={"venues": {"cex": {"sandbox": True}}},
    )
    assert resolve_sandbox("cex", "binance", settings=s) is True


def test_erro_nomeia_a_env_que_o_operador_escreveu(tmp_path: Path) -> None:
    """Apontar para uma chave de arquivo que pode nem existir nao e
    acionavel -- e o PR inteiro existe para tornar o typo acionavel."""
    s = _settings(tmp_path, env={"BINANCE_SANDBOX": "ture"})
    with pytest.raises(ConfigError) as exc:
        resolve_sandbox("cex", "binance", settings=s)
    assert "BINANCE_SANDBOX" in str(exc.value)


def test_chave_generica_mais_forte_avisa_ao_engolir_a_especifica(tmp_path: Path, caplog) -> None:
    """O arquivo do operador manda -- mas perder uma declaracao de seguranca
    do time em silencio, nao."""
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"kraken": {"sandbox": True}}}},
        local={"venues": {"cex": {"sandbox": False}}},
    )
    with caplog.at_level("WARNING"):
        assert resolve_sandbox("cex", "kraken", settings=s) is False
    assert "venues.cex.kraken.sandbox" in caplog.text


def test_nado_nao_anuncia_sandbox_que_nao_existe() -> None:
    """O adapter da Nado e construido so de `NADO_NETWORK` e nunca chama este
    resolvedor: anunciar `NADO_SANDBOX` seria prometer config inerte."""
    assert venue_chain("nado") == ("nado",)
    assert "NADO_SANDBOX" not in sandbox_env_names("dex", "nado-dex")


def test_fixture_isola_o_settings_local_do_operador(tmp_path: Path) -> None:
    """A fixture precisa neutralizar os tres candidatos, nao so o override.

    A primeira versao so apontava `DELTA_NEUTRAL_SETTINGS_DIR` para um
    `tmp_path` vazio -- e como `_local_settings_path` devolve o primeiro
    caminho que **existe**, a busca caia no home e a suite media o
    `settings.local.json` real do operador.
    """
    from workspace.config import _local_settings_path

    # home falso e vazio: o candidato do meio nao pode ser escolhido
    assert not (tmp_path / "home" / ".config").exists()
    assert _local_settings_path(ROOT) == ROOT / "settings.local.json"

    # com arquivo no override, ele vence
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    assert _local_settings_path(ROOT).parent == tmp_path


# --- achados do terceiro passe de code-review -------------------------------


def test_aviso_so_sai_quando_os_valores_divergem(tmp_path: Path, caplog) -> None:
    """Avisar com as duas chaves declarando o mesmo nao relata perda nenhuma,
    e num aviso de seguranca treina o operador a ignora-lo."""
    s = _settings(
        tmp_path,
        versioned={"venues": {"cex": {"kraken": {"sandbox": True}}}},
        local={"venues": {"cex": {"sandbox": True}}},
    )
    with caplog.at_level("WARNING"):
        assert resolve_sandbox("cex", "kraken", settings=s) is True
    assert caplog.text == ""
