from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "src" / "services"
SCAN_TARGETS = [
    ROOT / "src" / "ui_qt",
    ROOT / "src" / "cli",
    ROOT / "src" / "app_qt.py",
    ROOT / "src" / "launcher.py",
    ROOT / "src" / "launcher_settings.py",
]

RULES = {
    "realtime": {
        "file_prefix": "realtime",
        "deny_prefixes": ("src.report", "src.services.report"),
    },
    "report": {
        "file_prefix": "report",
        "deny_prefixes": ("src.services.realtime",),
    },
}

IMPL_FORBIDDEN_PREFIX = "src.services."
IMPL_SUFFIX = "_impl"
COMPAT_MODULES = (
    "src.report.export_core",
    "src.runtime.runner",
    "src.ui_qt.worker",
)
COMPAT_IMPL_ALLOWLIST = {
    (ROOT / "src" / "ui_qt" / "worker.py").resolve(),
}


def _iter_imports(tree: ast.AST) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports.append((node.lineno, name.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, node.module))
    return imports


def _check_file(path: Path, role: str) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text, filename=str(path))
    imports = _iter_imports(tree)
    deny_prefixes = RULES[role]["deny_prefixes"]
    violations: list[str] = []
    for lineno, module in imports:
        if module.startswith(deny_prefixes):
            violations.append(f"{path}:{lineno} imports {module}")
    return violations


def _iter_scan_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(target.rglob("*.py"))
    return files


def _check_layer_imports(paths: list[Path]) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        tree = ast.parse(text, filename=str(path))
        resolved = path.resolve()
        for lineno, module in _iter_imports(tree):
            if module.startswith(IMPL_FORBIDDEN_PREFIX) and IMPL_SUFFIX in module:
                if resolved not in COMPAT_IMPL_ALLOWLIST:
                    violations.append(f"{path}:{lineno} imports {module}")
            if module.startswith(COMPAT_MODULES):
                warnings.append(f"{path}:{lineno} imports {module}")
    return violations, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services-dir", default=str(SERVICES_DIR))
    args = parser.parse_args()

    services_dir = Path(args.services_dir)
    if not services_dir.exists():
        print(f"[check_service_imports] services dir not found: {services_dir}")
        return 2

    violations: list[str] = []
    for path in services_dir.glob("*.py"):
        name = path.stem
        for role, rule in RULES.items():
            if name.startswith(rule["file_prefix"]):
                violations.extend(_check_file(path, role))

    layer_files = _iter_scan_files(SCAN_TARGETS)
    layer_violations, layer_warnings = _check_layer_imports(layer_files)

    if violations:
        print("[check_service_imports] forbidden imports detected:")
        for item in violations:
            print(f" - {item}")
        return 1

    if layer_violations:
        print("[check_layer_imports] forbidden imports detected:")
        for item in layer_violations:
            print(f" - {item}")
        return 1

    if layer_warnings:
        print("[check_layer_imports] WARNING: compat shell imports detected:")
        for item in layer_warnings:
            print(f" - {item} (consider using Service interface)")

    print("[check_service_imports] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
