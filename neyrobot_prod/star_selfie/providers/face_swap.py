from __future__ import annotations

from typing import Protocol


class FaceSwapTransport(Protocol):
    async def swap(
        self,
        *,
        source_face: bytes,
        target_scene: bytes,
        target_face_index: int = 0,
    ) -> bytes: ...


class FaceSwapProvider:
    """Dedicated identity-transfer stage with explicit target-face selection."""

    def __init__(self, transport: FaceSwapTransport):
        self.transport = transport

    async def swap_face(
        self,
        *,
        source_face: bytes,
        target_scene: bytes,
        target_face_index: int,
    ) -> bytes:
        if not source_face or not target_scene:
            raise ValueError("Face swap requires both source face and target scene")
        if target_face_index < 0:
            raise ValueError("target_face_index must be non-negative")
        return await self.transport.swap(
            source_face=source_face,
            target_scene=target_scene,
            target_face_index=target_face_index,
        )

    async def swap_user_face(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        return await self.swap_face(
            source_face=source_face,
            target_scene=target_scene,
            target_face_index=0,
        )

    async def swap_character_face(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        return await self.swap_face(
            source_face=source_face,
            target_scene=target_scene,
            target_face_index=1,
        )
