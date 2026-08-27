# -*- coding: utf-8 -*-
"""Operational hardening for V263 model/cache/inference boundaries.

This module does not change V263 identity geometry or thresholds. It makes the two
ONNX assets safe for concurrent production use and provides a narrow V262 rollback
only when V263 infrastructure (model download/load/inference) is unavailable.
Identity-gate rejection is intentionally NOT downgraded to V262.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from neyrobot_prod import selfie_v262_landmark_field_compositor as v262
from neyrobot_prod import selfie_v263_dense_identity_lock as v263

_INSTALLED = False
_VERIFIED_MODELS: set[tuple[str, str]] = set()
_VERIFY_LOCK = asyncio.Lock()
_NET_INIT_LOCK = threading.RLock()
_PIPNET_INFER_LOCK = threading.RLock()
_MOBILEFACE_INFER_LOCK = threading.RLock()

_BASE_PIPNET_NET = v263._pipnet_net
_BASE_MOBILEFACE_NET = v263._mobileface_net
_BASE_DENSE = v263._dense_landmarks_68
_BASE_EMBED = v263._mobileface_embedding
_BASE_TRANSFER = v263._true_face_transfer_v263


class V263InfrastructureUnavailable(RuntimeError):
    """V263-only infrastructure failed; V262 may be used as availability rollback."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _ensure_verified_model(path: Path, url: str, digest: str, label: str) -> Path:
    """Verify/download once per process, with process-safe atomic replacement.

    Each process writes a PID-specific temporary file. Multiple Render workers may
    race to populate the shared path, but only complete checksum-verified files are
    atomically renamed into place, so readers never observe partial model bytes.
    After the first successful verification, the model is not re-hashed per request.
    """
    key = (str(path), str(digest))
    if key in _VERIFIED_MODELS and path.exists():
        return path

    async with _VERIFY_LOCK:
        if key in _VERIFIED_MODELS and path.exists():
            return path
        if path.exists():
            try:
                if _sha256_file(path) == digest:
                    _VERIFIED_MODELS.add(key)
                    return path
            except Exception:
                pass
            with contextlib.suppress(Exception):
                path.unlink()

        try:
            v241, *_ = v263._modules()
            runtime = v241._runtime()
            httpx_mod = getattr(runtime, "httpx", None) if runtime is not None else None
            if httpx_mod is None:
                import httpx as httpx_mod

            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.download")
            timeout = httpx_mod.Timeout(90.0, connect=25.0, read=90.0, write=30.0, pool=25.0)
            async with httpx_mod.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = bytes(response.content or b"")
            actual = hashlib.sha256(payload).hexdigest()
            if actual != digest:
                raise RuntimeError(f"{label} checksum mismatch: {actual}")
            tmp.write_bytes(payload)
            tmp.replace(path)
            _VERIFIED_MODELS.add(key)
            v263._log(
                "AI_SELFIE_V263_MODEL status=downloaded model=%s bytes=%s sha256=%s cache=verified process_safe=true",
                label, len(payload), actual[:16],
            )
            return path
        except Exception as exc:
            with contextlib.suppress(Exception):
                tmp = path.with_name(f"{path.name}.{os.getpid()}.download")
                tmp.unlink()
            raise V263InfrastructureUnavailable(f"{label} unavailable: {type(exc).__name__}: {exc}") from exc


def _pipnet_net(model_path: Path):
    with _NET_INIT_LOCK:
        try:
            return _BASE_PIPNET_NET(model_path)
        except Exception as exc:
            raise V263InfrastructureUnavailable(f"PIPNet load failed: {type(exc).__name__}: {exc}") from exc


def _mobileface_net(model_path: Path):
    with _NET_INIT_LOCK:
        try:
            return _BASE_MOBILEFACE_NET(model_path)
        except Exception as exc:
            raise V263InfrastructureUnavailable(f"MobileFace load failed: {type(exc).__name__}: {exc}") from exc


def _dense_landmarks_68(*args: Any, **kwargs: Any):
    with _PIPNET_INFER_LOCK:
        try:
            return _BASE_DENSE(*args, **kwargs)
        except V263InfrastructureUnavailable:
            raise
        except Exception as exc:
            # Face/sample validation remains a real input failure; only DNN/model
            # failures are availability failures eligible for V262 rollback.
            text = str(exc)
            infrastructure = (
                type(exc).__module__.startswith("cv2")
                or "PIPNet returned" in text
                or "PIPNet cls shape invalid" in text
            )
            if infrastructure:
                raise V263InfrastructureUnavailable(f"PIPNet inference failed: {type(exc).__name__}: {exc}") from exc
            raise


def _mobileface_embedding(*args: Any, **kwargs: Any):
    with _MOBILEFACE_INFER_LOCK:
        try:
            return _BASE_EMBED(*args, **kwargs)
        except V263InfrastructureUnavailable:
            raise
        except Exception as exc:
            text = str(exc)
            infrastructure = type(exc).__module__.startswith("cv2") or "MobileFace produced invalid embedding" in text
            if infrastructure:
                raise V263InfrastructureUnavailable(f"MobileFace inference failed: {type(exc).__name__}: {exc}") from exc
            raise


async def _true_face_transfer_v263_safe(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    try:
        return await _BASE_TRANSFER(runtime, stage1, source, source_photo_no)
    except V263InfrastructureUnavailable as exc:
        v263._log(
            "AI_SELFIE_V263_INFRA_FALLBACK status=fallback_v262 reason=%s:%s identity_gate_bypass=false rollback=v262",
            type(exc).__name__, str(exc)[:300],
        )
        runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v262_degraded_infrastructure"
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_v262_infrastructure_fallback"
        # Call the concrete V262 function directly. Do not invoke v262.enforce_runtime,
        # because V263 deliberately remains the installed owner for the next request.
        return await v262._true_face_transfer_v262(runtime, stage1, source, source_photo_no)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    v263._ensure_verified_model = _ensure_verified_model
    v263._MODEL_LOCK = _VERIFY_LOCK
    v263._pipnet_net = _pipnet_net
    v263._mobileface_net = _mobileface_net
    v263._dense_landmarks_68 = _dense_landmarks_68
    v263._mobileface_embedding = _mobileface_embedding
    v263._true_face_transfer_v263 = _true_face_transfer_v263_safe
    _INSTALLED = True
    v263._log(
        "AI_SELFIE_V263_RUNTIME_SAFETY status=ok model_cache=verified_once process_safe_atomic=true "
        "pipnet_inference=serialized mobileface_inference=serialized infra_rollback=v262 identity_reject_rollback=false"
    )


__all__ = ["install", "V263InfrastructureUnavailable"]
