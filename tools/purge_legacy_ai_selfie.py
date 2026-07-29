#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove the legacy Celebrity/Star AI-selfie feature from Python source.

This is intentionally a one-way source migration. It removes the old menus,
callbacks, state flags, providers, handlers and metadata while leaving the
separate generic FaceSwap/photo-editing feature untouched.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Iterable

MACHINE_MARKERS = (
    "aiselfie",
    "ai_selfie",
    "celebrity_selfie",
    "awaiting_ai_selfie",
    "as_preset_",
    "cs201",
    "cs202",
    "cs203",
    "cs204",
    "cs205",
    "cs206",
    "cs207",
    "cs208",
    "cs209",
    "cs210",
    "cs211",
    "cs212",
    "cs213",
    "cs214",
    "cs215",
    "cs216",
    "cs217",
    "cs218",
    "cs219",
    "cs220",
    "cs221",
    "cs222",
    "cs223",
    "cs224",
    "cs225",
    "cs226",
    "cs227",
    "cs228",
    "cs229",
    "cs230",
    "cs231",
    "cs232",
    "cs233",
    "cs234",
    "cs235",
    "cs236",
)
HUMAN_MARKERS = (
    "ai-селфи со звездой",
    "ai-селфи со знаменитостью",
    "селфи со звездой",
    "селфи со знаменитостью",
)


def _contains_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in MACHINE_MARKERS) or any(marker in lowered for marker in HUMAN_MARKERS)


def _target_names(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from _target_names(item)
    elif isinstance(node, ast.Attribute):
        yield node.attr


class Purger(ast.NodeTransformer):
    def __init__(self, source: str) -> None:
        self.source = source
        self.removed = 0

    def _segment(self, node: ast.AST) -> str:
        return ast.get_source_segment(self.source, node) or ""

    def _drop(self) -> None:
        self.removed += 1

    def visit_Import(self, node: ast.Import):
        kept = [alias for alias in node.names if not _contains_marker(alias.name)]
        if not kept:
            self._drop()
            return None
        node.names = kept
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        if _contains_marker(module):
            self._drop()
            return None
        kept = [alias for alias in node.names if not _contains_marker(alias.name)]
        if not kept:
            self._drop()
            return None
        node.names = kept
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if _contains_marker(node.name):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if _contains_marker(node.name):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        if _contains_marker(node.name):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        names = [name for target in node.targets for name in _target_names(target)]
        if any(_contains_marker(name) for name in names) or _contains_marker(self._segment(node)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if any(_contains_marker(name) for name in _target_names(node.target)) or _contains_marker(self._segment(node)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        if any(_contains_marker(name) for name in _target_names(node.target)) or _contains_marker(self._segment(node)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_If(self, node: ast.If):
        if _contains_marker(self._segment(node.test)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_While(self, node: ast.While):
        if _contains_marker(self._segment(node.test)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr):
        if _contains_marker(self._segment(node)):
            self._drop()
            return None
        return self.generic_visit(node)

    def visit_List(self, node: ast.List):
        new_elts = []
        for elt in node.elts:
            if _contains_marker(self._segment(elt)):
                self._drop()
            else:
                visited = self.visit(elt)
                if visited is not None:
                    new_elts.append(visited)
        node.elts = new_elts
        return node

    def visit_Tuple(self, node: ast.Tuple):
        new_elts = []
        for elt in node.elts:
            if _contains_marker(self._segment(elt)):
                self._drop()
            else:
                visited = self.visit(elt)
                if visited is not None:
                    new_elts.append(visited)
        node.elts = new_elts
        return node

    def visit_Set(self, node: ast.Set):
        new_elts = []
        for elt in node.elts:
            if _contains_marker(self._segment(elt)):
                self._drop()
            else:
                visited = self.visit(elt)
                if visited is not None:
                    new_elts.append(visited)
        node.elts = new_elts
        return node

    def visit_Dict(self, node: ast.Dict):
        keys, values = [], []
        for key, value in zip(node.keys, node.values):
            segment = self._segment(value) + (self._segment(key) if key else "")
            if _contains_marker(segment):
                self._drop()
                continue
            new_key = self.visit(key) if key is not None else None
            new_value = self.visit(value)
            if new_value is not None:
                keys.append(new_key)
                values.append(new_value)
        node.keys, node.values = keys, values
        return node

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            value = node.value
            replacements = {
                "AI-селфи со звездой": "AI-фото",
                "AI-селфи со знаменитостью": "AI-фото",
                "селфи со звездой": "AI-фото",
                "селфи со знаменитостью": "AI-фото",
                "AI-селфи": "AI-фото",
            }
            for old, new in replacements.items():
                value = value.replace(old, new)
            node.value = value
        return node


def _ensure_nonempty_bodies(tree: ast.AST) -> None:
    body_fields = ("body", "orelse", "finalbody")
    for node in ast.walk(tree):
        for field in body_fields:
            value = getattr(node, field, None)
            if field == "body" and isinstance(value, list) and not value and isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try),
            ):
                value.append(ast.Pass())
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if not handler.body:
                    handler.body.append(ast.Pass())


def purge_source(source: str, filename: str = "<source>") -> tuple[str, int]:
    tree = ast.parse(source, filename=filename)
    purger = Purger(source)
    tree = purger.visit(tree)
    _ensure_nonempty_bodies(tree)
    ast.fix_missing_locations(tree)
    output = ast.unparse(tree) + "\n"
    compile(output, filename, "exec")
    residual = [marker for marker in MACHINE_MARKERS if marker in output.lower()]
    residual += [marker for marker in HUMAN_MARKERS if marker in output.lower()]
    if residual:
        raise RuntimeError(f"legacy AI-selfie markers remain: {sorted(set(residual))}")
    return output, purger.removed


def purge_file(path: Path, *, check: bool = False) -> int:
    original = path.read_text(encoding="utf-8")
    output, removed = purge_source(original, str(path))
    if check:
        if output != original:
            raise SystemExit(f"{path}: legacy AI-selfie code is still present ({removed} AST nodes)")
        return 0
    if output != original:
        backup = path.with_suffix(path.suffix + ".pre-ai-selfie-purge.bak")
        if not backup.exists():
            backup.write_text(original, encoding="utf-8")
        path.write_text(output, encoding="utf-8")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="main.py")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(args.path).resolve()
    removed = purge_file(path, check=args.check)
    print(f"AI_SELFIE_PURGE_OK path={path} removed_nodes={removed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
