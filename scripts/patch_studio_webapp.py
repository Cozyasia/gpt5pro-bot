"""Safely prepare Studio integration against the CURRENT production main.py.

Usage: python scripts/patch_studio_webapp.py main.py --output /tmp/main.studio.py
Never writes to the source file, never deploys, and fails on unexpected shapes.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

ANCHOR = 'typ = (data.get("type") or data.get("action") or "").lower()'


def patch(source: str) -> str:
    tree = ast.parse(source)
    handlers = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "on_webapp_data"]
    if len(handlers) != 1:
        raise ValueError("Expected exactly one top-level on_webapp_data")
    fn = handlers[0]
    lines = source.splitlines(keepends=True)
    block = "".join(lines[fn.lineno - 1:fn.end_lineno])
    if "studio_navigation_markup" in block:
        raise ValueError("Studio hook already present")
    anchors = [i for i in range(fn.lineno - 1, fn.end_lineno)
               if lines[i].strip() == ANCHOR]
    if len(anchors) != 1:
        raise ValueError("Current-main payment dispatch anchor missing or ambiguous")
    if "subscribe" not in block or "topup_crypto" not in block:
        raise ValueError("Current-main payment paths not found; manual review required")
    index = anchors[0]
    indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
    insert = [
        "# Studio navigation: isolated from payment/subscription handling.",
        "from neyrobot_prod.studio_menu_telegram import studio_navigation_markup",
        "studio_result = studio_navigation_markup(raw)",
        "if studio_result is not None:",
        "    studio_text, studio_markup = studio_result",
        "    await update.effective_message.reply_text(studio_text, reply_markup=studio_markup)",
        "    return",
        "",
    ]
    lines[index:index] = [
        indent + line + "\n" if line else "\n" for line in insert
    ]
    result = "".join(lines)
    ast.parse(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error("Output must differ from input")
    args.output.write_text(patch(args.source.read_text(encoding="utf-8")), encoding="utf-8")
