"""Provider-neutral Seedance 2.5 reference-video request planning.

Reference audio is supported by some Seedance 2.5 API providers, but this
module does not assume CometAPI's /v1/videos accepts it. No network requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SeedanceReferenceRequest:
    model: str
    prompt: str
    image_urls: tuple[str, ...]
    audio_urls: tuple[str, ...]
    duration: int
    aspect_ratio: str = "9:16"

    def __post_init__(self) -> None:
        if not 4 <= self.duration <= 30:
            raise ValueError("Seedance 2.5 duration must be 4-30 seconds")
        if len(self.image_urls) != 1 or len(self.audio_urls) != 1:
            raise ValueError("singing clip requires one portrait and one Suno excerpt")
        for url in (*self.image_urls, *self.audio_urls):
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("reference URLs must be public HTTPS assets")
        if self.aspect_ratio not in ("9:16", "16:9", "1:1"):
            raise ValueError("unsupported aspect ratio")


def build_seedance_reference_request(
    *, portrait_url: str, suno_excerpt_url: str, duration: int,
    model: str = "seedance-2.5-reference-to-video",
) -> SeedanceReferenceRequest:
    return SeedanceReferenceRequest(
        model=model,
        prompt=(
            "@image1 is the singer. Animate natural, precise mouth movements "
            "synchronized to the Russian vocals in @audio1. Maintain facial "
            "identity and realistic expression; cinematic vertical framing. "
            "Do not add subtitles, on-screen text, or replacement lyrics."
        ),
        image_urls=(portrait_url,),
        audio_urls=(suno_excerpt_url,),
        duration=duration,
    )


def to_reference_api_payload(request: SeedanceReferenceRequest) -> dict:
    """Provider adapter for APIs explicitly documenting image_urls/audio_urls.

    Do not send this payload to CometAPI /v1/videos without verifying that
    endpoint's audio reference contract.
    """
    return {
        "model": request.model,
        "prompt": request.prompt,
        "image_urls": list(request.image_urls),
        "audio_urls": list(request.audio_urls),
        "duration": request.duration,
        "aspect_ratio": request.aspect_ratio,
        "generate_audio": False,
    }
