#!/usr/bin/env python3
"""Rebuild the trade dashboard and optionally run an external deploy command."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace.file_lock import FileLock, LockHeld
from workspace.trade_dashboard import (
    DEFAULT_CCXT_LOG_PATH,
    DEFAULT_HTML_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_SETUP_STATE_PATH,
    DEFAULT_STATE_PATH,
    SKILL_ID,
    rebuild_dashboard_from_logs,
)


HOME = Path.home()
STATE_DIR = HOME / ".openclaw" / "state" / SKILL_ID
DEFAULT_PUBLIC_HTML_PATH = ROOT / "index.html"
DEFAULT_PUBLIC_DATA_PATH = ROOT / "dashboard-data.json"
DEFAULT_STAMP_PATH = STATE_DIR / "dashboard_publisher.json"
DEFAULT_LOCK_PATH = STATE_DIR / "dashboard_publisher.lock"
DEFAULT_LOG_DIR = HOME / ".openclaw" / "logs" / SKILL_ID
DEFAULT_GITHUB_LIVE_REPO = ""
DEFAULT_GITHUB_LIVE_PATH = "dashboard-data.json"
DEFAULT_GITHUB_LIVE_BRANCH = "main"


def _utc_now_label() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_bytes(source.read_bytes())
    tmp.replace(destination)


def _split_command(raw: str) -> list[str]:
    parts = shlex.split(raw)
    if not parts:
        raise ValueError("configure --deploy-command para publicar externamente")
    return parts


def _run_deploy(command: Sequence[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def _github_raw_url(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _run_gh_api(args: Sequence[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", "api", *args],
        cwd=str(ROOT),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def _publish_github_live_data(
    *,
    data_path: Path,
    repo: str,
    branch: str,
    remote_path: str,
    min_seconds: float,
    stamp: dict[str, object],
) -> dict[str, object]:
    if not repo:
        return {}
    now = time.time()
    last_publish = float(stamp.get("last_live_data_published_at_epoch") or 0.0)
    raw_url = _github_raw_url(repo, branch, remote_path)
    if last_publish and now - last_publish < min_seconds:
        return {
            "live_data_url": raw_url,
            "last_live_data_skip_reason": "janela_minima",
            "last_live_data_skip_at": _utc_now_label(),
        }

    sha = ""
    fetch = _run_gh_api([f"/repos/{repo}/contents/{remote_path}?ref={branch}"], timeout=60)
    if fetch.returncode == 0:
        try:
            payload = json.loads(fetch.stdout)
            sha = str(payload.get("sha") or "")
        except json.JSONDecodeError:
            sha = ""
    elif "Not Found" not in fetch.stdout:
        return {
            "live_data_url": raw_url,
            "last_live_data_error": fetch.stdout[-1200:],
            "last_live_data_error_at": _utc_now_label(),
        }

    content = base64.b64encode(data_path.read_bytes()).decode("ascii")
    update_payload: dict[str, object] = {
        "message": f"update live dashboard data {_utc_now_label()}",
        "content": content,
        "branch": branch,
    }
    if sha:
        update_payload["sha"] = sha
    payload_path = STATE_DIR / "github_live_data_payload.json"
    payload_path.write_text(json.dumps(update_payload), encoding="utf-8")
    update = _run_gh_api(
        ["-X", "PUT", f"/repos/{repo}/contents/{remote_path}", "--input", str(payload_path)],
        timeout=180,
    )
    try:
        payload_path.unlink()
    except FileNotFoundError:
        pass
    if update.returncode != 0:
        return {
            "live_data_url": raw_url,
            "last_live_data_error": update.stdout[-1200:],
            "last_live_data_error_at": _utc_now_label(),
        }
    return {
        "live_data_url": raw_url,
        "last_live_data_published_at": _utc_now_label(),
        "last_live_data_published_at_epoch": time.time(),
        "last_live_data_error": "",
        "last_live_data_skip_reason": "",
    }


def publish_once(args: argparse.Namespace) -> int:
    with FileLock(Path(args.lock_path)):
        recorder = rebuild_dashboard_from_logs(
            setup_log=args.setup_log,
            ccxt_log=args.ccxt_log,
            state_path=args.state,
            html_path=args.html,
            setup_state_path=args.setup_state,
            sync_live_exposure=not args.no_live_exposure,
        )
        local_html = Path(args.html).expanduser()
        local_data = local_html.with_name("dashboard-data.json")
        public_html = Path(args.public_html).expanduser()
        public_data = Path(args.public_data).expanduser()

        _copy_atomic(local_html, public_html)
        _copy_atomic(local_data, public_data)

        html_hash = _sha256(public_html)
        data_hash = _sha256(public_data)
        fingerprint = f"{html_hash}:{data_hash}"
        stamp_path = Path(args.stamp_path).expanduser()
        stamp = _read_json(stamp_path)
        last_fingerprint = str(stamp.get("fingerprint") or "")
        last_deployed_at = float(stamp.get("last_deployed_at_epoch") or 0.0)
        changed = fingerprint != last_fingerprint
        age = time.time() - last_deployed_at
        can_deploy = age >= float(args.min_deploy_seconds)

        state_updated_at = str(recorder.state.get("updated_at") or "")
        summary = recorder.state.get("summary") if isinstance(recorder.state.get("summary"), dict) else {}
        open_trades = summary.get("open_trades") if isinstance(summary, dict) else "?"
        live_exposure_count = summary.get("live_exposure_count") if isinstance(summary, dict) else "?"
        print(
            f"{_utc_now_label()} dashboard rebuild | updated_at={state_updated_at} "
            f"trades={len(recorder.state.get('trades', []))} open={open_trades} "
            f"live_exposure={live_exposure_count} changed={changed}",
            flush=True,
        )
        rebuild_stamp = {
            **stamp,
            "last_rebuilt_fingerprint": fingerprint,
            "last_rebuilt_at": _utc_now_label(),
            "last_rebuilt_at_epoch": time.time(),
            "last_state_updated_at": state_updated_at,
        }
        live_data_update = _publish_github_live_data(
            data_path=public_data,
            repo=str(args.github_live_repo or ""),
            branch=str(args.github_live_branch or DEFAULT_GITHUB_LIVE_BRANCH),
            remote_path=str(args.github_live_path or DEFAULT_GITHUB_LIVE_PATH),
            min_seconds=float(args.github_live_min_seconds),
            stamp=stamp,
        )
        if live_data_update:
            rebuild_stamp.update(live_data_update)
            if live_data_update.get("last_live_data_published_at"):
                print(
                    f"{_utc_now_label()} dashboard live-data ok | url={live_data_update.get('live_data_url')}",
                    flush=True,
                )
            elif live_data_update.get("last_live_data_error"):
                print(f"{_utc_now_label()} dashboard live-data erro", flush=True)

        if args.no_deploy or not str(args.deploy_command or "").strip():
            _write_json(
                stamp_path,
                {
                    **rebuild_stamp,
                    "last_no_deploy": True,
                    "last_deploy_skip_reason": "no_deploy" if args.no_deploy else "sem_deploy_command",
                    "last_deploy_skip_at": _utc_now_label(),
                },
            )
            return 0

        if not changed:
            _write_json(
                stamp_path,
                {
                    **rebuild_stamp,
                    "last_no_deploy": False,
                    "last_deploy_skip_reason": "sem_mudanca",
                    "last_deploy_skip_at": _utc_now_label(),
                },
            )
            print(f"{_utc_now_label()} dashboard deploy skip | sem mudanca", flush=True)
            return 0
        deploy_backoff_until = float(stamp.get("deploy_backoff_until_epoch") or 0.0)
        if deploy_backoff_until > time.time():
            remaining = deploy_backoff_until - time.time()
            _write_json(
                stamp_path,
                {
                    **rebuild_stamp,
                    "last_no_deploy": False,
                    "last_deploy_skip_reason": "backoff",
                    "last_deploy_skip_at": _utc_now_label(),
                },
            )
            print(
                f"{_utc_now_label()} dashboard deploy skip | backoff ativo restante={remaining:.0f}s",
                flush=True,
            )
            return 0
        if not can_deploy:
            _write_json(
                stamp_path,
                {
                    **rebuild_stamp,
                    "last_no_deploy": False,
                    "last_deploy_skip_reason": "janela_minima",
                    "last_deploy_skip_at": _utc_now_label(),
                },
            )
            print(
                f"{_utc_now_label()} dashboard deploy skip | aguardando janela "
                f"minima={args.min_deploy_seconds}s restante={max(0.0, float(args.min_deploy_seconds) - age):.0f}s",
                flush=True,
            )
            return 0

        command = _split_command(args.deploy_command)
        started = time.time()
        result = _run_deploy(command, cwd=ROOT, timeout=int(args.deploy_timeout))
        elapsed = time.time() - started
        output = result.stdout.strip()
        if output:
            print(output, flush=True)
        if result.returncode != 0:
            update = {
                **stamp,
                "last_rebuilt_fingerprint": fingerprint,
                "last_rebuilt_at": _utc_now_label(),
                "last_rebuilt_at_epoch": time.time(),
                "last_state_updated_at": state_updated_at,
                "last_deploy_error": output[-1200:],
                "last_deploy_error_at": _utc_now_label(),
            }
            if "api-deployments-free-per-day" in output:
                update["deploy_backoff_until"] = _utc_now_label()
                update["deploy_backoff_until_epoch"] = time.time() + 24 * 60 * 60
            _write_json(stamp_path, update)
            print(f"{_utc_now_label()} dashboard deploy erro | rc={result.returncode} duracao={elapsed:.1f}s", flush=True)
            return result.returncode

        _write_json(
            stamp_path,
            {
                "fingerprint": fingerprint,
                "deploy_backoff_until": "",
                "deploy_backoff_until_epoch": 0.0,
                "last_deployed_at": _utc_now_label(),
                "last_deployed_at_epoch": time.time(),
                "last_rebuilt_at": _utc_now_label(),
                "last_rebuilt_at_epoch": time.time(),
                "last_state_updated_at": state_updated_at,
                "public_html": str(public_html),
                "public_data": str(public_data),
                "deploy_command": args.deploy_command,
            },
        )
        print(f"{_utc_now_label()} dashboard deploy ok | duracao={elapsed:.1f}s", flush=True)
        return 0


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atualiza o dashboard de trades e opcionalmente publica com comando externo.")
    parser.add_argument("--loop", action="store_true", help="roda continuamente")
    parser.add_argument("--once", action="store_true", help="executa uma rodada e sai")
    parser.add_argument("--interval", type=float, default=60.0, help="segundos entre rebuilds")
    parser.add_argument("--min-deploy-seconds", type=float, default=60.0, help="intervalo minimo entre deploys")
    parser.add_argument("--deploy-timeout", type=int, default=240, help="timeout do deploy em segundos")
    parser.add_argument("--no-deploy", action="store_true", help="rebuild local sem publicar externamente")
    parser.add_argument("--no-live-exposure", action="store_true", help="nao consulta posicoes live Nado/Kraken")
    parser.add_argument("--deploy-command", default="", help="comando externo opcional para publicar apos rebuild")
    parser.add_argument("--github-live-repo", default=DEFAULT_GITHUB_LIVE_REPO, help="repo publico owner/name opcional para publicar dashboard-data.json vivo")
    parser.add_argument("--github-live-path", default=DEFAULT_GITHUB_LIVE_PATH, help="caminho do JSON vivo no repo publico")
    parser.add_argument("--github-live-branch", default=DEFAULT_GITHUB_LIVE_BRANCH, help="branch do repo publico de dados")
    parser.add_argument("--github-live-min-seconds", type=float, default=60.0, help="intervalo minimo entre updates do JSON publico")
    parser.add_argument("--setup-log", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--ccxt-log", default=str(DEFAULT_CCXT_LOG_PATH))
    parser.add_argument("--setup-state", default=str(DEFAULT_SETUP_STATE_PATH))
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--html", default=str(DEFAULT_HTML_PATH))
    parser.add_argument("--public-html", default=str(DEFAULT_PUBLIC_HTML_PATH))
    parser.add_argument("--public-data", default=str(DEFAULT_PUBLIC_DATA_PATH))
    parser.add_argument("--stamp-path", default=str(DEFAULT_STAMP_PATH))
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            rc = publish_once(args)
        except LockHeld as exc:
            print(f"{_utc_now_label()} dashboard publisher skip | {exc}", flush=True)
            rc = 0
        except Exception as exc:  # noqa: BLE001
            print(f"{_utc_now_label()} dashboard publisher erro | {exc}", flush=True)
            rc = 1
        if not args.loop:
            return rc
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
