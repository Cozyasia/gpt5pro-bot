from __future__ import annotations

from .models import GenerationRequest, GenerationResult
from .prompts.scene import build_scene_prompt
from .storage import StarSelfieStorage


class StarSelfiePipeline:
    def __init__(self, scene_provider, face_swap_provider, storage: StarSelfieStorage):
        self.scene_provider = scene_provider
        self.face_swap_provider = face_swap_provider
        self.storage = storage

    async def run(self, request: GenerationRequest) -> GenerationResult:
        if not request.user_face_path.is_file():
            raise FileNotFoundError(request.user_face_path)
        if not 3 <= len(request.character.reference_paths) <= 6:
            raise ValueError("Character must have 3-6 reference images")

        prompt = build_scene_prompt(request.character.title, request.scene, request.capture_mode)
        refs = [path.read_bytes() for path in request.character.reference_paths]
        base_scene = await self.scene_provider.generate(prompt=prompt, character_references=refs)
        final = await self.face_swap_provider.swap_user_face(
            source_face=request.user_face_path.read_bytes(),
            target_scene=base_scene,
        )
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
            metadata={"character": request.character.slug, "aspect_ratio": request.aspect_ratio},
        )
