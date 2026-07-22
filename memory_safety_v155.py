# -*- coding: utf-8 -*-
"""Render web-process memory hardening for the v154 selfie pipeline.

The Telegram web service must remain responsive and must not load an ONNX
segmentation model in-process. Local rembg is therefore opt-in only and is
reserved for a separately sized media worker. This module also serializes the
most memory-intensive selfie pipeline and rejects new work before Render's hard
memory limit is reached.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v154 as v154

VERSION = "v155-render-memory-hardening-2026-07-22"
_INSTALL_FLAG = "_memory_safety_v155_installed"

log = logging.getLogger("gpt-bot.memory")
_ORIGINAL_LOCAL_REMBG = v154._local_rembg_cutout
_ORIGINAL_RUN_V154 = v154._run_v154_generation
_GENERATION_GATE: asyncio.Semaphore | None = None


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _rss_mb() -> float:
    """Return current resident memory on Linux without adding psutil."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _local_rembg_allowed() -> bool:
    """Require an explicit three-part opt-in for in-process ONNX inference."""
    return (
        not _flag("BG_DISABLE_LOCAL_REMBG", True)
        and _flag("LOCAL_REMBG_ENABLED", False)
        and _flag("CELEBRITY_V142_LOCAL_REMBG_FALLBACK", False)
    )


def _generation_gate() -> asyncio.Semaphore:
    global _GENERATION_GATE
    if _GENERATION_GATE is None:
        concurrency = _integer("CELEBRITY_V154_MAX_CONCURRENCY", 1, 1, 4)
        _GENERATION_GATE = asyncio.Semaphore(concurrency)
    return _GENERATION_GATE


async def _local_rembg_cutout(raw: bytes) -> bytes:
    if not _local_rembg_allowed():
        raise RuntimeError(
            "local rembg is disabled in the web service; use PhotoRoom or an isolated media worker"
        )
    return await _ORIGINAL_LOCAL_REMBG(raw)


async def _run_v154_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    async with _generation_gate():
        rss_before = _rss_mb()
        soft_limit_mb = _integer("MEMORY_SOFT_LIMIT_MB", 0, 0, 65536)
        if soft_limit_mb and rss_before >= soft_limit_mb:
            raise v139.PipelineError(
                "capacity",
                (
                    "The media service is temporarily at its safe memory limit. "
                    "Please retry shortly; the request was rejected before an unsafe restart."
                ),
            )

        log.info(
            "memory_guard start pipeline=v154 rss_mb=%.1f soft_limit_mb=%s",
            rss_before,
            soft_limit_mb or "off",
        )
        try:
            return await _ORIGINAL_RUN_V154(
                mod,
                user_photo,
                celebrity_refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=additional_user_refs,
            )
        finally:
            gc.collect()
            log.info(
                "memory_guard finish pipeline=v154 rss_mb=%.1f",
                _rss_mb(),
            )


def install() -> None:
    if getattr(v154, _INSTALL_FLAG, False):
        return

    # Global production policy wins over historical overlay defaults. The old
    # v154 code used setdefault(..., "1"), which silently re-enabled ONNX even
    # when render.yaml disabled it under different variable names.
    if not _local_rembg_allowed():
        os.environ["CELEBRITY_V142_LOCAL_REMBG_FALLBACK"] = "0"
        os.environ["CELEBRITY_V143_CUTOUT_PROVIDERS"] = "photoroom"

    v154._local_rembg_cutout = _local_rembg_cutout
    v142._local_rembg_cutout = _local_rembg_cutout
    v154._run_v154_generation = _run_v154_generation
    v139.selfie._run_v154_generation = _run_v154_generation

    setattr(v154, _INSTALL_FLAG, True)
    log.info(
        "memory_guard installed version=%s local_rembg=%s providers=%s concurrency=%s rss_mb=%.1f",
        VERSION,
        "enabled" if _local_rembg_allowed() else "disabled",
        os.environ.get("CELEBRITY_V143_CUTOUT_PROVIDERS", "photoroom"),
        _integer("CELEBRITY_V154_MAX_CONCURRENCY", 1, 1, 4),
        _rss_mb(),
    )


def install_early() -> None:
    install()


__all__ = [
    "VERSION",
    "install",
    "install_early",
    "_rss_mb",
    "_local_rembg_allowed",
    "_local_rembg_cutout",
    "_run_v154_generation",
]
