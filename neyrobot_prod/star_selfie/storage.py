from __future__ import annotations

import os
import uuid
from pathlib import Path


class StarSelfieStorage:
    def __init__(self, root: Path):
        self.root = root

    def save_generation(self, *, user_id: int, scene: bytes, final: bytes) -> tuple[Path, Path]:
        generation_id = uuid.uuid4().hex
        directory = self.root / "generations" / str(user_id) / generation_id
        directory.mkdir(parents=True, exist_ok=True)
        scene_path = directory / "scene.png"
        final_path = directory / "final.png"
        self._atomic_write(scene_path, scene)
        self._atomic_write(final_path, final)
        return scene_path, final_path

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(content)
        os.replace(temp, path)
