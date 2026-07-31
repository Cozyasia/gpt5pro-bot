from __future__ import annotations

from .config import StarSelfieConfig
from .pipeline import StarSelfiePipeline
from .providers.face_swap import FaceSwapProvider
from .providers.gemini_scene import GeminiSceneProvider
from .providers.http import (
    GeminiRESTTransport,
    GenericFaceSwapRESTTransport,
    SegmindFaceSwapRESTTransport,
)
from .storage import StarSelfieStorage


def build_pipeline(config: StarSelfieConfig) -> StarSelfiePipeline:
    """Build the production pipeline without importing Telegram or main.py."""
    config.validate_runtime()

    scene_transport = GeminiRESTTransport(
        api_key=config.gemini_api_key,
        timeout_s=config.request_timeout_s,
        api_base=config.gemini_api_base,
    )
    if config.face_swap_provider == "segmind":
        face_swap_transport = SegmindFaceSwapRESTTransport(
            endpoint=config.face_swap_url,
            api_key=config.face_swap_api_key,
            timeout_s=config.face_swap_timeout_s,
            face_restore=config.segmind_face_restore,
        )
    elif config.face_swap_provider == "generic_rest":
        face_swap_transport = GenericFaceSwapRESTTransport(
            endpoint=config.face_swap_url,
            api_key=config.face_swap_api_key,
            timeout_s=config.face_swap_timeout_s,
            result_path=config.face_swap_result_path,
            auth_header=config.face_swap_auth_header,
            auth_scheme=config.face_swap_auth_scheme,
        )
    else:
        raise ValueError(f"Unsupported Face Swap provider: {config.face_swap_provider}")

    return StarSelfiePipeline(
        scene_provider=GeminiSceneProvider(scene_transport, config.gemini_model),
        face_swap_provider=FaceSwapProvider(face_swap_transport),
        storage=StarSelfieStorage(config.persistent_root),
        max_attempts=config.max_generation_attempts,
        face_swap_attempts=config.face_swap_attempts,
    )
