from __future__ import annotations

import asyncio
from io import BytesIO

from .models import GenerationRequest, GenerationResult
from .prompts.scene import build_scene_prompt
from .qc import BasicImageQC
from .storage import StarSelfieStorage


def _decode_cv_image(data: bytes):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def _face_candidates(data: bytes):
    """Return frontal faces with quality metadata used for reference ranking."""
    import cv2

    image = _decode_cv_image(data)
    if image is None:
        return image, []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=6, minSize=(80, 80))
    candidates = []
    image_area = max(1.0, float(image.shape[0] * image.shape[1]))
    for x, y, width, height in faces:
        roi = gray[y : y + height, x : x + width]
        if roi.size == 0:
            continue
        area_ratio = (float(width) * float(height)) / image_area
        sharpness = float(cv2.Laplacian(roi, cv2.CV_64F).var())
        brightness = float(roi.mean())
        exposure_score = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)
        center_x = x + width / 2.0
        center_y = y + height / 2.0
        center_distance = abs(center_x - image.shape[1] / 2.0) / max(1.0, image.shape[1])
        center_distance += abs(center_y - image.shape[0] / 2.0) / max(1.0, image.shape[0])
        score = area_ratio * 120.0 + min(sharpness, 1200.0) / 1200.0 * 4.0 + exposure_score * 2.0
        score -= center_distance * 0.5
        candidates.append((score, (int(x), int(y), int(width), int(height))))
    return image, candidates


def _select_best_face_reference(references: list[bytes]) -> bytes:
    """Prefer a large, sharp, evenly exposed frontal celebrity face."""
    best = references[0]
    best_score = -1.0
    try:
        for reference in references:
            _, candidates = _face_candidates(reference)
            if not candidates:
                continue
            score, _ = max(candidates, key=lambda item: item[0])
            if score > best_score:
                best_score = score
                best = reference
    except Exception:
        pass
    return best


def _polish_identity_face(data: bytes, *, target_face_index: int = 0) -> bytes:
    """Reduce swap ripple/compression only inside the selected face, preserving identity geometry."""
    try:
        import cv2
        import numpy as np

        image, candidates = _face_candidates(data)
        if image is None or not candidates:
            return data
        ordered = sorted((box for _, box in candidates), key=lambda box: box[0])
        if target_face_index >= len(ordered):
            return data
        x, y, width, height = ordered[target_face_index]

        pad_x = int(width * 0.12)
        pad_top = int(height * 0.16)
        pad_bottom = int(height * 0.12)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_top)
        x2 = min(image.shape[1], x + width + pad_x)
        y2 = min(image.shape[0], y + height + pad_bottom)
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            return data

        # Mild artifact suppression, followed by restrained detail recovery.
        clean = cv2.bilateralFilter(roi, d=5, sigmaColor=18, sigmaSpace=18)
        blur = cv2.GaussianBlur(clean, (0, 0), 0.75)
        sharpened = cv2.addWeighted(clean, 1.16, blur, -0.16, 0)

        mask = np.zeros(roi.shape[:2], dtype=np.uint8)
        center = (mask.shape[1] // 2, int(mask.shape[0] * 0.50))
        axes = (max(1, int(mask.shape[1] * 0.39)), max(1, int(mask.shape[0] * 0.45)))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), max(2.0, min(width, height) * 0.025))
        alpha = (mask.astype(np.float32) / 255.0)[..., None]
        blended = sharpened.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
        image[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)

        # PNG prevents another lossy JPEG pass after both identity transfers.
        ok, encoded = cv2.imencode(".png", image, [int(cv2.IMWRITE_PNG_COMPRESSION), 2])
        return encoded.tobytes() if ok else data
    except Exception:
        return data


class StarSelfiePipeline:
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
                    raise RuntimeError(f"QC rejected identity transfer: {candidate_qc.reason}")
                return candidate, attempt
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt < self.face_swap_attempts:
                    await asyncio.sleep(min(2.0 * attempt, 6.0))
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

        prompt = build_scene_prompt(request.character.title, request.scene, request.capture_mode)
        character_refs = [path.read_bytes() for path in request.character.reference_paths]
        celebrity_face = _select_best_face_reference(character_refs)
        user_body_reference = request.user_body_path.read_bytes()
        scene_reference = request.scene_reference_path.read_bytes() if request.scene_reference_path is not None else None
        user_face = request.user_face_path.read_bytes()
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
                raise RuntimeError(f"Gemini scene generation failed: {type(exc).__name__}: {exc}") from exc

            scene_qc = self.qc.validate(base_scene)
            if not scene_qc.accepted:
                last_reason = f"scene_{scene_qc.reason}"
                continue

            # Lock celebrity first; user stays last so the user's transferred face is never recompressed by another swap.
            celebrity_locked, celebrity_swap_attempt = await self._swap_with_retries(
                label="Celebrity",
                source_face=celebrity_face,
                target_scene=base_scene,
                target_face_index=1,
            )
            user_locked, user_swap_attempt = await self._swap_with_retries(
                label="User",
                source_face=user_face,
                target_scene=celebrity_locked,
                target_face_index=0,
            )
            final = await asyncio.to_thread(_polish_identity_face, user_locked, target_face_index=0)

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
                    "celebrity_identity_transfer": True,
                    "celebrity_swap_attempt": celebrity_swap_attempt,
                    "celebrity_reference_ranked_by_quality": True,
                    "user_identity_transfer": True,
                    "user_swap_attempt": user_swap_attempt,
                    "user_face_local_artifact_cleanup": True,
                    "lossless_final_encoding": True,
                    "custom_scene_photo": request.scene_reference_path is not None,
                    "user_body_reference": True,
                },
            )

        raise RuntimeError(f"Star Selfie failed QC after {self.max_attempts} attempts: {last_reason}")
