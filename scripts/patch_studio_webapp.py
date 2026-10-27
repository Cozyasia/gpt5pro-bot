"""Apply the Studio WebApp hook to a reviewed copy of main.py.

This is intentionally a fail-closed patch tool. It refuses to edit if the
expected function shape has changed. It does NOT deploy or change GitHub main.
Usage:
    python scripts/patch_studio_webapp.py main.py --output /tmp/main.studio.py
"""
from __future__ import annotations
import argparse
import ast
from pathlib import Path

ANCHOR = '        typ = (data.get("type") or data.get("action") or "").lower()'
INSERT = '''        # Studio navigation is isolated from subscription/payment flows.
        # It creates a Telegram callback button; it never dispatches a callback
        # automatically or grants access to a paid/medical function.
        from neyrobot_prod.studio_menu_telegram import studio_navigation_markup
        studio_result = studio_navigation_markup(raw)
        if studio_result is not None:
            studio_text, studio_markup = studio_result
            await update.effective_message.reply_text(
                studio_text, reply_markup=studio_markup
            )
            return

'''


def patch(source: str) -> str:
    tree = ast.parse(source)
    handlers = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "on_webapp_data"]
    if len(handlers) != 1:
        raise ValueError("Expected exactly one top-level on_webapp_data")
    fn = handlers[0]
    lines = source.splitlines(keepends=True)
    first, last = fn.lineno, fn.end_lineno
    block = "".join(lines[first - 1:last])
    if "studio_navigation_markup" in block:
        raise ValueError("Studio hook already present; refusing duplicate")
    if block.count(ANCHOR) != 1:
        raise ValueError("Payment dispatch anchor missing or changed")
    if "subscribe" not in block or "topup_crypto" not in block:
        raise ValueError("Expected existing payment handlers not found")
    index = next(i for i in range(first - 1, last) if ANCHOR in lines[i])
    lines.insert(index, INSERT)
    result = "".join(lines)
    ast.parse(result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.source.resolve() == args.output.resolve():
        p.error("Output must differ from input")
    args.output.write_text(patch(args.source.read_text(encoding="utf-8")), encoding="utf-8")
