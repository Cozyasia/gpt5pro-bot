#!/usr/bin/env python3
"""Build a secret-safe, fail-closed inventory of the NEYRONIX product surface."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Capability:
    capability_id: str
    name: str
    entry: str
    handler: str
    provider: str
    env_any_groups: tuple[tuple[str, ...], ...]
    billing: str
    evidence: tuple[str, ...]
    limitation: str = "Requires an authenticated Telegram user and provider quota."


def _c(
    capability_id: str,
    name: str,
    entry: str,
    handler: str,
    provider: str,
    env: Sequence[Sequence[str]],
    billing: str,
    evidence: Sequence[str],
    limitation: str = "Requires an authenticated Telegram user and provider quota.",
) -> Capability:
    return Capability(
        capability_id, name, entry, handler, provider,
        tuple(tuple(group) for group in env), billing, tuple(evidence), limitation,
    )


CAPABILITIES: tuple[Capability, ...] = (
    _c("text_chat", "AI chat", "Text message / assistant card", "on_text", "OpenAI",
       (("OPENAI_API_KEY",),), "Subscription/limits; no charge before provider acceptance",
       ("OPENAI_API_KEY", "on_text", "OPENAI_MODEL")),
    _c("documents_pdf_docx", "PDF/DOCX analysis", "Send document", "on_document", "OpenAI",
       (("OPENAI_API_KEY",),), "Chat limits", ("filters.Document.ALL", "on_document", "python-docx")),
    _c("image_analysis", "Image analysis", "Send photo in chat", "on_photo", "OpenAI",
       (("OPENAI_API_KEY",),), "Chat limits", ("filters.PHOTO", "on_photo", "image_url")),
    _c("speech_to_text", "Speech recognition", "Voice/audio message", "on_voice", "OpenAI",
       (("OPENAI_STT_KEY", "OPENAI_API_KEY"),), "Chat limits",
       ("OPENAI_STT_MODEL", "filters.VOICE | filters.AUDIO", "transcriptions")),
    _c("text_to_speech", "Speech synthesis", "/voice_on", "_tts_synthesize", "OpenAI",
       (("OPENAI_TTS_KEY", "OPENAI_API_KEY"),), "Chat limits",
       ("OPENAI_TTS_MODEL", "cmd_voice_on", "audio/speech")),
    _c("live_search", "Live information search", "Question requiring fresh data", "live_search", "Tavily",
       (("TAVILY_API_KEY",),), "Chat limits", ("TAVILY_API_KEY", "cmd_test_live_search", "live_search")),
    _c("dialog_history", "Dialog history", "/chats and /newchat", "cmd_chats/cmd_newchat", "SQLite",
       (), "Included", ("cmd_chats", "cmd_newchat", "ai_chats"),
       "History is account-bound; Telegram messages themselves are not portable between bots."),
    _c("model_selection", "Model selection", "AI engines menu", "cmd_engines", "OpenAI",
       (("OPENAI_API_KEY",),), "Plan-dependent", ("cmd_engines", "OPENAI_MODEL", "engine:")),
    _c("image_generation", "Text-to-image", "Images card / /img", "cmd_img", "OpenAI",
       (("OPENAI_IMAGE_KEY", "OPENAI_API_KEY"),), "Quoted credits", ("cmd_img", "OPENAI_IMAGE_MODEL", "images/generations")),
    _c("image_edit_reference", "Reference image editing", "Photo workflow", "on_photo", "OpenAI",
       (("OPENAI_IMAGE_KEY", "OPENAI_API_KEY"),), "Quoted credits", ("images/edits", "OPENAI_IMAGE_KEY", "reference")),
    _c("image_midjourney", "Styled/ad imagery", "/midjourney", "cmd_midjourney", "CometAPI",
       (("COMET_API_KEY", "COMETAPI_KEY"),), "Quoted credits", ("cmd_midjourney", "COMET_IMAGE_GEN_PATH", "MIDJOURNEY_ENABLED")),
    _c("celebrity_selfie", "Selfie with celebrity", "AI selfie card", "celebrity_selfie", "Google Gemini",
       (("GEMINI_IMAGE_API_KEY",),), "Reserved credits; protected delivery",
       ("GEMINI_IMAGE_API_KEY", "celebrity_selfie", "AI_SELFIE_V265_ENFORCE"),
       "Subject to provider safety policy; direct Google key is required by the authoritative route."),
    _c("video_text_to_video", "Text-to-video", "Video card", "_route_selected_text_video", "Kling AI",
       (("KLING_API_KEY", "COMET_API_KEY"),), "Duration-based quoted credits",
       ("_route_selected_text_video", "KLING_TEXT_CREATE_PATH", "text2video")),
    _c("video_image_to_video", "Image-to-video", "Upload photo in video mode", "_create_and_poll_i2v", "Runway",
       (("RUNWAYML_API_SECRET", "RUNWAY_API_KEY", "RUNWAY_KEY", "COMET_API_KEY"),), "Duration-based quoted credits",
       ("_create_and_poll_i2v", "RUNWAY_IMAGE2VIDEO_ENABLED", "RUNWAY_API_KEY")),
    _c("video_multi_photo", "Multi-photo video", "Neuroproduction / music-video", "singing_clip_pipeline", "Seedance",
       (("COMET_API_KEY",),), "Scene/duration quote", ("singing_clip_pipeline", "SEEDANCE_MODEL", "reference_images")),
    _c("video_advertising", "Advertising video", "Advertising card", "handle_production_brief", "Google Veo",
       (("COMET_API_KEY",),), "Scene/duration quote", ("handle_production_brief", "submit_veo_task", "VEO_FAST_MODEL")),
    _c("video_property", "Real-estate video", "Realty card", "real_estate_video", "Google Veo",
       (("COMET_API_KEY",),), "Idempotent reservation/commit", ("real_estate_video", "property_video_billing", "submit_veo_task")),
    _c("video_reels_shorts", "Reels / Shorts", "Video formats", "on_cb_fun", "Kling AI",
       (("KLING_API_KEY", "COMET_API_KEY"),), "Duration-based quoted credits", ("on_cb_fun", "9:16", "KLING_MODEL")),
    _c("video_lipsync", "Lip-sync", "Presenter/vocal clip", "_kling_lipsync", "Kling AI",
       (("KLING_API_KEY", "COMET_API_KEY"),), "Per-segment quote", ("KLING_LIPSYNC_ENABLED", "lipsync", "KLING_LIPSYNC")),
    _c("video_voiceover", "Video voiceover", "Presenter/video flow", "_tts_synthesize", "OpenAI",
       (("OPENAI_TTS_KEY", "OPENAI_API_KEY"),), "Included in job quote", ("VEO_24S_TTS_COST_PER_MINUTE_USD", "_tts_synthesize", "voice")),
    _c("video_multiscene", "Multi-scene video", "Director/video flow", "veo_resumable_pipeline", "Google Veo",
       (("COMET_API_KEY",),), "Scene quote; resumable journal", ("veo_resumable_pipeline", "veo_multiscene", "VEO_JOBS_DIR")),
    _c("video_heygen", "Talking avatar", "/heygen", "cmd_heygen", "HeyGen",
       (("HEYGEN_API_KEY",), ("HEYGEN_AVATAR_ID",), ("HEYGEN_VOICE_ID",)), "Provider job quote",
       ("cmd_heygen", "HEYGEN_API_KEY", "heygen_talking_avatar")),
    _c("video_luma", "Luma image-to-video", "Video provider fallback", "_create_and_poll_i2v", "Luma",
       (("LUMA_API_KEY",),), "Provider quote", ("LUMA_API_KEY", "LUMA_STATUS_PATH", "Luma image")),
    _c("music_generation", "Music and vocals", "/music", "on_cb_suno", "Suno",
       (("SUNO_API_KEY", "COMET_API_KEY"),), "Quoted credits", ("cmd_music", "on_cb_suno", "SUNO_CREATE_PATH")),
    _c("neuroproduction", "Commercial neuroproduction", "Neuroproduction/advertising", "handle_production_brief", "Multi-provider",
       (("COMET_API_KEY",),), "Brief then explicit quote/confirmation",
       ("handle_production_brief", "ent:brief:", "production_events")),
    _c("marketplace", "Marketplace product cards", "Marketplace card", "marketplace_pipeline", "OpenAI",
       (("OPENAI_IMAGE_KEY", "OPENAI_API_KEY"),), "USD quote mapped to idempotent credit ledger",
       ("marketplace_pipeline", "SQLiteUSDWalletLedger", "MARKETPLACE_PAID_GENERATION_ENABLED")),
    _c("payments_yookassa", "YooKassa payments", "Plans/balance", "on_successful_payment", "YooKassa",
       (("YOOKASSA_PROVIDER_TOKEN", "PROVIDER_TOKEN_YOOKASSA"),), "Telegram payment receipt; idempotent transaction",
       ("PreCheckoutQueryHandler", "on_successful_payment", "YOOKASSA_PROVIDER_TOKEN")),
    _c("payments_cryptobot", "CryptoBot top-up", "Plans/balance", "crypto_create_invoice", "CryptoBot",
       (("CRYPTO_PAY_API_TOKEN",),), "Invoice reconciliation", ("CRYPTO_PAY_API_TOKEN", "createInvoice", "getInvoices")),
)


@dataclass(frozen=True)
class LiveProviderTestGate:
    budget_usd: float

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "LiveProviderTestGate":
        if str(environ.get("NEYRONIX_ALLOW_LIVE_PROVIDER_TESTS", "")).lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("NEYRONIX_ALLOW_LIVE_PROVIDER_TESTS=1 is required")
        try:
            budget = float(environ.get("NEYRONIX_LIVE_TEST_BUDGET_USD", "0"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("live provider test budget must be positive") from exc
        if budget <= 0:
            raise RuntimeError("live provider test budget must be positive")
        return cls(budget_usd=budget)


def _read_python_sources(root: Path) -> str:
    chunks: list[str] = []
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "__pycache__", "tests"} for part in path.parts):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _configured(capability: Capability, environ: Mapping[str, str]) -> tuple[bool, list[dict[str, object]]]:
    groups: list[dict[str, object]] = []
    for alternatives in capability.env_any_groups:
        present = [name for name in alternatives if bool(str(environ.get(name, "")).strip())]
        groups.append({"any_of": list(alternatives), "present": present, "ready": bool(present)})
    return all(group["ready"] for group in groups), groups


def audit_capabilities(root: Path, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    environ = os.environ if environ is None else environ
    source = _read_python_sources(Path(root))
    env_names = sorted({name for item in CAPABILITIES for group in item.env_any_groups for name in group})
    rows: list[dict[str, object]] = []
    for item in CAPABILITIES:
        missing = [token for token in item.evidence if token not in source]
        ready, groups = _configured(item, environ)
        rows.append({
            "id": item.capability_id,
            "name": item.name,
            "entry": item.entry,
            "handler": item.handler,
            "provider": item.provider,
            "billing": item.billing,
            "code_status": "integrated" if not missing else "missing_evidence",
            "missing_evidence": missing,
            "configuration": {"ready": ready, "requirements": groups},
            "live_test": {"status": "not_run", "reason": "explicit paid-test budget not authorized"},
            "limitations": item.limitation,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Source evidence and secret presence are not proof of a working provider API.",
        "environment": {name: bool(str(environ.get(name, "")).strip()) for name in env_names},
        "capabilities": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(audit_capabilities(args.root), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
