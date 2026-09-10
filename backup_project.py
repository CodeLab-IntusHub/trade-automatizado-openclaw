from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXCLUDED_PARTS = {".venv", ".pytest_cache", "__pycache__", "dist"}
EXCLUDED_NAMES = {".env", "state.json", "setup_live_state.json"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo")
EXCLUDED_PATTERNS = (".env.", "batch-open-", "batch-status-")
ARTIFACTS = [
    "skill.json",
    "SKILL.md",
    "README.md",
    "INSTALL.md",
    "workspace/cli.py",
    "workspace/core/delta_neutral.py",
    "workspace/kraken/kraken_integration.py",
    "workspace/nado/nado_integration.py",
]


def should_copy(path: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    if path.name.endswith(EXCLUDED_SUFFIXES):
        return False
    return not any(pattern in path.name for pattern in EXCLUDED_PATTERNS)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = ROOT.parent / f"{ROOT.name}-backup-{timestamp}"
    dst.mkdir(parents=True, exist_ok=False)

    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not should_copy(rel):
            continue
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    skill = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))
    artifact_paths = [Path(p) for p in ARTIFACTS]
    artifact_paths.extend(Path("dist") / item.name for item in (ROOT / "dist").glob("*.skill"))
    artifacts = []
    for rel in dict.fromkeys(artifact_paths):
        full = ROOT / rel
        if not full.exists():
            continue
        artifacts.append(
            {
                "relative_path": rel.as_posix(),
                "size_bytes": full.stat().st_size,
                "sha256": sha256_file(full),
            }
        )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(ROOT),
        "backup_path": str(dst),
        "skill_name": skill["name"],
        "skill_version": skill["version"],
        "artifacts": artifacts,
    }
    (dst / "backup-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return dst


if __name__ == "__main__":
    print(create_backup())
