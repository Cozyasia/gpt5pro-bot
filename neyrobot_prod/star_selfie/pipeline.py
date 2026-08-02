from __future__ import annotations

import asyncio

from .models import GenerationRequest, GenerationResult
from .prompts.scene import build_scene_prompt
from .qc import BasicImageQC
from .storage import StarSelfieStorage


class StarSelfiePipeline:
    """V232 scene generation followed by one isolated user identity transfer.

    Gemini creates the complete scene and the selected celebrity from the legacy
    multi-reference set.  Only after that image is accepted does the dedicated
    FaceSwap provider replace PERSON A.  The FaceSwap output is terminal: it is
    never sent back through Gemini, which prevents redraw, rejuvenation and loss
    of celebrity identity.
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
        self.max_attempts = max(2, max_attempts)
        self.face_swap_attempts = max(2, face_swap_attempts)
        self.qc = qc or BasicImageQC()

    async def _transfer_user_face(
        self,
        *,
        source_face: bytes,
        target_scene: bytes,
    ) -> tuple[bytes, int]:
        """Replace PERSON A only; never alter or re-generate PERSON B."""
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
                    raise RuntimeError(
                        f"QC rejected user identity transfer: {candidate_qc.reason}"
                    )
                return candidate, attempt
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt < self.face_swap_attempts:
                    await asyncio.sleep(min(2.5 * attempt, 8.0))
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

        prompt = build_scene_prompt(
            request.character.title,
            request.scene,
            request.capture_mode,
        )
        character_refs = [path.read_bytes() for path in request.character.reference_paths]
        user_body_reference = request.user_body_path.read_bytes()
        user_face = request.user_face_path.read_bytes()
        scene_reference = (
            request.scene_reference_path.read_bytes()
            if request.scene_reference_path is not None
            else None
        )
        failures: list[str] = []

        for generation_attempt in range(1, self.max_attempts + 1):
            try:
                # V232-quality scene pass. The portrait is only a construction
                # anchor here; the exact user identity is applied afterwards.
                base_scene = await self.scene_provider.generate(
                    prompt=prompt,
                    character_references=character_refs,
                    user_face_reference=user_face,
                    user_body_reference=user_body_reference,
                    scene_reference=scene_reference,
                )
                scene_qc = self.qc.validate(base_scene)
                if not scene_qc.accepted:
                    raise RuntimeError(f"base scene QC rejected: {scene_qc.reason}")

                # Terminal isolated stage. Do not pass this result back to Gemini.
                final, user_swap_attempt = await self._transfer_user_face(
                    source_face=user_face,
                    target_scene=base_scene,
                )
                final_qc = self.qc.validate(final)
                if not final_qc.accepted:
                    raise RuntimeError(f"final image QC rejected: {final_qc.reason}")

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
                        "generation_attempt": generation_attempt,
                        "architecture": "v232_scene_plus_terminal_user_only_face_swap",
                        "identity_assignment": "left_user_right_celebrity",
                        "celebrity_generated_from_all_catalog_references": True,
                        "celebrity_face_swap_disabled": True,
                        "user_portrait_used_as_scene_anchor": True,
                        "user_body_reference": True,
                        "user_identity_transfer": True,
                        "user_target_face_index": 0,
                        "user_swap_attempt": user_swap_attempt,
                        "post_swap_gemini_pass": False,
                        "custom_scene_photo": request.scene_reference_path is not None,
                    },
                )
            except Exception as exc:
                failures.append(
                    f"generation {generation_attempt}: {type(exc).__name__}: {exc}"
                )
                if generation_attempt < self.max_attempts:
                    await asyncio.sleep(min(3.0 * generation_attempt, 8.0))
                    continue

        raise RuntimeError(
            f"Star Selfie failed after {self.max_attempts} complete attempts: "
            + " | ".join(failures[-self.max_attempts :])
        )
