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


def _encode_png(image) -> bytes:
    import cv2

    ok, encoded = cv2.imencode(".png", image, [int(cv2.IMWRITE_PNG_COMPRESSION), 2])
    if not ok:
        raise RuntimeError("Could not encode image")
    return encoded.tobytes()


def _face_candidates(data: bytes):
    """Return frontal faces with quality metadata used for reference ranking."""
    import cv2

    image = _decode_cv_image(data)
    if image is None:
        return image, []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=6, minSize=(70, 70))
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


def _ordered_primary_face_boxes(data: bytes) -> list[tuple[int, int, int, int]]:
    """Return the two dominant scene faces ordered strictly from left to right."""
    image, candidates = _face_candidates(data)
    if image is None:
        return []
    # Keep the largest/clearest detections first, then lock semantic roles by x position.
    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)[:4]
    boxes = [box for _, box in ranked]
    boxes.sort(key=lambda box: box[0] + box[2] / 2.0)
    return boxes[:2]


def _expanded_face_region(
    image_shape,
    box: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Expand around head/neck while keeping each person's region isolated."""
    height_px, width_px = image_shape[:2]
    x, y, width, height = box
    pad_x = int(width * 0.72)
    pad_top = int(height * 0.70)
    pad_bottom = int(height * 0.92)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_top)
    x2 = min(width_px, x + width + pad_x)
    y2 = min(height_px, y + height + pad_bottom)
    return x1, y1, x2, y2


def _extract_region(data: bytes, region: tuple[int, int, int, int]) -> bytes:
    image = _decode_cv_image(data)
    if image is None:
        raise RuntimeError("Could not decode target scene")
    x1, y1, x2, y2 = region
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise RuntimeError("Target face crop is empty")
    return _encode_png(crop)


def _paste_region(
    scene_data: bytes,
    swapped_crop_data: bytes,
    region: tuple[int, int, int, int],
) -> bytes:
    """Feather a locally swapped single-face crop back into the unchanged scene."""
    import cv2
    import numpy as np

    scene = _decode_cv_image(scene_data)
    swapped = _decode_cv_image(swapped_crop_data)
    if scene is None or swapped is None:
        raise RuntimeError("Could not decode swap result")
    x1, y1, x2, y2 = region
    target_width = x2 - x1
    target_height = y2 - y1
    if target_width <= 0 or target_height <= 0:
        raise RuntimeError("Invalid target region")
    if swapped.shape[1] != target_width or swapped.shape[0] != target_height:
        swapped = cv2.resize(swapped, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)

    mask = np.zeros((target_height, target_width), dtype=np.uint8)
    margin_x = max(2, int(target_width * 0.06))
    margin_y = max(2, int(target_height * 0.06))
    cv2.rectangle(
        mask,
        (margin_x, margin_y),
        (target_width - margin_x, target_height - margin_y),
        255,
        -1,
    )
    sigma = max(3.0, min(target_width, target_height) * 0.045)
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    original = scene[y1:y2, x1:x2]
    blended = swapped.astype(np.float32) * alpha + original.astype(np.float32) * (1.0 - alpha)
    scene[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
    return _encode_png(scene)


def _polish_identity_face(data: bytes, *, target_face_index: int = 0) -> bytes:
    """Reduce swap ripple only inside the selected face, preserving identity geometry."""
    try:
        import cv2
        import numpy as np

        image, candidates = _face_candidates(data)
        if image is None or not candidates:
            return data
        ordered = sorted((box for _, box in candidates), key=lambda box: box[0] + box[2] / 2.0)
        if target_face_index >= len(ordered):
            return data
        x, y, width, height = ordered[target_face_index]
        pad_x = int(width * 0.10)
        pad_top = int(height * 0.13)
        pad_bottom = int(height * 0.10)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_top)
        x2 = min(image.shape[1], x + width + pad_x)
        y2 = min(image.shape[0], y + height + pad_bottom)
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            return data

        # Very restrained cleanup: avoid changing face geometry or skin character.
        clean = cv2.bilateralFilter(roi, d=3, sigmaColor=10, sigmaSpace=10)
        blur = cv2.GaussianBlur(clean, (0, 0), 0.55)
        sharpened = cv2.addWeighted(clean, 1.10, blur, -0.10, 0)
        mask = np.zeros(roi.shape[:2], dtype=np.uint8)
        center = (mask.shape[1] // 2, int(mask.shape[0] * 0.50))
        axes = (max(1, int(mask.shape[1] * 0.37)), max(1, int(mask.shape[0] * 0.43)))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), max(1.5, min(width, height) * 0.018))
        alpha = (mask.astype(np.float32) / 255.0)[..., None]
        blended = sharpened.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
        image[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
        return _encode_png(image)
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

    async def _swap_local_region_with_retries(
        self,
        *,
        label: str,
        source_face: bytes,
        target_scene: bytes,
        region: tuple[int, int, int, int],
    ) -> tuple[bytes, int]:
        """Swap one isolated face crop, removing provider face-order ambiguity."""
        errors: list[str] = []
        target_crop = await asyncio.to_thread(_extract_region, target_scene, region)
        for attempt in range(1, self.face_swap_attempts + 1):
            try:
                swapped_crop = await self.face_swap_provider.swap_face(
                    source_face=source_face,
                    target_scene=target_crop,
                    target_face_index=0,
                )
                if not swapped_crop:
                    raise RuntimeError("provider returned an empty image")
                if swapped_crop == target_crop:
                    raise RuntimeError("provider returned the unchanged image")
                crop_qc = self.qc.validate(swapped_crop)
                if not crop_qc.accepted:
                    raise RuntimeError(f"QC rejected local identity transfer: {crop_qc.reason}")
                composited = await asyncio.to_thread(_paste_region, target_scene, swapped_crop, region)
                return composited, attempt
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

            boxes = await asyncio.to_thread(_ordered_primary_face_boxes, base_scene)
            if len(boxes) != 2:
                last_reason = f"scene_expected_two_faces_detected_{len(boxes)}"
                continue

            # Prompt contract is USER on the left, CELEBRITY on the right.
            # Each transfer uses a single-face crop, so Segmind's internal ordering cannot swap identities.
            user_box, celebrity_box = boxes[0], boxes[1]
            base_image = _decode_cv_image(base_scene)
            if base_image is None:
                last_reason = "scene_decode_failed"
                continue
            user_region = _expanded_face_region(base_image.shape, user_box)
            celebrity_region = _expanded_face_region(base_image.shape, celebrity_box)

            celebrity_locked, celebrity_swap_attempt = await self._swap_local_region_with_retries(
                label="Celebrity",
                source_face=celebrity_face,
                target_scene=base_scene,
                region=celebrity_region,
            )
            user_locked, user_swap_attempt = await self._swap_local_region_with_retries(
                label="User",
                source_face=user_face,
                target_scene=celebrity_locked,
                region=user_region,
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
                    "identity_assignment": "left_user_right_celebrity",
                    "local_single_face_transfers": True,
                    "provider_face_order_ambiguity_removed": True,
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
