from __future__ import annotations

import asyncio

from .models import GenerationRequest, GenerationResult
from .prompts.scene import build_scene_prompt
from .qc import BasicImageQC
from .storage import StarSelfieStorage


def _select_best_face_reference(references: list[bytes]) -> bytes:
    """Choose the catalogue image with the largest clear frontal face."""
    if not references:
        raise ValueError("Celebrity reference list is empty")
    best = references[0]
    best_score = -1.0
    try:
        import cv2
        import numpy as np

        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        for reference in references:
            image = cv2.imdecode(np.frombuffer(reference, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=1.07,
                minNeighbors=5,
                minSize=(80, 80),
            )
            if len(faces) == 0:
                continue
            _, _, width, height = max(
                faces, key=lambda item: int(item[2]) * int(item[3])
            )
            area_ratio = (float(width) * float(height)) / max(
                1.0, float(image.shape[0] * image.shape[1])
            )
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            score = area_ratio * 1000.0 + min(sharpness, 1000.0) / 1000.0
            if score > best_score:
                best_score = score
                best = reference
    except Exception:
        pass
    return best


class StarSelfiePipeline:
    """Generate the scene first, then lock celebrity and user identities separately.

    Gemini owns composition, wardrobe, body proportions and lighting. The external
    face provider is used in two isolated passes: celebrity on image-right first,
    user on image-left second. This is the stable pre-rewrite behaviour and avoids
    asking one generative pass to invent both identities.
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

    async def _swap_with_retries(
        self,
        *,
        label: str,
        source_face: bytes,
        target_scene: bytes,
        target_face_index: int,
    ) -> tuple[bytes, int]:
        errors: list[str] = []
        for attempt in range(1, self.face_swap_attempts + 1):
            try:
                candidate = await self.face_swap_provider.swap_face(
                    source_face=source_face,
                    target_scene=target_scene,
                    target_face_index=target_face_index,
                )
                if not candidate:
                    raise RuntimeError("provider returned an empty image")
                if candidate == target_scene:
                    raise RuntimeError("provider returned the unchanged image")
                candidate_qc = self.qc.validate(candidate)
                if not candidate_qc.accepted:
                    raise RuntimeError(
                        f"QC rejected {label} identity transfer: {candidate_qc.reason}"
                    )
                return candidate, attempt
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt < self.face_swap_attempts:
                    await asyncio.sleep(min(2.5 * attempt, 8.0))
        raise RuntimeError(
            f"{label} identity transfer failed after {self.face_swap_attempts} attempts: "
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
        celebrity_face = _select_best_face_reference(character_refs)
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
                base_scene = await self.scene_provider.generate(
                    prompt=prompt,
                    character_references=character_refs,
                    user_body_reference=user_body_reference,
                    scene_reference=scene_reference,
                )
                scene_qc = self.qc.validate(base_scene)
                if not scene_qc.accepted:
                    raise RuntimeError(f"base scene QC rejected: {scene_qc.reason}")

                celebrity_locked, celebrity_swap_attempt = await self._swap_with_retries(
                    label="celebrity",
                    source_face=celebrity_face,
                    target_scene=base_scene,
                    target_face_index=1,
                )
                final, user_swap_attempt = await self._swap_with_retries(
                    label="user",
                    source_face=user_face,
                    target_scene=celebrity_locked,
                    target_face_index=0,
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
                        "architecture": "legacy_scene_plus_separate_celebrity_and_user_identity_lock",
                        "identity_assignment": "left_user_right_celebrity",
                        "celebrity_identity_transfer": True,
                        "celebrity_swap_attempt": celebrity_swap_attempt,
                        "user_identity_transfer": True,
                        "user_swap_attempt": user_swap_attempt,
                        "custom_scene_photo": request.scene_reference_path is not None,
                        "user_body_reference": True,
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
