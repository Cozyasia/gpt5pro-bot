from __future__ import annotations

from typing import Protocol


class FaceSwapTransport(Protocol):
    async def swap(self, *, source_face: bytes, target_scene: bytes) -> bytes: ...


class FaceSwapProvider:
    """Dedicated identity-transfer stage for the user's face only."""

    def __init__(self, transport: FaceSwapTransport):
        self.transport = transport

    async def swap_user_face(self, *, source_face: bytes, target_scene: bytes) -> bytes:
        if not source_face or not target_scene:
            raise ValueError("Face swap requires both source face and target scene")
        return await self.transport.swap(source_face=source_face, target_scene=target_scene)
