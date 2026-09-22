#!/usr/bin/env python3
"""OpenClaw entrypoint for trade-automatizado-openclaw.

The wrapper owns runtime concerns around the original strategy engine:
bootstrap, env loading, state/log paths, structured diagnostics, and
live-trade confirmation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent
REPO_DIR = WORKSPACE_DIR.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from workspace.venues import venue_summary  # noqa: E402
from workspace.venues.sandbox import resolve_sandbox, sandbox_settings_keys  # noqa: E402
from workspace.venues.config import selected_venues  # noqa: E402
from workspace.config import ConfigError  # noqa: E402
_logger = logging.getLogger(__name__)
REQUIREMENTS = WORKSPACE_DIR / "requirements.txt"
SKILL_ID = "trade-automatizado-openclaw"
LEGACY_SKILL_ID = "delta-neutral-airdrop-farmer"
STATE_DIR = Path(
    os.environ.get(
        "DELTA_NEUTRAL_STATE_DIR",
        Path.home() / ".openclaw" / "state" / SKILL_ID,
    )
).expanduser()
LOG_DIR = Path(
    os.environ.get(
        "DELTA_NEUTRAL_LOG_DIR",
        STATE_DIR / "logs",
    )
).expanduser()
VENV_DIR = Path(
    os.environ.get(
        "DELTA_NEUTRAL_VENV_DIR",
        STATE_DIR / ".venv",
    )
).expanduser()
DEFAULT_ENV_FILE = Path.home() / ".config" / "openclaw" / f"{SKILL_ID}.env"
LEGACY_ENV_FILE = Path.home() / ".config" / "openclaw" / f"{LEGACY_SKILL_ID}.env"
USER_CONFIG_FILE = Path(
    os.environ.get(
        "DELTA_NEUTRAL_USER_CONFIG_FILE",
        Path.home() / ".openclaw" / "workspace" / f"{SKILL_ID}.config.env",
    )
).expanduser()
STATE_CONFIG_FILE = Path(
    os.environ.get(
        "DELTA_NEUTRAL_STATE_CONFIG_FILE",
        STATE_DIR / "config.env",
    )
).expanduser()
ENV_FILE = Path(
    os.environ.get(
        "DELTA_NEUTRAL_ENV_FILE",
        DEFAULT_ENV_FILE,
    )
).expanduser()

# Teto para a sonda de dependencias; sem ele um interpretador travado pendura o diagnostico.
DEPENDENCY_PROBE_TIMEOUT = 60
REQUIRED_MODULES = {
    "ccxt": "ccxt",
    "dotenv": "python-dotenv",
    "pandas": "pandas",
    "numpy": "numpy",
}
# Dependencias por venue. So a Nado tem SDK proprio (e exige toolchain nativo);
# Kraken, Hyperliquid e as demais CEXs rodam pelo ccxt, que ja esta acima.
# Ausencia aqui e reportada, mas nao reprova o diagnostico nem dispara bootstrap.
OPTIONAL_MODULES = {
    "nado_protocol": "nado-protocol",
}
PROBED_MODULES = {**REQUIRED_MODULES, **OPTIONAL_MODULES}


def _dependencies_ready(status: dict[str, bool]) -> bool:
    """So as dependencias obrigatorias decidem se o ambiente esta pronto."""
    return all(status.get(name, False) for name in REQUIRED_MODULES)
SECRET_ENV = [
    "NADO_OWNER_PRIVATE_KEY",
    "NADO_PRIVATE_KEY",
    "PRIVATE_KEY",
    "NADO_LINKED_SIGNER_PRIVATE_KEY",
    "KRAKEN_API_KEY",
    "KRAKEN_API_KEY_",
    "KRAKEN_API_SECRET",
    "CEX_API_KEY",
    "CEX_API_SECRET",
    "CEX_API_PASSWORD",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BYBIT_API_KEY",
    "BYBIT_API_SECRET",
    "OKX_API_KEY",
    "OKX_API_SECRET",
    "OKX_API_PASSWORD",
    "KUCOIN_API_KEY",
    "KUCOIN_API_SECRET",
    "KUCOIN_API_PASSWORD",
    "MEXC_API_KEY",
    "MEXC_API_SECRET",
    "BITGET_API_KEY",
    "BITGET_API_SECRET",
    "BITGET_API_PASSWORD",
    "GATEIO_API_KEY",
    "GATEIO_API_SECRET",
    "HYPERLIQUID_WALLET_ADDRESS",
    "HYPERLIQUID_ACCOUNT_ADDRESS",
    "HYPERLIQUID_PRIVATE_KEY",
    "HYPERLIQUID_API_PRIVATE_KEY",
    "HYPERLIQUID_AGENT_PRIVATE_KEY",
    "HYPERLIQUID_VAULT_ADDRESS",
]
NON_SECRET_CONFIG_ENV = {
    "NETWORK",
    "NADO_NETWORK",
    "NADO_SUBACCOUNT_NAME",
    "NADO_REQUIRE_LINKED_SIGNER",
    "KRAKEN_VENUE",
    "KRAKEN_SANDBOX",
    "DEX_ID",
    "TRADE_DEX_ID",
    "DEX_ADAPTER",
    "DEX_ADAPTER_MODULE",
    "DEX_CONFIG_JSON",
    "DEX_NETWORK",
    "DEX_SANDBOX",
    "DEX_MARKET_TYPE",
    "DEX_OPTIONS_JSON",
    "HYPERLIQUID_NETWORK",
    "HYPERLIQUID_SANDBOX",
    "HYPERLIQUID_MARKET_TYPE",
    "HYPERLIQUID_SYMBOL_QUOTE",
    "HYPERLIQUID_OPTIONS_JSON",
    "CEX_ID",
    "TRADE_CEX_ID",
    "CEX_MARKET_TYPE",
    "CEX_DEFAULT_TYPE",
    "CEX_SANDBOX",
    "CEX_OPTIONS_JSON",
    "KRAKEN_ALLOW_MAIN_ACCOUNT",
    "EXECUTION_MODE",
    "DEFAULT_EXECUTION_MODE",
    "MARGIN_MODE",
    "DEFAULT_MARGIN_MODE",
    "NADO_MARGIN_MODE",
    "DEX_MARGIN_MODE",
    "KRAKEN_MARGIN_MODE",
    "CEX_MARGIN_MODE",
    "MARGIN_USD",
    "DEFAULT_MARGIN_USD",
    "NADO_MARGIN_USD",
    "DEX_MARGIN_USD",
    "KRAKEN_MARGIN_USD",
    "CEX_MARGIN_USD",
    "LEVERAGE",
    "NADO_LEVERAGE",
    "KRAKEN_LEVERAGE",
    "NADO_ALLOW_OWNER_FALLBACK",
    "NADO_MIN_ORDER_NOTIONAL_USD",
    "EXCHANGES",
    "CERTAINTY",
    "UNIQUE_TREND",
    "SETUP_NOTIFY_ENTRY_CHANNEL",
    "SETUP_LIVE_TARGET_STOP_MODE",
    "SETUP_NOTIFY_ENTRY_TARGET",
    "SETUP_NOTIFY_ENTRY_DISCORD_CHANNEL_ID",
}
TRADE_COMMANDS = {
    "open",
    "abrir",
    "open-venue-pair",
    "abrir-par-delta-neutro",
    "close-venue-pair",
    "fechar-par-delta-neutro",
    "rebalance",
    "unwind",
    "farm",
    "opportunistic",
    "setup-live",
    "rodar-setups-live",
    "live-hedge",
    "live-sync",
}
LIVE_CONFIRM_ENV = "TRADE_AUTOMATIZADO_CONFIRM_LIVE"
FRIENDLY_LIVE_CONFIRM_ENV = "AUTORIZAR_TRADE_REAL"
FRIENDLY_CONFIRM_ENV = "CONFIRMAR_TRADE_REAL"
LEGACY_LIVE_CONFIRM_ENV = "DELTA_NEUTRAL_CONFIRM_LIVE"
_LIVE_CONFIRM_TRUE_VALUES = {"1", "true", "yes", "sim"}
DASHBOARD_COMMANDS = {
    "dashboard",
    "dashboard-publisher",
}


VENV_MARKER = STATE_DIR / ".venv_path"


def _set_venv_dir(path: Path) -> None:
    global VENV_DIR
    VENV_DIR = path.expanduser()
    os.environ["DELTA_NEUTRAL_ACTIVE_VENV_DIR"] = str(VENV_DIR)


def _read_marked_venv_dir() -> Path | None:
    if os.environ.get("DELTA_NEUTRAL_VENV_DIR"):
        return None
    try:
        raw = VENV_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    path = Path(raw).expanduser()
    py = path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return path if py.exists() else None


def _venv_python_for(path: Path) -> Path:
    if os.name == "nt":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def _venv_python() -> Path:
    return _venv_python_for(VENV_DIR)


def _venv_fallback_dir() -> Path:
    return STATE_DIR / ".venv-auto"


def _dependency_status(python: Path | None = None) -> dict[str, bool]:
    """Sonda todos os modulos exigidos de uma vez.

    Uma sonda por modulo custava um startup de interpretador cada; no Windows
    isso fazia o `setup-check` levar ~24s. A pergunta e uma so, entao o
    subprocesso tambem e.
    """
    modules = list(PROBED_MODULES)
    if python is None:
        return {name: importlib.util.find_spec(name) is not None for name in modules}
    code = (
        "import importlib.util, json, sys; "
        "print(json.dumps({name: importlib.util.find_spec(name) is not None "
        "for name in json.loads(sys.argv[1])}))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", code, json.dumps(modules)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=DEPENDENCY_PROBE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        # O diagnostico precisa responder mesmo com o interpretador do venv
        # travado (disco de rede, antivirus). Reportar "ausente" e o que o
        # timeout existe para permitir -- levantar penduraria o `setup-check`.
        return {name: False for name in modules}
    if completed.returncode != 0:
        return {name: False for name in modules}
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return {name: False for name in modules}
    return {name: bool(payload.get(name)) for name in modules}


def _env_file_candidates() -> list[Path]:
    if os.environ.get("DELTA_NEUTRAL_ENV_FILE"):
        return [ENV_FILE]
    return [DEFAULT_ENV_FILE, LEGACY_ENV_FILE]


def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.split("#", 1)[0].strip().strip('"').strip("'")


# Envs que, lidas de um arquivo de config, **derrubam o `settings.json`**:
# elas entram na camada de ambiente, que vence arquivo por desenho. Ate esta
# fatia a documentacao mandava justamente salva-las aqui -- fechar o
# `.env.example` e o assistente de primeiro uso nao alcancava quem seguia o
# manual, que e a maioria.
#
# Elas continuam sendo carregadas. Tira-las da allowlist pareceria a correcao
# obvia e seria pior: quem tem `HYPERLIQUID_SANDBOX=true` salvo aqui cairia no
# default da venue, que e `False`, e passaria a operar na mainnet so por
# atualizar. A precedencia fica; o silencio e que sai.
#
# O par e `(tipo, venue)`; a chave de settings sai do **proprio resolvedor**,
# para nao manter uma segunda tabela que diverge da primeira.
CONFIG_ENV_QUE_VENCE_SETTINGS = {
    "CEX_SANDBOX": ("cex", ""),
    "KRAKEN_SANDBOX": ("cex", "kraken"),
    "DEX_SANDBOX": ("dex", ""),
    "DEX_NETWORK": ("dex", ""),
    "HYPERLIQUID_SANDBOX": ("dex", "hyperliquid"),
    "HYPERLIQUID_NETWORK": ("dex", "hyperliquid"),
}


def _avisa_env_que_vence_settings(key: str, source: Path) -> None:
    """Diz que chave de settings acabou de ser encoberta, e por qual arquivo.

    `NADO_NETWORK` e `NETWORK` ficam de fora de proposito: o adapter da Nado e
    construido so a partir delas e nunca chama o resolvedor, entao elas nao
    encobrem settings nenhum. Um aviso que sai sempre e um aviso ignorado.
    """
    kind, venue = CONFIG_ENV_QUE_VENCE_SETTINGS[key]
    chave = sandbox_settings_keys(kind, venue)[0]
    _logger.warning(
        "config: %s veio de %s e entra na camada de ambiente, que vence arquivo. "
        "Enquanto ela existir, %s no seu settings.json nao tem efeito. "
        "Para configurar por arquivo, remova a linha e declare a chave no settings.",
        key, source, chave,
    )


def _load_key_value_file(source: Path, *, allowed_keys: set[str] | None = None) -> bool:
    loaded = False
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_env_value(value)
        if not key:
            continue
        if allowed_keys is not None and key not in allowed_keys:
            continue
        if key in SECRET_ENV and allowed_keys is not None:
            continue
        if key not in os.environ:
            os.environ[key] = value
            loaded = True
            # So na injecao: quando a variavel ja esta no ambiente, o arquivo
            # nao decidiu nada e avisar sobre ele apontaria para o lugar errado.
            if key in CONFIG_ENV_QUE_VENCE_SETTINGS:
                _avisa_env_que_vence_settings(key, source)
    return loaded


def _load_user_config_files() -> list[Path]:
    active: list[Path] = []
    for source in [USER_CONFIG_FILE, STATE_CONFIG_FILE]:
        if source.exists():
            _load_key_value_file(source, allowed_keys=NON_SECRET_CONFIG_ENV)
            active.append(source)
    return active


def _load_env_file() -> Path | None:
    _load_user_config_files()
    # In OpenClaw, secrets should come from runtime environment/service keys,
    # not from a local dotfile path. Keep dotfile loading only for an explicit
    # DELTA_NEUTRAL_ENV_FILE override or for non-OpenClaw/local executions.
    if (
        not os.environ.get("DELTA_NEUTRAL_ENV_FILE")
        and (os.environ.get("QC_SECRETS_PROXY") or os.environ.get("QC_SERVICE_KEY_NAMES"))
    ):
        return None
    source = next((candidate for candidate in _env_file_candidates() if candidate.exists()), None)
    if source is None:
        return None
    _load_key_value_file(source)
    return source


def _safe_mkdirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    marked = _read_marked_venv_dir()
    if marked is not None:
        _set_venv_dir(marked)


def _format_bootstrap_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return stderr.strip() or str(exc)
    return str(exc)


def _bootstrap_at(path: Path, *, force: bool) -> dict[str, object]:
    py = _venv_python_for(path)
    created = False
    installed = False
    if force or not py.exists():
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        created = True

    before = _dependency_status(py) if py.exists() else {}
    if force or not _dependencies_ready(before):
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools<81", "wheel"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        installed = True

    after = _dependency_status(py)
    return {
        "status": "ok" if _dependencies_ready(after) else "incomplete",
        "venv": str(path),
        "python": str(py),
        "created": created,
        "installed": installed,
        "dependencies": after,
    }


def bootstrap(force: bool = False) -> dict[str, object]:
    """Create/update the local virtualenv when dependencies are missing.

    If the default venv is present but not writable (common after image/user
    changes), automatically fall back to a fresh state-local venv and persist it.
    """
    started = time.time()
    attempts: list[dict[str, object]] = []
    candidates = [VENV_DIR]
    explicit_venv = bool(os.environ.get("DELTA_NEUTRAL_VENV_DIR"))
    fallback = _venv_fallback_dir()
    if not explicit_venv and fallback != VENV_DIR:
        candidates.append(fallback)

    for index, candidate in enumerate(candidates):
        try:
            result = _bootstrap_at(candidate, force=force if index == 0 else True)
            _set_venv_dir(candidate)
            if candidate == fallback and not explicit_venv:
                VENV_MARKER.write_text(str(candidate), encoding="utf-8")
                result["fallback_from"] = str(candidates[0])
                result["fallback_reason"] = attempts[-1]["error"] if attempts else "default_venv_unavailable"
            result["attempts"] = attempts
            result["elapsed_seconds"] = round(time.time() - started, 2)
            return result
        except (OSError, subprocess.CalledProcessError) as exc:
            py = _venv_python_for(candidate)
            attempts.append(
                {
                    "venv": str(candidate),
                    "python": str(py),
                    "error": _format_bootstrap_error(exc),
                    "dependencies": _dependency_status(py) if py.exists() else {name: False for name in PROBED_MODULES},
                }
            )
            if explicit_venv:
                break

    py = _venv_python()
    return {
        "status": "blocked",
        "reason": "python_bootstrap_unavailable",
        "message": "Não foi possível criar/instalar dependências Python. A skill tentou o venv padrão e, quando permitido, um venv alternativo em state/.venv-auto. Se persistir, configure DELTA_NEUTRAL_VENV_DIR para um diretório gravável com pip.",
        "venv": str(VENV_DIR),
        "python": str(py),
        "attempts": attempts,
        "dependencies": _dependency_status(py) if py.exists() else {name: False for name in PROBED_MODULES},
        "elapsed_seconds": round(time.time() - started, 2),
    }


def _live_trade_confirmed() -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in _LIVE_CONFIRM_TRUE_VALUES
        for name in (FRIENDLY_LIVE_CONFIRM_ENV, FRIENDLY_CONFIRM_ENV, LIVE_CONFIRM_ENV, LEGACY_LIVE_CONFIRM_ENV)
    )


def _bootstrap_allowed() -> bool:
    return os.environ.get("DELTA_NEUTRAL_NO_BOOTSTRAP", "").lower() not in {"1", "true", "yes", "sim"}


def _ensure_venv_ready() -> dict[str, object]:
    """Best-effort first-run bootstrap for install/new-agent diagnostics.

    New OpenClaw agents often run `setup-check` before any real command. The
    global Python is intentionally clean, so `dependencies_current_python=false`
    is expected. What matters is the skill-owned venv under state/.venv.
    """
    py = _venv_python()
    deps = _dependency_status(py) if py.exists() else {name: False for name in PROBED_MODULES}
    if py.exists() and _dependencies_ready(deps):
        return {"attempted": False, "status": "ready", "dependencies": deps}
    if not _bootstrap_allowed():
        return {"attempted": False, "status": "skipped", "reason": "DELTA_NEUTRAL_NO_BOOTSTRAP", "dependencies": deps}
    boot = bootstrap()
    deps = _dependency_status(py) if py.exists() else {name: False for name in PROBED_MODULES}
    return {"attempted": True, "status": boot.get("status", "unknown"), "result": boot, "dependencies": deps}


def _sandbox_do_relatorio(kind: str, venue_id: str) -> str | None:
    """Sandbox para o relatorio: `"true"`, `"false"` ou `None` se ilegivel.

    Config invalida ja aparece em `venues_error` e no check `venues_config`;
    repetir a excecao aqui trocaria o relatorio inteiro por um traceback. Mas
    tambem nao se chuta um lado: `None` diz "nao sei", e `"false"` diria
    "dinheiro real" sobre uma config que ninguem conseguiu ler.
    """
    try:
        return "true" if resolve_sandbox(kind, venue_id) else "false"
    except ConfigError:
        return None


def setup_check() -> dict[str, object]:
    env_loaded = _load_env_file()
    _safe_mkdirs()
    venv_bootstrap = _ensure_venv_ready()
    current_deps = _dependency_status()
    venv_py = _venv_python()
    venv_deps = _dependency_status(venv_py) if venv_py.exists() else {name: False for name in PROBED_MODULES}
    # `setup-check` e o comando de diagnostico: config invalida precisa
    # aparecer como achado no relatorio, nao como traceback. Quem opera roda
    # isto justamente quando algo esta errado.
    try:
        venues = venue_summary()
        venues_error = None
    except ConfigError as exc:
        venues = {}
        venues_error = str(exc)
    selecao = selected_venues()
    return {
        "status": "ok" if _dependencies_ready(venv_deps) else "needs_bootstrap",
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "repo_dir": str(REPO_DIR),
            "workspace_dir": str(WORKSPACE_DIR),
        },
        "paths": {
            "venv_dir": str(VENV_DIR),
            "venv_marker": str(VENV_MARKER),
            "fallback_venv_dir": str(_venv_fallback_dir()),
            "state_dir": str(STATE_DIR),
            "log_dir": str(LOG_DIR),
            "user_config_file": str(USER_CONFIG_FILE),
            "state_config_file": str(STATE_CONFIG_FILE),
            "user_config_files_loaded": [str(path) for path in _load_user_config_files()],
            "env_file": str(ENV_FILE),
            "env_file_loaded": bool(env_loaded),
            "active_env_file": str(env_loaded) if env_loaded else None,
            "fallback_env_file": str(LEGACY_ENV_FILE),
        },
        "dependencies_current_python": current_deps,
        "dependencies_venv": venv_deps,
        "dependencies_ready": _dependencies_ready(venv_deps),
        "venv_ready": _dependencies_ready(venv_deps),
        "bootstrap": venv_bootstrap,
        "install_note": "Use dependencies_venv/venv_ready como fonte de verdade; dependencies_current_python pode ser false porque a skill roda pelo venv isolado.",
        "secrets_configured": {name: bool(os.environ.get(name)) for name in SECRET_ENV},
        "venues": venues,
        "venues_error": venues_error,
        "safe_defaults": {
            # Pela mesma funcao do caminho de ordem: reler o env aqui perdia o
            # alias `PRIMARY_CEX`, e o relatorio descrevia uma venue diferente
            # da que opera.
            "dex_id": selecao.dex_id,
            "cex_id": selecao.cex_id,
            "dex_network": _clean_env_value(os.environ.get("DEX_NETWORK") or os.environ.get("NADO_NETWORK") or os.environ.get("NETWORK") or "testnet"),
            # Do resolvedor unico, para a CEX selecionada. `None` quando a
            # config esta invalida: chutar `"false"` seria um palpite na
            # direcao do dinheiro.
            "cex_sandbox": _sandbox_do_relatorio("cex", selecao.cex_id),
            "nado_network": _clean_env_value(os.environ.get("NADO_NETWORK") or os.environ.get("NETWORK") or "testnet"),
            "cex_market_type": _clean_env_value(os.environ.get("CEX_MARKET_TYPE") or os.environ.get("CEX_DEFAULT_TYPE") or ""),
            "require_linked_signer": _clean_env_value(os.environ.get("NADO_REQUIRE_LINKED_SIGNER") or "true"),
            "require_kraken_subaccount": "false",
            "execution_mode": _clean_env_value(
                os.environ.get("EXECUTION_MODE") or os.environ.get("DEFAULT_EXECUTION_MODE") or "hedged"
            ),
            "margin_mode": _clean_env_value(os.environ.get("MARGIN_MODE") or os.environ.get("DEFAULT_MARGIN_MODE") or "cross"),
            "nado_margin_mode": _clean_env_value(os.environ.get("NADO_MARGIN_MODE") or os.environ.get("DEX_MARGIN_MODE") or ""),
            "kraken_margin_mode": _clean_env_value(os.environ.get("KRAKEN_MARGIN_MODE") or os.environ.get("CEX_MARGIN_MODE") or ""),
            "margin_usd": _clean_env_value(os.environ.get("MARGIN_USD") or os.environ.get("DEFAULT_MARGIN_USD") or ""),
            "nado_margin_usd": _clean_env_value(os.environ.get("NADO_MARGIN_USD") or os.environ.get("DEX_MARGIN_USD") or ""),
            "kraken_margin_usd": _clean_env_value(os.environ.get("KRAKEN_MARGIN_USD") or os.environ.get("CEX_MARGIN_USD") or ""),
            "privileged_fallback_confirmed": _clean_env_value(
                os.environ.get("DELTA_NEUTRAL_CONFIRM_PRIVILEGED_FALLBACK") or "false"
            ),
            "nado_allow_owner_fallback": _clean_env_value(os.environ.get("NADO_ALLOW_OWNER_FALLBACK") or "auto_if_linked_signer_missing"),
            "kraken_allow_main_account": _clean_env_value(os.environ.get("KRAKEN_ALLOW_MAIN_ACCOUNT") or "false"),
            "volume_order": _clean_env_value(os.environ.get("VOLUME_ORDER") or "workflow_required_for_live"),
            "nado_min_order_notional_usd": _clean_env_value(os.environ.get("NADO_MIN_ORDER_NOTIONAL_USD") or "10"),
        },
    }


# Checks que decidem o veredito do `doctor`. Credencial de venue fica de fora
# de proposito: ela falta em quem ainda esta configurando, e nao impede o
# diagnostico de rodar.
BLOCKING_CHECKS = frozenset(
    {"requirements_file", "state_dir_writable", "log_dir_writable", "venv_ready", "venues_config"}
)


def doctor() -> dict[str, object]:
    report = setup_check()
    report["checks"] = []

    def add(name: str, ok: bool, detail: str) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    def configured(names: object) -> bool:
        if not isinstance(names, list):
            return False
        return any(bool(os.environ.get(str(name))) for name in names)

    add("requirements_file", REQUIREMENTS.exists(), str(REQUIREMENTS))
    add("state_dir_writable", _writable_dir(STATE_DIR), str(STATE_DIR))
    add("log_dir_writable", _writable_dir(LOG_DIR), str(LOG_DIR))
    add("venv_ready", all(report["dependencies_venv"].values()), "rode `python workspace/run.py bootstrap` se falso")
    # Config de venue invalida derruba `venues`, `rodar-setups` e o
    # `build_engine`. Sem este check ela so aparecia como um campo solto do
    # relatorio, e o `doctor` -- que existe para dizer se da para operar --
    # podia nao acusar nada.
    venues_error = report.get("venues_error")
    add("venues_config", venues_error is None, str(venues_error) if venues_error else "ok")
    venues = report.get("venues", {}) if isinstance(report.get("venues"), dict) else {}
    dex_id = str(venues.get("dex_id") or "nado")
    cex_id = str(venues.get("cex_id") or "kraken")
    dex_env = venues.get("dex_required_env", {}) if isinstance(venues.get("dex_required_env"), dict) else {}
    add(
        "cex_credentials",
        bool(venues.get("cex_credentials_configured")),
        f"credenciais da CEX {cex_id}: CEX_API_KEY/CEX_API_SECRET ou envs especificas do venue selecionado",
    )
    if dex_id in {"nado", "nado-dex", "nado_dex"}:
        add(
            "nado_credentials",
            configured(dex_env.get("owner_private_key")),
            "NADO_OWNER_PRIVATE_KEY, NADO_PRIVATE_KEY ou alias legado PRIVATE_KEY",
        )
        add(
            "linked_signer_or_owner",
            configured(dex_env.get("linked_signer_private_key")) or configured(dex_env.get("owner_private_key")),
            "linked signer recomendado; se ausente, trades Nado usam owner da wallet/conta configurada",
        )
    elif dex_id in {"hyperliquid", "hyperliquid-dex", "hyperliquid_dex"}:
        add(
            "hyperliquid_credentials",
            configured(dex_env.get("wallet_address")) and configured(dex_env.get("private_key")),
            "HYPERLIQUID_WALLET_ADDRESS + HYPERLIQUID_PRIVATE_KEY/AGENT_PRIVATE_KEY",
        )
        add(
            "hyperliquid_vault_optional",
            True,
            "HYPERLIQUID_VAULT_ADDRESS/vault nao e obrigatorio; e recomendado quando o venue oferecer isolamento",
        )
    else:
        add(
            "dex_adapter",
            bool(venues.get("dex_adapter_configured")),
            f"DEX {dex_id} custom exige DEX_ADAPTER_MODULE=pacote.modulo:Classe",
        )
    # Por nome, nao por posicao: o corte `[:4]` era um indice, entao inserir um
    # check acima silenciosamente derrubava outro do criterio -- foi o que
    # aconteceu com `venues_config`, que ficou fora e deixava o `doctor`
    # devolver `ok` com config que derruba todo comando de trade.
    report["status"] = (
        "ok"
        if all(item["ok"] for item in report["checks"] if item["name"] in BLOCKING_CHECKS)
        else "attention"
    )
    return report


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _extract_runtime_env_arg(argv: list[str]) -> tuple[str | None, list[str]]:
    runtime_env: str | None = None
    cleaned: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--runtime-env":
            if i + 1 >= len(argv):
                raise ValueError("--runtime-env exige o caminho do arquivo .env")
            runtime_env = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--runtime-env="):
            runtime_env = arg.split("=", 1)[1]
            if not runtime_env:
                raise ValueError("--runtime-env exige o caminho do arquivo .env")
            i += 1
            continue
        cleaned.append(arg)
        i += 1
    return runtime_env, cleaned


def _has_explicit_sizing(args: list[str]) -> bool:
    sizing_flags = {
        "--notional",
        "--valor-nominal",
        "--margin-usd",
        "--margem-usd",
        "--nado-margin-usd",
        "--margem-nado-usd",
        "--dex-margin-usd",
        "--margem-dex-usd",
        "--kraken-margin-usd",
        "--margem-kraken-usd",
        "--cex-margin-usd",
        "--margem-cex-usd",
        "--account-margin-slots",
        "--slots-margem-conta",
    }
    for arg in args:
        if arg in sizing_flags:
            return True
        if any(arg.startswith(flag + "=") for flag in sizing_flags):
            return True
    return False


def _run_cli(args: list[str]) -> int:
    _load_env_file()
    _safe_mkdirs()
    os.environ.setdefault("DELTA_NEUTRAL_STATE_DIR", str(STATE_DIR))
    os.environ.setdefault("DELTA_NEUTRAL_LOG_DIR", str(LOG_DIR))
    os.environ.setdefault("NADO_MIN_ORDER_NOTIONAL_USD", "10")

    inspection_only = any(arg in {"-h", "--help", "--dry-run", "--simular"} for arg in args)
    if args and args[0] in {"setup-live", "rodar-setups-live", "open", "abrir", "open-venue-pair", "abrir-par-delta-neutro"} and not inspection_only and not _has_explicit_sizing(args):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "live_sizing_requires_workflow_input",
                    "message": "Informe o tamanho antes da execucao real: use --margem-usd ou --valor-nominal. Para tamanhos separados, use --margem-dex-usd/--margem-cex-usd. Aliases tecnicos tambem aceitos: --margin-usd, --notional, --dex-margin-usd, --cex-margin-usd, --nado-margin-usd, --kraken-margin-usd ou --account-margin-slots.",
                    "command": args[0],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if (
        args
        and args[0] in TRADE_COMMANDS
        and not inspection_only
        and not _live_trade_confirmed()
    ):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "live_trade_requires_explicit_confirmation",
                    "message": f"Para executar ordem real, defina {FRIENDLY_LIVE_CONFIRM_ENV}=sim nesta execucao aprovada. Tambem aceito: {LIVE_CONFIRM_ENV}=true; alias legado: {LEGACY_LIVE_CONFIRM_ENV}=true.",
                    "command": args[0],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    no_bootstrap = not _bootstrap_allowed()
    py = _venv_python()
    if not no_bootstrap:
        deps = _dependency_status(py) if py.exists() else {}
        if not py.exists() or not _dependencies_ready(deps):
            boot = bootstrap()
            if boot.get("status") == "blocked":
                print(json.dumps(boot, ensure_ascii=False, indent=2))
                return 3

    py = _venv_python() if _venv_python().exists() else Path(sys.executable)
    cmd = [str(py), str(WORKSPACE_DIR / "cli.py"), *args]
    return subprocess.call(cmd, cwd=str(REPO_DIR), env=os.environ.copy())


def _run_dashboard(command: str, args: list[str]) -> int:
    _load_env_file()
    _safe_mkdirs()
    os.environ.setdefault("DELTA_NEUTRAL_STATE_DIR", str(STATE_DIR))
    os.environ.setdefault("DELTA_NEUTRAL_LOG_DIR", str(LOG_DIR))
    os.environ.setdefault("NADO_MIN_ORDER_NOTIONAL_USD", "10")

    no_bootstrap = not _bootstrap_allowed()
    py = _venv_python()
    if not no_bootstrap:
        deps = _dependency_status(py) if py.exists() else {}
        if not py.exists() or not _dependencies_ready(deps):
            boot = bootstrap()
            if boot.get("status") == "blocked":
                print(json.dumps(boot, ensure_ascii=False, indent=2))
                return 3

    py = _venv_python() if _venv_python().exists() else Path(sys.executable)
    if command == "dashboard":
        cmd = [str(py), str(WORKSPACE_DIR / "dashboard_publisher.py"), "--once", "--no-deploy", *args]
    else:
        cmd = [str(py), str(WORKSPACE_DIR / "dashboard_publisher.py"), *args]
    return subprocess.call(cmd, cwd=str(REPO_DIR), env=os.environ.copy())


def main(argv: list[str] | None = None) -> int:
    global ENV_FILE
    argv = list(sys.argv[1:] if argv is None else argv)
    runtime_env: str | None = None
    runtime_env_error: str | None = None
    try:
        runtime_env, argv = _extract_runtime_env_arg(argv)
    except ValueError as exc:
        runtime_env_error = str(exc)

    parser = argparse.ArgumentParser(
        prog="delta-neutral-run",
        description="Entrypoint OpenClaw para Trade Automatizado OpenClaw.",
    )
    parser.add_argument(
        "--runtime-env",
        default=runtime_env,
        help="arquivo .env efemero para esta execucao; equivalente a DELTA_NEUTRAL_ENV_FILE",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="setup-check, doctor, bootstrap, dashboard, dashboard-publisher ou comando original do cli.py",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    if runtime_env_error:
        parser.error(runtime_env_error)
    ns = parser.parse_args(argv)
    if ns.runtime_env:
        os.environ["DELTA_NEUTRAL_ENV_FILE"] = ns.runtime_env
        ENV_FILE = Path(ns.runtime_env).expanduser()

    if not ns.command:
        parser.print_help()
        return 0
    if ns.command in {"wizard", "first-run", "onboarding"}:
        setup_script = WORKSPACE_DIR / "first_run_setup.py"
        return subprocess.call([sys.executable, str(setup_script), "--json"], cwd=str(REPO_DIR))
    if ns.command == "setup-check":
        _print_json(setup_check())
        return 0
    if ns.command == "doctor":
        _print_json(doctor())
        return 0
    if ns.command == "bootstrap":
        _print_json(bootstrap(force="--force" in ns.args))
        return 0
    if ns.command in DASHBOARD_COMMANDS:
        return _run_dashboard(ns.command, ns.args)
    return _run_cli([ns.command, *ns.args])


if __name__ == "__main__":
    raise SystemExit(main())
