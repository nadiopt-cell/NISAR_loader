# -*- coding: utf-8 -*-
"""
Static import-graph check: every *relative* import in the plugin and
tests must resolve to an existing module. Absolute imports (stdlib,
qgis.*, ...) are out of scope. Runs without QGIS/Qt (TZ P0.2 guard).

Usage: python scripts_import_check.py
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PLUGIN = REPO / "nisar_qgis"


def module_parts(path: Path):
    rel = path.relative_to(REPO).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        is_init = True
        parts = parts[:-1]
    else:
        is_init = False
    return parts, is_init


def resolve_relative(module_parts_, is_init: bool, level: int,
                     module: str):
    """Resolve `from <level dots><module> import ...` to a full dotted name."""
    pkg = module_parts_ if is_init else module_parts_[:-1]
    if level == 1:
        prefix = pkg
    else:
        prefix = pkg[: len(pkg) - (level - 1)]
    if prefix is None or len(prefix) < 0 or (level - 1) > len(pkg):
        return None
    parts = list(prefix) + ([module] if module else [])
    return ".".join(parts)


def module_exists(full: str) -> bool:
    if not full:
        return False
    base = REPO
    parts = full.split(".")
    for i, part in enumerate(parts):
        candidate = base / part
        if (candidate.with_suffix(".py")).is_file():
            # module file must be the last part
            return i == len(parts) - 1
        if candidate.is_dir() and (candidate / "__init__.py").is_file():
            base = candidate
            continue
        return False
    return True  # package (dir with __init__)


def check_file(path: Path):
    errors = []
    parts, is_init = module_parts(path)
    mod = ".".join(parts)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        level = node.level or 0
        if level == 0:
            continue  # absolute import — not our business here
        full = resolve_relative(parts, is_init, level, node.module)
        if full is None:
            errors.append("%s: too many dots in 'from %s%s import ...'"
                          % (mod, "." * level, node.module or ""))
            continue
        if not module_exists(full):
            errors.append(
                "%s: cannot resolve 'from %s%s import %s' -> %s"
                % (mod, "." * level, node.module or "",
                   ", ".join(a.name for a in node.names), full))
    return errors


def main():
    errors = []
    files = sorted(PLUGIN.rglob("*.py"))
    files += sorted((REPO / "tests").rglob("*.py"))
    files += [REPO / "conftest.py"]
    for path in files:
        if path.name == "__init__.py" and path.parent == REPO:
            continue
        errors.extend(check_file(path))
    if errors:
        print("IMPORT GRAPH ERRORS (%d):" % len(errors))
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("Import graph OK: %d files checked, all relative imports resolve."
          % len(files))


if __name__ == "__main__":
    main()
