"""Chave desconhecida no settings deixa de ser ignorada em silêncio.

Um typo no nome de uma chave não produzia erro nenhum: a chave simplesmente
não era lida, o código caía no default, e o operador via o comando rodar
achando que a configuração dele valia. Medido antes da correção:

    venues.cex.binance.sandbxo: true   -> resolvido False   PRODUÇÃO
    venues.cex.binanse.sandbox: true   -> resolvido False   PRODUÇÃO
    venues.cexs.kraken.sandbox: false  -> resolvido True
    setups.triangle-breakout.pivot_windwo: 9 -> efetivo 2

Os dois primeiros mandam dinheiro real. E `validate_setup_settings`, que existe
justamente para o erro aparecer no boot, passava por todos eles sem reclamar --
ela valida os valores das chaves que conhece, e um typo produz uma chave que
ela não conhece.

Esta é a contrapartida necessária da fatia anterior: a documentação passou a
mandar escrever `venues.cex.binance.sandbox` no arquivo, então a correção
dependia de o operador não errar de digitar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import ConfigError  # noqa: E402
from workspace.settings_schema import validar_settings  # noqa: E402


def _erros(payload: dict) -> list[str]:
    return validar_settings(payload, origem="settings.json")


def test_settings_example_passa_pelo_schema() -> None:
    """O exemplo que distribuímos tem que ser válido.

    Este é o teste que impede o erro mais caro desta mudança: um schema
    incompleto rejeitaria configuração legítima e derrubaria o boot de quem
    copiou o exemplo -- trocando uma falha silenciosa por uma barulhenta e
    errada.
    """
    payload = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    assert _erros(payload) == []


def test_chave_de_comentario_e_aceita_em_qualquer_nivel() -> None:
    """`_comentario` é como o exemplo documenta a si mesmo."""
    assert _erros({"_comentario": "x", "venues": {"_comentario": "y", "cex": {}}}) == []


@pytest.mark.parametrize("payload,esperado", [
    ({"venues": {"cex": {"binance": {"sandbxo": True}}}}, "sandbxo"),
    ({"venues": {"cexs": {"kraken": {"sandbox": True}}}}, "cexs"),
    ({"setups": {"triangle-breakuot": {"pivot_window": 2}}}, "triangle-breakuot"),
    ({"setups": {"triangle-breakout": {"pivot_windwo": 2}}}, "pivot_windwo"),
    ({"setupz": {}}, "setupz"),
    ({"venues": {"cex": {"kraken": {"sandbox": True, "sandbox_extra": 1}}}}, "sandbox_extra"),
])
def test_chave_desconhecida_vira_erro(payload, esperado) -> None:
    erros = _erros(payload)
    assert erros, f"passou em silêncio: {payload}"
    assert any(esperado in e for e in erros), erros


def test_erro_sugere_a_chave_certa() -> None:
    """Dizer "chave desconhecida" sem dizer qual era a certa devolve o operador
    ao mesmo lugar: relendo a documentação para achar um typo de uma letra."""
    (erro,) = _erros({"setups": {"triangle-breakout": {"pivot_windwo": 2}}})
    assert "pivot_window" in erro
    assert "setups.triangle-breakout" in erro, erro


def test_parametro_valido_no_setup_errado_e_erro() -> None:
    """`pivot_window` existe -- mas não no `funding-arb`. Uma lista única de
    parâmetros aceitaria isso, e a chave ficaria morta do mesmo jeito."""
    erros = _erros({"setups": {"funding-arb": {"pivot_window": 2}}})
    assert erros and "pivot_window" in erros[0], erros


def test_variantes_de_timeframe_do_divergence_sao_validas() -> None:
    """A chave do divergence é gerada com sufixo de timeframe."""
    for chave in ("divergence-and-volume", "divergence-and-volume-15m",
                  "divergence-and-volume-1h", "divergence-and-volume-4h"):
        assert _erros({"setups": {chave: {"rsi_period": 14}}}) == [], chave
    assert _erros({"setups": {"divergence-and-volume-2h": {"rsi_period": 14}}}) != []


def test_venue_desconhecida_na_cex_e_erro_com_sugestao() -> None:
    """`binanse` não é exchange nenhuma: a chave morre e a venue cai no default,
    que para toda CEX fora da família kraken é produção."""
    erros = _erros({"venues": {"cex": {"binanse": {"sandbox": True}}}})
    assert erros, "venue inexistente passou"
    assert "binance" in erros[0], erros


def test_variantes_internas_de_venue_sao_validas() -> None:
    """`kraken-spot` e `krakenfutures` não estão em `ccxt.exchanges`, mas são
    seleções aceitas pelo código."""
    for venue in ("kraken", "kraken-spot", "krakenfutures", "kraken_futures", "binance", "hyperliquid"):
        assert _erros({"venues": {"cex": {venue: {"sandbox": True}}}}) == [], venue


def test_dex_custom_mantem_o_id_aberto() -> None:
    """DEX por adapter (`DEX_ADAPTER_MODULE`) tem id arbitrário por desenho."""
    assert _erros({"venues": {"dex": {"meu-dex-interno": {"sandbox": True}}}}) == []
    # o nível da folha continua fechado, mesmo com o id aberto
    assert _erros({"venues": {"dex": {"meu-dex-interno": {"sandbxo": True}}}}) != []


def test_sandbox_generico_por_tipo_continua_valido() -> None:
    """`venues.cex.sandbox` convive com `venues.cex.<venue>.sandbox`: um é
    escalar, o outro é objeto, no mesmo nível."""
    assert _erros({"venues": {"cex": {"sandbox": False, "kraken": {"sandbox": True}}}}) == []


def test_o_erro_nomeia_o_arquivo_de_origem() -> None:
    """Com dois arquivos na precedência, "chave desconhecida" sem dizer em qual
    deles manda o operador procurar no lugar errado."""
    (erro,) = validar_settings({"setupz": {}}, origem="settings.local.json")
    assert "settings.local.json" in erro, erro


def test_boot_derruba_com_chave_desconhecida(tmp_path: Path, monkeypatch) -> None:
    """`validate_setup_settings` é o gancho de boot; é lá que tem que doer."""
    from workspace.config import load_settings
    from workspace.core.setups import validate_setup_settings

    (tmp_path / "settings.json").write_text(
        json.dumps({"setups": {"triangle-breakout": {"pivot_windwo": 9}}}), encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))
    with pytest.raises(ConfigError) as exc:
        validate_setup_settings(settings=load_settings(root=tmp_path))
    assert "pivot_windwo" in str(exc.value)


def test_schema_cobre_toda_chave_que_o_codigo_le() -> None:
    """A direção perigosa do drift: o schema rejeitar config legítima.

    Se o código passar a ler `setups.X.novo_campo` e ninguém tocar no schema, o
    operador que declarar esse campo -- seguindo a documentação -- vê o boot
    cair. Aqui o `Settings` é instrumentado para registrar toda chave que os
    getters de setup pedem, e cada uma tem que ser aceita pelo schema.
    """
    from workspace.config import Settings
    from workspace.core import setups as mod

    pedidas: list[str] = []
    original = Settings._require

    def espiao(self, dotted, env, default):
        pedidas.append(dotted)
        return original(self, dotted, env, default)

    Settings._require = espiao  # type: ignore[method-assign]
    try:
        mod.validate_setup_settings(settings=Settings(versioned={}, local={}, env={}))
    finally:
        Settings._require = original  # type: ignore[method-assign]

    assert pedidas, "nenhuma chave registrada -- o espião não pegou nada"
    for dotted in sorted(set(pedidas)):
        partes = dotted.split(".")
        payload: dict = {}
        no = payload
        for parte in partes[:-1]:
            no[parte] = {}
            no = no[parte]
        no[partes[-1]] = 1
        assert _erros(payload) == [], f"o código lê '{dotted}', mas o schema recusa"


def _doctor_em(tmp_path: Path, monkeypatch, payload: dict):
    import sys as _sys

    import workspace.config as config
    from workspace import run

    (tmp_path / "settings.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(run, "_venv_python", lambda: Path(_sys.executable))
    return run, run.doctor()


def test_doctor_reporta_chave_desconhecida(tmp_path: Path, monkeypatch) -> None:
    """O operador edita o settings e roda `setup-check`, não `setup-live`.

    Reportar só no boot do live deixa a descoberta para o momento em que já há
    ordem para abrir.
    """
    run, report = _doctor_em(tmp_path, monkeypatch, {"venues": {"cex": {"kraken": {"sandbxo": True}}}})
    assert report["settings_error"], "chave morta não apareceu no relatório"
    assert "sandbxo" in report["settings_error"]
    check = next(c for c in report["checks"] if c["name"] == "settings_schema")
    assert check["ok"] is False


def test_doctor_nao_reclama_de_settings_valido(tmp_path: Path, monkeypatch) -> None:
    """Contraprova: sem ela, o teste acima passaria com um check sempre falso."""
    _run, report = _doctor_em(tmp_path, monkeypatch, {"venues": {"cex": {"kraken": {"sandbox": True}}}})
    assert report["settings_error"] is None
    check = next(c for c in report["checks"] if c["name"] == "settings_schema")
    assert check["ok"] is True


def test_settings_schema_conta_para_o_veredito() -> None:
    """Asserção direta, porque a indireta não podia falhar.

    A primeira versão deste teste afirmava `status == "attention"` no cenário
    da chave morta. Uma mutação que removia `settings_schema` de
    `BLOCKING_CHECKS` **sobreviveu**: `venv_ready` também falha no ambiente de
    teste, então o veredito era `attention` de qualquer jeito e a asserção não
    discriminava nada. `doctor` devolvendo `ok` com config morta é o mesmo
    defeito que o corte `checks[:4]` produziu com o `venues_config`.
    """
    from workspace import run

    assert "settings_schema" in run.BLOCKING_CHECKS


def test_veredito_vira_attention_por_causa_deste_check() -> None:
    """Prova que pertencer a `BLOCKING_CHECKS` de fato muda o veredito, com
    todos os outros checks passando -- o que o ambiente de teste não permite
    montar de verdade."""
    from workspace import run

    checks = [{"name": nome, "ok": True, "detail": ""} for nome in sorted(run.BLOCKING_CHECKS)]
    assert all(c["ok"] for c in checks if c["name"] in run.BLOCKING_CHECKS)
    for c in checks:
        if c["name"] == "settings_schema":
            c["ok"] = False
    assert not all(c["ok"] for c in checks if c["name"] in run.BLOCKING_CHECKS)


def test_schema_nao_segue_o_repo_root_do_operador(tmp_path: Path, monkeypatch) -> None:
    """`REPO_ROOT` aponta para onde o settings do **operador** é procurado, e o
    teste a redireciona para um diretório falso. O schema viaja com o código.

    Amarrado ao `REPO_ROOT`, o schema passava na suíte só por acidente de ordem
    de import -- e sumia assim que alguém importasse o módulo depois do patch,
    derrubando o `setup_check` inteiro com traceback.
    """
    import importlib

    import workspace.config as config
    from workspace import settings_schema

    # O `reload` é o que torna este teste falsificável. `SCHEMA_PATH` é
    # constante de módulo, avaliada no import: patchear `REPO_ROOT` depois
    # nunca a altera, então a primeira versão deste teste passava tanto com o
    # caminho certo quanto com o errado -- confirmado por mutação.
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    try:
        recarregado = importlib.reload(settings_schema)
        assert recarregado.SCHEMA_PATH.exists(), (
            f"o schema sumiu quando REPO_ROOT virou {tmp_path}: ele é versionado "
            "com o código, não procurado junto do settings do operador"
        )
        assert tmp_path not in recarregado.SCHEMA_PATH.parents
    finally:
        monkeypatch.undo()
        importlib.reload(settings_schema)


def test_setup_check_sobrevive_a_schema_ausente(tmp_path: Path, monkeypatch) -> None:
    """Mesma lição do `venues_error`: o diagnóstico é rodado justamente quando
    algo está errado, então ele não pode virar traceback."""
    from workspace import run, settings_schema

    monkeypatch.setattr(settings_schema, "SCHEMA_PATH", tmp_path / "nao-existe.json")
    settings_schema._schema.cache_clear()
    try:
        report = run.setup_check()
    finally:
        settings_schema._schema.cache_clear()
    assert report["settings_error"] is None
