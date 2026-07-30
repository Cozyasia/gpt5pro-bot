from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QCResult:
    accepted: bool
    reason: str = ""


class BasicImageQC:
    """Cheap transport-level guard before later vision QC.

    It rejects empty, truncated, HTML and JSON error bodies so failed provider
    responses are never persisted or returned to Telegram as images.
    """

    min_bytes: int = 10_000

    def validate(self, image: bytes) -> QCResult:
        if len(image) < self.min_bytes:
            return QCResult(False, "image_too_small")
        prefix = image[:32].lstrip().lower()
        if prefix.startswith((b"<html", b"<!doctype", b"{", b"[")):
            return QCResult(False, "non_image_payload")
        if image.startswith(b"\xff\xd8\xff"):
            return QCResult(True)
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            return QCResult(True)
        if image.startswith(b"RIFF") and b"WEBP" in image[:16]:
            return QCResult(True)
        return QCResult(False, "unsupported_image_format")
