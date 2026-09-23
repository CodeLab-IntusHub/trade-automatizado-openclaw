"""`config-export`: o `settings.json` equivalente ao ambiente atual.

A migração de env para arquivo é incremental por desenho, e isso cria um
degrau ruim para quem já opera: o operador tem dezenas de variáveis no `.env`,
a documentação nova fala em `settings.json`, e não há caminho entre os dois que
não seja transcrever à mão -- lendo o código para descobrir qual chave
corresponde a qual variável.

O que este comando **não** pode fazer é parecer completo. Só parte das
variáveis tem equivalente em settings hoje; um arquivo que aparentasse
substituir o `.env` levaria o operador a apagar o `.env` e perder credencial.
Daí os dois avisos obrigatórios: o que não foi exportado, e o fato de que as
variáveis exportadas **continuam vencendo** o arquivo enquanto existirem no
ambiente.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.config import load_settings  # noqa: E402
from workspace.settings_schema import validar_settings  # noqa: E402


def _export(monkeypatch, tmp_path: Path, env: dict[str, str]):
    """Roda o export num ambiente controlado e devolve `(settings, relatorio)`."""
    from workspace import config_export

    for nome, valor in env.items():
        monkeypatch.setenv(nome, valor)
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))
    return config_export.exportar(settings=load_settings(root=tmp_path))


def test_saida_passa_pelo_proprio_schema(monkeypatch, tmp_path: Path) -> None:
    """Fecha o ciclo com a fatia anterior: um export que o próprio validador
    recusa é pior que nenhum export -- ele derruba o boot de quem o usou."""
    exportado, _ = _export(monkeypatch, tmp_path, {"CEX_ID": "kraken"})
    assert validar_settings(exportado, origem="exportado") == []


def test_nao_emite_segredo(monkeypatch, tmp_path: Path) -> None:
    """A regra que vale desde o começo da fase: segredo nunca entra no settings.

    Nem o valor, nem a chave. Aqui vale duplamente, porque a saída é feita para
    ser redirecionada para um arquivo que o operador pode commitar.
    """
    from workspace.run import SECRET_ENV

    segredos = {nome: f"valor-secreto-de-{nome}" for nome in SECRET_ENV}
    exportado, relatorio = _export(monkeypatch, tmp_path, {**segredos, "CEX_ID": "kraken"})
    texto = json.dumps(exportado) + json.dumps(relatorio)
    for nome in SECRET_ENV:
        assert f"valor-secreto-de-{nome}" not in texto, f"vazou o valor de {nome}"


def test_exporta_o_valor_efetivo_e_nao_o_default(monkeypatch, tmp_path: Path) -> None:
    """Exportar o default seria emitir um arquivo que não descreve nada."""
    exportado, _ = _export(monkeypatch, tmp_path, {
        "CEX_ID": "kraken",
        "KRAKEN_SANDBOX": "false",
        "TRIANGLE_PIVOT_WINDOW": "7",
    })
    assert exportado["venues"]["cex"]["kraken"]["sandbox"] is False
    assert exportado["setups"]["triangle-breakout"]["pivot_window"] == 7


def test_round_trip_reproduz_os_mesmos_valores(monkeypatch, tmp_path: Path) -> None:
    """O teste que de fato prova o comando.

    Exporta com o ambiente cheio, grava o resultado, limpa as variáveis e
    confere que o arquivo sozinho produz os mesmos valores efetivos. Sem isto,
    o export poderia emitir chaves plausíveis que nenhum leitor consulta.
    """
    from workspace.core.setups import get_triangle_breakout_config
    from workspace.venues.sandbox import resolve_sandbox

    env = {"CEX_ID": "kraken", "KRAKEN_SANDBOX": "false", "TRIANGLE_PIVOT_WINDOW": "7"}
    exportado, _ = _export(monkeypatch, tmp_path, env)

    antes_sandbox = resolve_sandbox("cex", "kraken", settings=load_settings(root=tmp_path))
    antes_pivot = get_triangle_breakout_config(settings=load_settings(root=tmp_path)).pivot_window

    (tmp_path / "settings.json").write_text(json.dumps(exportado), encoding="utf-8")
    for nome in env:
        monkeypatch.delenv(nome, raising=False)

    depois = load_settings(root=tmp_path)
    assert resolve_sandbox("cex", "kraken", settings=depois) == antes_sandbox is False
    assert get_triangle_breakout_config(settings=depois).pivot_window == antes_pivot == 7


def test_relatorio_avisa_que_o_env_continua_vencendo(monkeypatch, tmp_path: Path) -> None:
    """Exportar não tem efeito nenhum enquanto a variável existir no ambiente.

    Um operador que exporta, mantém o `.env` e não vê mudança conclui que
    settings não funciona -- foi exatamente o que motivou o aviso de origem no
    boot dos setups.
    """
    _, relatorio = _export(monkeypatch, tmp_path, {"CEX_ID": "kraken", "KRAKEN_SANDBOX": "false"})
    assert "KRAKEN_SANDBOX" in relatorio["envs_que_vencem_o_arquivo"]
    assert any("vence" in a.lower() for a in relatorio["avisos"])


def test_aviso_de_que_o_arquivo_nao_substitui_o_env_sai_sempre() -> None:
    """O aviso que impede o dano maior: apagar o `.env` e perder credencial.

    A primeira versão deste teste só verificava que a lista de avisos não
    estava vazia. Uma mutação que **removia** este aviso sobreviveu, porque o
    aviso sobre precedência mantinha a lista cheia -- asserção que não podia
    falhar pelo motivo declarado. Este aviso é incondicional, então o teste
    também é.
    """
    from workspace.config_export import exportar

    _, relatorio = exportar(ambiente={})
    assert any("substitui" in a.lower() and ".env" in a.lower() for a in relatorio["avisos"]), (
        f"o aviso central sumiu: {relatorio['avisos']}"
    )


def test_relatorio_lista_o_que_nao_tem_equivalente(monkeypatch, tmp_path: Path) -> None:
    """Listar tudo não informa nada: o valor está na diferença.

    `KRAKEN_SANDBOX` precisa estar **definida** aqui. Na primeira versão ela não
    estava, e a asserção de exclusão passava por vacuidade -- confirmado por
    mutação: trocar o filtro por "lista todas as envs definidas" não quebrava
    teste nenhum.
    """
    _, relatorio = _export(monkeypatch, tmp_path, {
        "CEX_ID": "kraken",
        "KRAKEN_SANDBOX": "false",
        "VOLUME_ORDER": "50",
        "NADO_SUBACCOUNT_NAME": "default_1",
    })
    nao_exportaveis = relatorio["sem_equivalente_em_settings"]
    assert "VOLUME_ORDER" in nao_exportaveis
    assert "NADO_SUBACCOUNT_NAME" in nao_exportaveis
    assert "KRAKEN_SANDBOX" not in nao_exportaveis, (
        "variável COM equivalente listada como sem equivalente"
    )


def test_segredo_definido_aparece_so_como_nome(monkeypatch, tmp_path: Path) -> None:
    """O operador precisa saber que a credencial fica onde está -- sem que o
    relatório a imprima."""
    _, relatorio = _export(monkeypatch, tmp_path, {
        "CEX_ID": "kraken", "KRAKEN_API_SECRET": "s3cr3t-de-verdade",
    })
    assert "KRAKEN_API_SECRET" in relatorio["segredos_definidos"]
    assert "s3cr3t-de-verdade" not in json.dumps(relatorio)


def test_ambiente_limpo_exporta_os_defaults_sem_avisar_a_toa(monkeypatch, tmp_path: Path) -> None:
    """Sem variável nenhuma, não há env vencendo nada -- e um aviso que sai
    sempre é um aviso ignorado."""
    from workspace.run import SECRET_ENV
    import workspace.config_export as ce

    for nome in list(ce.envs_do_projeto()) + list(SECRET_ENV):
        monkeypatch.delenv(nome, raising=False)
    exportado, relatorio = _export(monkeypatch, tmp_path, {})
    assert validar_settings(exportado, origem="exportado") == []
    assert relatorio["envs_que_vencem_o_arquivo"] == []
    assert relatorio["segredos_definidos"] == []


def test_cli_manda_json_para_stdout_e_aviso_para_stderr(monkeypatch, tmp_path: Path, capsys) -> None:
    """`config-export > settings.json` tem que produzir um arquivo válido.

    Aviso misturado no stdout transformaria o redirecionamento num arquivo
    quebrado -- e o operador só descobriria no boot seguinte.
    """
    from workspace import run

    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))
    monkeypatch.setenv("KRAKEN_SANDBOX", "false")

    assert run.main(["config-export"]) == 0
    capturado = capsys.readouterr()
    payload = json.loads(capturado.out)
    assert validar_settings(payload, origem="stdout") == []
    assert "KRAKEN_SANDBOX" in capturado.err
    assert capturado.err.strip(), "o aviso não pode sumir"


def test_schema_aceita_tudo_que_o_export_emite(monkeypatch, tmp_path: Path) -> None:
    """Contra o drift na direção oposta à da fatia anterior.

    Lá o risco era o schema recusar chave que o código lê. Aqui é o export
    emitir chave que o schema recusa -- e o operador que usar a saída vê o boot
    cair por causa de uma ferramenta nossa.
    """
    exportado, _ = _export(monkeypatch, tmp_path, {
        "CEX_ID": "binance", "DEX_ID": "hyperliquid", "CEX_SANDBOX": "true",
    })
    assert validar_settings(exportado, origem="exportado") == []
    assert exportado["venues"]["cex"]["binance"]["sandbox"] is True


def test_lista_numerica_sai_numerica(monkeypatch, tmp_path: Path) -> None:
    """`get_list` devolve `[str(item)]` por contrato, então a escada de alvos
    saía como `["1.0", "1.5"]` onde o `settings.example.json` traz `[1.0, 1.5]`.

    O produto deste comando é um arquivo feito para ser lido e editado por uma
    pessoa; emitir um dialeto diferente do exemplo que documentamos convida a
    editar errado. A conversão é segura exatamente porque `get_list`
    re-stringifica na leitura -- o teste abaixo é o que garante isso.
    """
    exportado, _ = _export(monkeypatch, tmp_path, {})
    divergence = exportado["setups"]["divergence-and-volume-4h"]
    assert divergence["target_levels"] == [1.0, 1.5, 2.0, 2.5]
    assert divergence["fibonacci_levels"] == [1.0, 1.618, 2.0, 2.618]
    assert all(isinstance(x, float) for x in divergence["target_weights"])


def test_round_trip_do_divergence(monkeypatch, tmp_path: Path) -> None:
    """A escada de alvos é invariante do tipo (`__post_init__`), então ela é o
    caso em que um round-trip mal feito não passa despercebido.

    O primeiro round-trip que escrevi cobria só `pivot_window` e `sandbox` --
    escalares. Foi por isso que a lista numérica passou batida.
    """
    from workspace.core.setups import get_divergence_volume_config

    antes = get_divergence_volume_config(timeframe="4h", settings=load_settings(root=tmp_path))
    exportado, _ = _export(monkeypatch, tmp_path, {})
    (tmp_path / "settings.json").write_text(json.dumps(exportado), encoding="utf-8")
    depois = get_divergence_volume_config(timeframe="4h", settings=load_settings(root=tmp_path))
    assert antes == depois


def test_texto_que_parece_numero_nao_e_convertido_a_toa(monkeypatch, tmp_path: Path) -> None:
    """A conversão vale para a lista inteira ou para nenhuma: converter item a
    item produziria uma lista mista, que é pior que qualquer um dos dois."""
    from workspace.config_export import _normalizar

    assert _normalizar(("1.0", "2.5")) == [1.0, 2.5]
    assert _normalizar(("1.0", "BTC")) == ["1.0", "BTC"]
    assert _normalizar(("BTC", "ETH")) == ["BTC", "ETH"]
    assert _normalizar("texto") == "texto"


def test_primeira_leitura_de_uma_chave_e_a_que_vale() -> None:
    """O preenchimento é last-wins por natureza, e a mesma chave pode ser lida
    duas vezes: `setups.py` sonda presença chamando o getter com um sentinela
    próprio como `default`.

    Hoje o filtro de tipo descarta essa segunda leitura antes de ela chegar à
    montagem — medido: sem o filtro, o sentinela sobrescrevia o `7` lido do
    ambiente. Mas depender disso deixa a regra implícita num filtro que existe
    por outro motivo, então ela é testada aqui, direto, com entradas
    controladas.
    """
    from workspace.config_export import _montar

    entradas = [
        ("setups.triangle-breakout.pivot_window", ("TRIANGLE_PIVOT_WINDOW",), 7),
        ("setups.triangle-breakout.pivot_window", (), "sondagem"),
    ]
    assert _montar(entradas)["setups"]["triangle-breakout"]["pivot_window"] == 7


def test_montar_descarta_o_que_o_json_nao_representa() -> None:
    """A saída vira arquivo: valor não serializável ali quebraria o comando na
    hora de imprimir, e o operador ficaria sem export nenhum.

    Testado aqui, em `_montar`, e não no coletor: lá o defeito só apareceria se
    existisse uma chave **apenas** sondada — condição que hoje não ocorre, o
    que tornava a mutação que removia o filtro invisível.
    """
    from workspace.config_export import _montar

    assert _montar([("a.b", (), object())]) == {}
    assert _montar([("a.b", (), 1), ("a.c", (), object())]) == {"a": {"b": 1}}


def test_saida_e_sempre_serializavel(monkeypatch, tmp_path: Path) -> None:
    exportado, relatorio = _export(monkeypatch, tmp_path, {"CEX_ID": "kraken"})
    json.dumps(exportado)
    json.dumps(relatorio)
