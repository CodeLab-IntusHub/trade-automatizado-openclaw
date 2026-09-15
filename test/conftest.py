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

from pathlib import Path

import pytest


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
