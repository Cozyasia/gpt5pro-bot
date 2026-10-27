"""Prepare a guarded /start Studio hook against the checked-out production main.py.

This script does not overwrite the source and never executes bot handlers.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

PAYMENT_ANCHOR = "if await _handle_payment_start_payload(update, context):"
HOOK = "studio_start_markup(context.args)"

def patch(source: str) -> str:
    tree = ast.parse(source)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_start"]
    lines = source.splitlines(keepends=True)
    functions = [node for node in functions if PAYMENT_ANCHOR in "".join(lines[node.lineno - 1:node.end_lineno])]
    # Python resolves duplicate definitions to the last binding in module execution order.
    # Require that the final candidate contains the current duplicate-update guard.
    guarded = [node for node in functions if "_claim_start_update(update)" in "".join(lines[node.lineno - 1:node.end_lineno])]
    if len(guarded) != 1 or guarded[0] is not functions[-1]:
        raise ValueError("Expected final payment-aware cmd_start with update guard; candidates: " + repr([node.lineno for node in functions]))
    fn = guarded[0]
    block = "".join(lines[fn.lineno - 1:fn.end_lineno])
    if HOOK in block:
        raise ValueError("Studio start hook already installed")
    anchors = [index for index in range(fn.lineno - 1, fn.end_lineno) if lines[index].strip() == PAYMENT_ANCHOR]
    if len(anchors) != 1:
        raise ValueError("Payment handler anchor missing or ambiguous")
    index = anchors[0]
    payment_indent = lines[index][:len(lines[index])-len(lines[index].lstrip())]
    # Insert only after the payment early-return, preserving payment precedence.
    return_line = index + 1
    if return_line >= len(lines) or lines[return_line].strip() != "return":
        raise ValueError("Payment handler is not a simple early return")
    if not lines[return_line].startswith(payment_indent + "    "):
        raise ValueError("Unexpected payment return indentation")
    injection = [
        "from neyrobot_prod.studio_menu_start import studio_start_markup",
        "studio_entry = studio_start_markup(context.args)",
        "if studio_entry is not None:",
        "    studio_title, studio_markup = studio_entry",
        "    await update.effective_chat.send_message(",
        "        'Раздел: ' + studio_title, reply_markup=studio_markup",
        "    )",
        "    return",
    ]
    lines[return_line+1:return_line+1] = [payment_indent+line+"\n" for line in injection]
    result = "".join(lines)
    ast.parse(result)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error("Output must differ from source")
    args.output.write_text(patch(args.source.read_text(encoding="utf-8")), encoding="utf-8")
