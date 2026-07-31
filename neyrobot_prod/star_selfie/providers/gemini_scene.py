from __future__ import annotations

from typing import Protocol


class GeminiTransport(Protocol):
    async def generate_image(self, *, prompt: str, references: list[bytes], model: str) -> bytes: ...


class GeminiSceneProvider:
    """Direct Gemini API boundary for scene and character rendering."""

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
        references = [*character_references, user_body_reference]
        if scene_reference:
            references.append(scene_reference)
        return await self.transport.generate_image(
            prompt=prompt,
            references=references,
            model=self.model,
        )
