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
    """V232-style scene generation boundary.

    Gemini owns composition, wardrobe, lighting and the celebrity identity.  The
    user portrait is supplied only to produce a correctly sized, well-lit target
    head; the final user identity is applied later by the dedicated FaceSwap
    stage.  Reference order and labels are deliberately deterministic because
    identity assignment degraded when user and celebrity inputs were interleaved.
    """

    def __init__(self, transport: GeminiTransport, model: str):
        self.transport = transport
        self.model = model

    async def generate(
        self,
        *,
        prompt: str,
        character_references: list[bytes],
        user_face_reference: bytes,
        user_body_reference: bytes,
        scene_reference: bytes | None = None,
    ) -> bytes:
        if not 3 <= len(character_references) <= 6:
            raise ValueError("Gemini scene generation requires 3-6 character references")
        if not user_face_reference:
            raise ValueError("Gemini scene generation requires a user portrait reference")
        if not user_body_reference:
            raise ValueError("Gemini scene generation requires a user full-body reference")

        references: list[bytes] = []
        labels: list[str] = []

        # V232 used the uploaded location as the first authoritative visual input.
        if scene_reference:
            references.append(scene_reference)
            labels.append(
                "AUTHORITATIVE SCENE BASE: preserve location, camera viewpoint, perspective, lighting direction and major object placement. Ignore and do not copy any people in this reference."
            )

        # Keep all user anchors together and before the celebrity block.
        references.append(user_body_reference)
        labels.append(
            "PERSON A BODY REFERENCE: use only height, body mass, shoulder width, limb thickness and body proportions. Ignore clothes, pose, carried objects and background."
        )
        references.append(user_face_reference)
        labels.append(
            "PERSON A PORTRAIT: use only apparent age, head size, hairline and approximate target-face geometry so the later exact identity transfer has a clean frontal target. Do not beautify or rejuvenate."
        )

        # The celebrity is reconstructed only from this contiguous multi-reference set.
        for index, reference in enumerate(character_references, 1):
            references.append(reference)
            labels.append(
                f"PERSON B HERO PORTRAIT {index}: authoritative identity reference for the same selected celebrity. Use jointly with every other PERSON B portrait; never transfer these features to PERSON A."
            )

        return await self.transport.generate_image(
            prompt=prompt,
            references=references,
            reference_labels=labels,
            model=self.model,
        )
