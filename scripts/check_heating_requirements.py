#!/usr/bin/env python3
"""
Ensure requirements-heating.txt stays aligned with backend/pyproject.toml.

Every [project].dependencies entry must appear in requirements-heating.txt with a
specifier that does not allow versions below what pyproject.toml requires (so the
Lambda bundle cannot resolve looser than the library).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None  # type: ignore[misc, assignment]

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _project_table_block(text: str) -> str:
    lines = text.splitlines()
    buf: list[str] = []
    in_project = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == "[project]":
                in_project = True
                continue
            if in_project:
                break
            continue
        if in_project:
            buf.append(line)
    return "\n".join(buf)


def _dependencies_from_project_block(block: str) -> list[str]:
    key = "dependencies"
    i = block.find(key)
    if i < 0:
        raise SystemExit("No dependencies = … found under [project] in pyproject.toml")
    eq = block.find("=", i)
    if eq < 0:
        raise SystemExit("Malformed dependencies assignment in pyproject.toml")
    lb = block.find("[", eq)
    if lb < 0:
        raise SystemExit("Expected dependencies = [ … ] in pyproject.toml")
    depth = 0
    end = -1
    for pos in range(lb, len(block)):
        c = block[pos]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
    if end < 0:
        raise SystemExit("Unclosed dependencies list in pyproject.toml")
    raw_list = block[lb:end]
    try:
        val = ast.literal_eval(raw_list)
    except (SyntaxError, ValueError) as e:
        raise SystemExit(f"Could not parse dependencies list: {e}") from e
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise SystemExit("dependencies must be a list of strings in pyproject.toml")
    return val


def _load_pyproject_dependencies(pyproject_path: Path) -> list[str]:
    text = pyproject_path.read_text(encoding="utf-8")
    if tomllib is not None:
        data = tomllib.loads(text)
        project = data.get("project")
        if not isinstance(project, dict):
            return []
        deps = project.get("dependencies")
        if deps is None:
            return []
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise SystemExit(f"Unexpected [project].dependencies shape in {pyproject_path}")
        return deps
    return _dependencies_from_project_block(_project_table_block(text))


def _parse_requirements_path(path: Path) -> dict[str, Requirement]:
    by_name: dict[str, Requirement] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        key = canonicalize_name(req.name)
        if key in by_name:
            raise SystemExit(f"Duplicate package in {path}: {req.name!r}")
        by_name[key] = req
    return by_name


def _minimum_lower_bound(spec_str: str) -> Version | None:
    """
    Best-effort minimum version implied by simple PEP 440 specifiers we use in this repo.

    Returns the highest lower bound from >= and == clauses; ignores upper bounds and
    extras. None means no comparable floor (unconstrained or unsupported operators).
    """
    if not spec_str or spec_str == "*":
        return None
    floors: list[Version] = []
    for part in spec_str.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith(">="):
            ver_s = part[2:].strip()
        elif part.startswith("=="):
            ver_s = part[2:].strip()
        elif part.startswith("~="):
            ver_s = part.split("~=", 1)[1].strip()
        else:
            # e.g. !=, <, > without combining — skip for floor extraction
            continue
        try:
            floors.append(Version(ver_s))
        except InvalidVersion:
            continue
    return max(floors) if floors else None


def _heating_covers_pyproject(heat: Requirement, proj: Requirement) -> str | None:
    """Return error message if heating allows a version pyproject rejects; else None."""
    proj_floor = _minimum_lower_bound(str(proj.specifier))
    if proj_floor is None:
        return None

    heat_floor = _minimum_lower_bound(str(heat.specifier))
    if heat_floor is None:
        return (
            f"{proj.name}: pyproject pins {proj.specifier!s} but heating has no "
            f"compatible lower bound — add an explicit >= that is at least {proj_floor}"
        )

    if heat_floor < proj_floor:
        return (
            f"{proj.name}: heating allows down to {heat_floor} but pyproject requires "
            f">= {proj_floor} — tighten requirements-heating.txt (e.g. >={proj_floor})"
        )

    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=_repo_root() / "backend" / "pyproject.toml",
        help="Path to backend pyproject.toml",
    )
    parser.add_argument(
        "--heating",
        type=Path,
        default=_repo_root() / "requirements-heating.txt",
        help="Path to requirements-heating.txt",
    )
    args = parser.parse_args(argv)

    if not args.pyproject.is_file():
        print(f"Missing {args.pyproject}", file=sys.stderr)
        return 2
    if not args.heating.is_file():
        print(f"Missing {args.heating}", file=sys.stderr)
        return 2

    pyproject_deps = _load_pyproject_dependencies(args.pyproject)
    heating_by_name = _parse_requirements_path(args.heating)

    errors: list[str] = []
    for dep_str in pyproject_deps:
        proj_req = Requirement(dep_str)
        key = canonicalize_name(proj_req.name)
        heat_req = heating_by_name.get(key)
        if heat_req is None:
            errors.append(
                f"{proj_req.name}: listed in {args.pyproject} but missing from {args.heating}"
            )
            continue
        msg = _heating_covers_pyproject(heat_req, proj_req)
        if msg:
            errors.append(msg)

    if errors:
        print("Heating requirements check failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"OK: {args.heating.name} covers all {len(pyproject_deps)} "
        f"pyproject dependency package(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
