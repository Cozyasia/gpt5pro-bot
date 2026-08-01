from __future__ import annotations

import asyncio

from .models import GenerationRequest, GenerationResult
from .prompts.scene import build_scene_prompt
from .qc import BasicImageQC
from .storage import StarSelfieStorage


class StarSelfiePipeline:
    """Legacy identity-first scene generation plus isolated user face transfer.

    The scene model owns the celebrity identity exactly as in the pre-rewrite
    multi-reference architecture. Face Swap is applied only to the user on the
    left, so the provider cannot redraw or degrade the celebrity.
    """

    def __init__(
        self,
        scene_provider,
        face_swap_provider,
        storage: StarSelfieStorage,
        *,
        max_attempts: int = 2,
        face_swap_attempts: int = 3,
        qc: BasicImageQC | None = None,
    ):
        self.scene_provider = scene_provider
        self.face_swap_provider = face_swap_provider
        self.storage = storage
        self.max_attempts = max(1, max_attempts)
        self.face_swap_attempts = max(1, face_swap_attempts)
        self.qc = qc or BasicImageQC()

    async def _transfer_user_face(
        self,
        *,
        source_face: bytes,
        target_scene: bytes,
    ) -> tuple[bytes, int]:
        errors: list[str] = []
        for attempt in range(1, self.face_swap_attempts + 1):
            try:
                candidate = await self.face_swap_provider.swap_face(
                    source_face=source_face,
                    target_scene=target_scene,
                    target_face_index=0,
                )
                if not candidate:
                    raise RuntimeError("provider returned an empty image")
                if candidate == target_scene:
                    raise RuntimeError("provider returned the unchanged image")
                candidate_qc = self.qc.validate(candidate)
                if not candidate_qc.accepted:
                    raise RuntimeError(f"QC rejected user identity transfer: {candidate_qc.reason}")
                return candidate, attempt
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt < self.face_swap_attempts:
                    await asyncio.sleep(min(2.0 * attempt, 6.0))
        raise RuntimeError(
            f"User identity transfer failed after {self.face_swap_attempts} attempts: "
            + " | ".join(errors[-self.face_swap_attempts :])
        )

    async def run(self, request: GenerationRequest) -> GenerationResult:
        if not request.user_face_path.is_file():
            raise FileNotFoundError(request.user_face_path)
        if not request.user_body_path.is_file():
            raise FileNotFoundError(request.user_body_path)
        if not 3 <= len(request.character.reference_paths) <= 6:
            raise ValueError("Character must have 3-6 reference images")
        if request.scene_reference_path is not None and not request.scene_reference_path.is_file():
            raise FileNotFoundError(request.scene_reference_path)

        prompt = build_scene_prompt(request.character.title, request.scene, request.capture_mode)
        character_refs = [path.read_bytes() for path in request.character.reference_paths]
        user_body_reference = request.user_body_path.read_bytes()
        user_face = request.user_face_path.read_bytes()
        scene_reference = (
            request.scene_reference_path.read_bytes()
            if request.scene_reference_path is not None
            else None
        )
        last_reason = "generation_failed"

        for attempt in range(1, self.max_attempts + 1):
            try:
                base_scene = await self.scene_provider.generate(
                    prompt=prompt,
                    character_references=character_refs,
                    user_body_reference=user_body_reference,
                    scene_reference=scene_reference,
                )
            except Exception as exc:
                last_reason = f"legacy_scene_{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    await asyncio.sleep(min(2.0 * attempt, 5.0))
                    continue
                raise RuntimeError(
                    f"Legacy Star Selfie scene generation failed: {type(exc).__name__}: {exc}"
                ) from exc

            scene_qc = self.qc.validate(base_scene)
            if not scene_qc.accepted:
                last_reason = f"scene_{scene_qc.reason}"
                continue

            try:
                final, user_swap_attempt = await self._transfer_user_face(
                    source_face=user_face,
                    target_scene=base_scene,
                )
            except Exception as exc:
                last_reason = f"user_identity_{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    await asyncio.sleep(min(2.0 * attempt, 5.0))
                    continue
                raise RuntimeError(
                    f"Star Selfie user face transfer failed: {type(exc).__name__}: {exc}"
                ) from exc

            final_qc = self.qc.validate(final)
            if not final_qc.accepted:
                last_reason = f"final_{final_qc.reason}"
                continue

            scene_path, final_path = self.storage.save_generation(
                user_id=request.user_id,
                scene=base_scene,
                final=final,
            )
            return GenerationResult(
                scene_image_path=scene_path,
                final_image_path=final_path,
                capture_mode=request.capture_mode,
                scene_provider=type(self.scene_provider).__name__,
                face_swap_provider=type(self.face_swap_provider).__name__,
                metadata={
                    "character": request.character.slug,
                    "aspect_ratio": request.aspect_ratio,
                    "attempt": attempt,
                    "architecture": "legacy_multireference_hero_plus_user_only_face_transfer",
                    "identity_assignment": "left_user_right_celebrity",
                    "celebrity_generated_from_all_catalog_references": True,
                    "celebrity_face_swap_disabled": True,
                    "user_identity_transfer": True,
                    "user_swap_attempt": user_swap_attempt,
                    "custom_scene_photo": request.scene_reference_path is not None,
                    "user_body_reference": True,
                },
            )

        raise RuntimeError(f"Star Selfie failed after {self.max_attempts} attempts: {last_reason}")
