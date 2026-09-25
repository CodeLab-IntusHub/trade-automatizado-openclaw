"""Isolamento que vale para a suite inteira.

Depois que `venue_summary()` passou a resolver `sandbox` pelo `workspace.config`,
qualquer teste que o chame -- direto ou por dentro do `setup_check`/`doctor`/
`build_engine` -- le `settings.json` e `settings.local.json`. Sem isolamento
global, a suite passa a depender dos arquivos da maquina de quem roda: com um
`settings.local.json` real declarando `venues.cex.sandbox`, cinco testes de
`test_smoke.py` e `test_v2.py` quebravam.

Ficava fora do lugar como fixture de dois modulos: o vazamento nao e dos
modulos que testam config, e sim de todo caminho que constroi venue.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _restaura_environ():
    """Devolve `os.environ` ao estado anterior depois de cada teste.

    `monkeypatch` so desfaz o que ele mesmo mudou. Codigo de producao chamado
    de dentro do teste tambem escreve no ambiente -- `_load_env_file()` repoe
    as chaves de `NON_SECRET_CONFIG_ENV` lidas dos arquivos do operador -- e
    isso vazava para os testes seguintes. Foi observado: um teste que exercita
    justamente essa reinjecao deixou `CEX_ID=binance` para tras e derrubou dois
    testes de `test_v2.py`.
    """
    antes = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(antes)


@pytest.fixture(autouse=True)
def isola_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutraliza os tres candidatos de `_local_settings_path`.

    A funcao devolve o **primeiro caminho que existe**, nesta ordem:
    `DELTA_NEUTRAL_SETTINGS_DIR`, `~/.config/openclaw/<skill>/` e a raiz do
    repo. Por isso apontar so o override para um `tmp_path` vazio nao basta --
    sem arquivo la, a busca cai no home e a suite volta a medir a maquina. O
    home tambem precisa ser falso, porque ha teste que remove o override de
    proposito para exercitar o fallback.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("DELTA_NEUTRAL_SETTINGS_DIR", str(tmp_path))
    # Arquivo vazio no override para que ele seja de fato o escolhido: sem
    # isso a busca segue ate a raiz do repo, e um `settings.local.json` la
    # (fora do git, mas presente na maquina de quem desenvolve) voltaria a
    # decidir o resultado dos testes.
    local = tmp_path / "settings.local.json"
    if not local.exists():
        local.write_text("{}", encoding="utf-8")

    # O versionado tambem: `load_settings()` sem `root` o le da raiz do repo, e
    # isolar so metade do par deixava a suite refem do dia em que um
    # `settings.json` de time fosse commitado.
    import workspace.config as config

    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)

    # `setup_check` chama `_load_env_file()`, que **reinjeta** em `os.environ`
    # as chaves de `NON_SECRET_CONFIG_ENV` (`CEX_SANDBOX`, `KRAKEN_SANDBOX`,
    # `CEX_ID`...) lidas dos arquivos do operador. Os caminhos sao constantes
    # de modulo, ligadas ao home **real** no import -- antes de o patch de HOME
    # existir. Sem redireciona-las, um `monkeypatch.delenv` no teste era
    # desfeito no meio da chamada, e o vazamento ainda sobrevivia para os
    # testes seguintes.
    import workspace.run as run

    vazio = tmp_path / "sem-env"
    # `ENV_FILE` entra junto: quando `DELTA_NEUTRAL_ENV_FILE` esta definida
    # (modo `--runtime-env`), `_env_file_candidates()` devolve so ela, e todo o
    # resto do redirecionamento nao vale nada.
    monkeypatch.delenv("DELTA_NEUTRAL_ENV_FILE", raising=False)
    for constante in ("ENV_FILE", "USER_CONFIG_FILE", "STATE_CONFIG_FILE", "DEFAULT_ENV_FILE", "LEGACY_ENV_FILE"):
        monkeypatch.setattr(run, constante, vazio / f"{constante.lower()}.env", raising=False)


@pytest.fixture(autouse=True)
def sem_rede_na_permissao_de_saque(monkeypatch: pytest.MonkeyPatch) -> None:
    """O `doctor` consulta a CEX para saber se a key pode sacar -- a unica
    chamada de rede dele, e so com credencial configurada. Varios testes rodam
    o `doctor` com credencial falsa; sem isto, cada um tentaria a venue de
    verdade. Os testes do check substituem esta consulta pela que precisam."""
    from workspace.venues import permissao_de_saque as ps

    def sem_rede(venue: str, credenciais: dict, *, sandbox: bool) -> ps.Veredicto:
        return ps.Veredicto(venue, ps.NAO_VERIFICAVEL, "rede desligada nos testes")

    monkeypatch.setattr(ps, "consultar", sem_rede)


@pytest.fixture(autouse=True)
def sem_openclaw_na_politica_de_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """O `doctor` roda `openclaw exec-policy show --json` para saber se o
    OpenClaw pede aprovacao. Na suite, isso mediria a maquina de quem roda:
    fica "nao verificado". Os testes do check substituem pela politica que
    precisam."""
    from workspace import politica_openclaw as po

    monkeypatch.setattr(po, "consultar", lambda: po.Veredicto(po.NAO_VERIFICAVEL, "openclaw fora dos testes"))
