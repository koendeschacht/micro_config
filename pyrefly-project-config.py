#!/usr/bin/env python3
"""Build a micro-only Pyrefly config for the active Git worktree."""

import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

PROFILES = Path(__file__).with_name("project-lsp.json")
OUTPUT_DIR = Path("/tmp/micro-pyrefly")
PATH_LIST_KEYS = {"project-includes", "project-excludes", "search-path", "site-package-path"}
PATH_KEYS = {"python-interpreter-path", "typeshed-path", "baseline"}


def project_identity(start: Path) -> tuple[Path, str] | None:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    root_name, common_name = result.stdout.splitlines()
    root = Path(root_name).resolve()
    common = Path(common_name)
    if not common.is_absolute():
        common = start / common
    common = common.resolve()
    return root, common.parent.name if common.name == ".git" else common.name


def absolute_path(root: Path, value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else root / path)


def toml_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported Pyrefly config value: {type(value).__name__}")


def toml_lines(values: dict[str, object], prefix: str = "") -> list[str]:
    lines = []
    for key, value in values.items():
        if not isinstance(value, dict) and not (isinstance(value, list) and value and isinstance(value[0], dict)):
            lines.append(f"{json.dumps(key)} = {toml_value(value)}")
    for key, value in values.items():
        section = f"{prefix}.{json.dumps(key)}" if prefix else json.dumps(key)
        if isinstance(value, dict):
            lines.extend(["", f"[{section}]", *toml_lines(value, section)])
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                lines.extend(["", f"[[{section}]]", *toml_lines(item, section)])
    return lines


def build(start: Path) -> str:
    identity = project_identity(start)
    if identity is None:
        return ""
    root, name = identity
    profiles = json.loads(PROFILES.read_text())
    profile = profiles.get(name)
    if profile is None:
        return ""

    project_file = root / "pyproject.toml"
    project_settings = (
        tomllib.loads(project_file.read_text()).get("tool", {}).get("pyrefly", {})
        if project_file.exists()
        else {}
    )
    settings = dict(project_settings)
    for key in PATH_LIST_KEYS:
        if key in settings:
            settings[key] = [absolute_path(root, value) for value in settings[key]]
    for key in PATH_KEYS:
        if key in settings:
            settings[key] = absolute_path(root, settings[key])

    settings.setdefault("project-includes", [str(root / "**/*.py*")])
    discovered_roots = []
    for pattern in profile["sourceRoots"]:
        discovered_roots.extend(str(path) for path in sorted(root.glob(pattern)) if path.is_dir())
    source_roots = [str(root)]
    interpreter = root / ".venv/bin/python"
    if interpreter.exists():
        result = subprocess.run(
            [str(interpreter), "-c", "import json, sys; print(json.dumps(sys.path))"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            source_roots.extend(path for path in json.loads(result.stdout) if path in discovered_roots)
    source_roots.extend(discovered_roots)
    source_roots.extend(settings.get("search-path", []))
    settings["search-path"] = list(dict.fromkeys(source_roots))
    if "python-interpreter-path" not in settings and interpreter.exists():
        settings["python-interpreter-path"] = str(interpreter)

    OUTPUT_DIR.mkdir(mode=0o700, exist_ok=True)
    output = OUTPUT_DIR / f"{name}-{hashlib.sha256(str(root).encode()).hexdigest()[:16]}.toml"
    content = "\n".join(toml_lines(settings)) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", dir=OUTPUT_DIR, delete=False) as temporary:
        temporary.write(content)
    Path(temporary.name).replace(output)
    return str(output)


if __name__ == "__main__":
    print(build(Path(sys.argv[1]).resolve()))
