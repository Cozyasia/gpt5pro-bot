from __future__ import annotations

from typing import Protocol


class GeminiTransport(Protocol):
    async def generate_image(
        self,
        *,
        prompt: str,
        references: list[bytes],
        model: str,
        reference_labels: list[str] | None = None,
    ) -> bytes: ...


class GeminiSceneProvider:
    """Direct Gemini API boundary with explicit legacy-style reference roles."""

    def __init__(self, transport: GeminiTransport, model: str):
        self.transport = transport
        self.model = model

    async def generate(
        self,
        *,
        prompt: str,
        character_references: list[bytes],
        user_body_reference: bytes,
        scene_reference: bytes | None = None,
    ) -> bytes:
        if not 3 <= len(character_references) <= 6:
            raise ValueError("Gemini scene generation requires 3-6 character references")
        if not user_body_reference:
            raise ValueError("Gemini scene generation requires a user full-body reference")

        references = list(character_references)
        labels = [
            f"CHARACTER REFERENCE {index + 1}: selected celebrity only; same identity as every other CHARACTER reference."
            for index in range(len(character_references))
        ]
        references.append(user_body_reference)
        labels.append(
            "USER BODY REFERENCE: use only height, build and body proportions. Ignore face, hair, clothes, pose, objects and background."
        )
        if scene_reference:
            references.append(scene_reference)
            labels.append(
                "SCENE REFERENCE: use only location, composition and atmosphere. Do not copy any person from this image."
            )
        return await self.transport.generate_image(
            prompt=prompt,
            references=references,
            reference_labels=labels,
            model=self.model,
        )
