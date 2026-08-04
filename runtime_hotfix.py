# -*- coding: utf-8 -*-
"""Small, reversible production bootstrap for V232.

It keeps the restored V232 main.py untouched and replaces only two audited
functions at process start:
  * OpenAI retouch -> local-mask/original-preserving implementation;
  * Telegram ApplicationBuilder -> production media transport timeouts.

If a named target disappears after a future main.py update, the process fails
closed instead of silently running an unsafe full-frame retouch pipeline.
"""
from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot.runtime-hotfix")

ROOT = Path(__file__).resolve().parent
MAIN_PATH = ROOT / "main.py"

_RET_CODE = '''
async def _openai_image_edit_bytes(img_bytes: bytes, user_instruction: str) -> bytes | None:
    return await guarded_openai_retouch(
        img_bytes,
        user_instruction,
        api_key=OPENAI_IMAGE_KEY,
        base_url=IMAGES_BASE_URL,
        model=IMAGES_MODEL,
        quality=OPENAI_IMAGE_QUALITY,
        timeout_s=float(os.environ.get("RETOUCH_TIMEOUT_S", "180") or "180"),
    )
'''


class _ProductionPatch(ast.NodeTransformer):
    def __init__(self) -> None:
        self.retouch_replaced = 0
        self.builder_hardened = 0

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if node.name == "_openai_image_edit_bytes":
            replacement = ast.parse(_RET_CODE).body[0]
            replacement = ast.copy_location(replacement, node)
            self.retouch_replaced += 1
            return replacement
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        node = self.generic_visit(node)
        if node.name != "build_application":
            return node

        hardened: list[ast.stmt] = []
        inserted = False
        for statement in node.body:
            hardened.append(statement)
            # Insert directly after: builder = ApplicationBuilder().token(BOT_TOKEN)
            if (
                not inserted
                and isinstance(statement, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "builder" for t in statement.targets)
            ):
                patch = ast.parse(
                    '''
builder = (
    builder
    .connect_timeout(float(os.environ.get("TELEGRAM_CONNECT_TIMEOUT_S", "30") or "30"))
    .read_timeout(float(os.environ.get("TELEGRAM_READ_TIMEOUT_S", "90") or "90"))
    .write_timeout(float(os.environ.get("TELEGRAM_WRITE_TIMEOUT_S", "90") or "90"))
    .media_write_timeout(float(os.environ.get("TELEGRAM_MEDIA_WRITE_TIMEOUT_S", "180") or "180"))
    .pool_timeout(float(os.environ.get("TELEGRAM_POOL_TIMEOUT_S", "30") or "30"))
)
'''
                ).body
                hardened.extend(patch)
                inserted = True
                self.builder_hardened += 1
        node.body = hardened
        return node


def _compile_patched_main() -> object:
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MAIN_PATH))

    # Imported into the transformed module's own global namespace.
    import_node = ast.ImportFrom(
        module="retouch_guard",
        names=[ast.alias(name="guarded_openai_retouch", asname=None)],
        level=0,
    )
    # Keep encoding/docstring semantics valid: insert after module docstring and
    # future imports, before ordinary imports.
    insert_at = 0
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(getattr(tree.body[0], "value", None), ast.Constant):
        if isinstance(tree.body[0].value.value, str):
            insert_at = 1
    while insert_at < len(tree.body) and isinstance(tree.body[insert_at], ast.ImportFrom) and tree.body[insert_at].module == "__future__":
        insert_at += 1
    tree.body.insert(insert_at, import_node)

    transformer = _ProductionPatch()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)

    if transformer.retouch_replaced != 1:
        raise RuntimeError(
            f"Safety stop: expected one _openai_image_edit_bytes, found {transformer.retouch_replaced}"
        )
    if transformer.builder_hardened != 1:
        raise RuntimeError(
            f"Safety stop: expected one build_application builder, patched {transformer.builder_hardened}"
        )

    log.info(
        "V232 production patch active: guarded_retouch=%s telegram_builder=%s queue_notice=%s",
        transformer.retouch_replaced,
        transformer.builder_hardened,
        os.environ.get("QUEUE_PUBLIC_MAX_MIN", "30"),
    )
    return compile(tree, str(MAIN_PATH), "exec")


def main() -> None:
    code = _compile_patched_main()
    namespace = {
        "__name__": "__main__",
        "__file__": str(MAIN_PATH),
        "__package__": None,
        "__cached__": None,
    }
    exec(code, namespace, namespace)


if __name__ == "__main__":
    main()
