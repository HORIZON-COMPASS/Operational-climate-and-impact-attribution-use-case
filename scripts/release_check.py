#!/usr/bin/env python3
"""Static checks that are safe to run without scientific dependencies or data."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".cff", ".md", ".patch", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
FORBIDDEN_PATH_SUFFIXES = {".grib", ".grib2", ".h5", ".hdf5", ".nc", ".nc4"}
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
FORBIDDEN_TEXT = {
    "/" + "Users" + "/": "personal macOS path",
    "/" + "Volumes" + "/": "personal mounted-volume path",
    "webhook" + ".site": "temporary external webhook",
}
SECRET_PATTERNS = {
    "AWS access key": re.compile("A" + r"KIA[0-9A-Z]{16}"),
    "GitHub token": re.compile("gh" + r"[pousr]_[A-Za-z0-9_]{20,}"),
    "GitHub fine-grained token": re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}"),
    "private key": re.compile("BEGIN " + r"[A-Z ]*PRIVATE KEY"),
}
REQUIRED_FILES = {
    ".gitignore",
    "ATTRICI_MODIFICATIONS.md",
    "CITATION.cff",
    "KNOWN_LIMITATIONS.md",
    "LICENSE.txt",
    "licenses/scikit-learn-BSD-3-Clause.txt",
    "NOTICE.md",
    "patches/attrici-compass.patch",
    "README.md",
    "SECURITY.md",
    "attrici/counterfactual/settings.example.toml",
    "environments/attrici.yml",
    "environments/crop-model.yml",
    "environments/daily-data.yml",
}


def repository_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts):
            yield path


def check_required(errors: list[str]):
    for relative in sorted(REQUIRED_FILES):
        if not (ROOT / relative).is_file():
            errors.append(f"missing required release file: {relative}")


def check_file_set(errors: list[str]):
    for path in repository_files():
        relative = path.relative_to(ROOT)
        if path.name in {".DS_Store", ".cdsapirc", ".env", ".netrc"}:
            errors.append(f"forbidden local file: {relative}")
        if path.suffix.lower() in FORBIDDEN_PATH_SUFFIXES:
            errors.append(f"scientific data file must not be committed: {relative}")
        if "settings.production" in path.name or "settings.local" in path.name:
            errors.append(f"machine-specific settings file: {relative}")


def check_text(errors: list[str]):
    for path in repository_files():
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".gitignore":
            continue
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"text file is not UTF-8: {path.relative_to(ROOT)}")
            continue
        for needle, label in FORBIDDEN_TEXT.items():
            if needle in value:
                errors.append(f"{label} in {path.relative_to(ROOT)}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(value):
                errors.append(f"possible {label} in {path.relative_to(ROOT)}")


def check_python_syntax(errors: list[str]):
    for path in repository_files():
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"Python syntax error in {path.relative_to(ROOT)}: {exc}")


def check_shell_syntax(errors: list[str]):
    for path in repository_files():
        if path.suffix != ".sh":
            continue
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, check=False
        )
        if result.returncode:
            errors.append(
                f"shell syntax error in {path.relative_to(ROOT)}: {result.stderr.strip()}"
            )


def main() -> int:
    errors: list[str] = []
    check_required(errors)
    check_file_set(errors)
    check_text(errors)
    check_python_syntax(errors)
    check_shell_syntax(errors)
    if errors:
        print("Release check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Release check passed: structure, safety patterns, Python and shell syntax.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
