"""
Build script: empacota a skill num `.skill` zip seguindo o padrão
OpenClaw.

Uso:
    py -3 build.py              # gera dist/trade-automatizado-openclaw.skill
    py -3 build.py --validate   # só valida manifest e estrutura
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

# Windows console default é cp1252 e quebra em emoji. Força UTF-8.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

REQUIRED_FILES = ["SKILL.md", "skill.json", "README.md", "LICENSE"]
REQUIRED_DIRS = ["workspace", "resources"]
EXCLUDE = {"__pycache__", ".git", ".venv", "venv", "dist", "node_modules", ".pytest_cache", "playwright-report", "test-results", ".playwright", "blob-report"}
EXCLUDE_FILES = {".env", "state.json"}


def validate() -> dict:
    errors: list[str] = []

    for f in REQUIRED_FILES:
        if not (ROOT / f).exists():
            errors.append(f"Missing required file: {f}")

    for d in REQUIRED_DIRS:
        if not (ROOT / d).is_dir():
            errors.append(f"Missing required dir: {d}")

    # Parse skill.json
    manifest = {}
    try:
        manifest = json.loads((ROOT / "skill.json").read_text(encoding="utf-8"))
        for key in ("name", "version", "description", "license"):
            if not manifest.get(key):
                errors.append(f"skill.json: missing or empty field `{key}`")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"skill.json invalid JSON: {exc}")

    # SKILL.md frontmatter
    skill_md = (ROOT / "SKILL.md").read_text(encoding="utf-8") if (ROOT / "SKILL.md").exists() else ""
    if not skill_md.startswith("---"):
        errors.append("SKILL.md must start with YAML frontmatter (---)")
    else:
        front = skill_md.split("---", 2)[1] if "---" in skill_md[3:] else ""
        if "name:" not in front:
            errors.append("SKILL.md frontmatter missing `name:`")
        if "description:" not in front:
            errors.append("SKILL.md frontmatter missing `description:`")

    if errors:
        print("❌ Validation errors:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)

    print(f"✅ Valid skill: {manifest.get('name')} v{manifest.get('version')}")
    return manifest


def build(manifest: dict) -> Path:
    DIST.mkdir(exist_ok=True)
    skill_name = manifest["name"]
    version = manifest["version"]
    out_file = DIST / f"{skill_name}-{version}.skill"

    added = 0
    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if any(part in EXCLUDE for part in path.parts):
                continue
            if path.is_dir():
                continue
            if path.name in EXCLUDE_FILES:
                continue
            if path == out_file:
                continue
            # Relative path from skill root
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("dist/"):
                continue
            zf.write(path, rel)
            added += 1

    size_kb = out_file.stat().st_size / 1024
    print(f"📦 Built {out_file.name}  ({added} files, {size_kb:.1f} KB)")
    # Also produce latest symlink-ish
    latest = DIST / f"{skill_name}.skill"
    latest.write_bytes(out_file.read_bytes())
    print(f"📦 Also wrote {latest.name} (latest)")
    return out_file


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validate", action="store_true", help="Só valida, não empacota")
    args = p.parse_args()

    manifest = validate()
    if args.validate:
        return
    build(manifest)


if __name__ == "__main__":
    main()
