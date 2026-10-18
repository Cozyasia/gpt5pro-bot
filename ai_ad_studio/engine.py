"""Deterministic, non-billing storyboard builder."""
from dataclasses import dataclass
from .catalog import get_template
from .source_patterns import source_for_template

@dataclass(frozen=True)
class ProductBrief:
    name: str
    description: str
    reference_image_ids: tuple[str, ...]
    logo_id: str | None = None
    language: str = "ru"
    aspect_ratio: str = "9:16"
    duration_seconds: int = 30

    def validate(self) -> None:
        if not self.name.strip() or not self.description.strip():
            raise ValueError("Product name and description are required")
        if not 1 <= len(self.reference_image_ids) <= 5 or not all(self.reference_image_ids):
            raise ValueError("Provide 1–5 valid product image references")
        if self.aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise ValueError("Unsupported aspect ratio")
        if self.duration_seconds not in {10, 15, 20, 30, 60}:
            raise ValueError("Unsupported storyboard duration")
        if self.language not in {"ru", "en"}:
            raise ValueError("Unsupported language")

def build_storyboard(template_id: str, brief: ProductBrief) -> dict:
    brief.validate()
    template = get_template(template_id)
    source_pattern = source_for_template(template_id)
    shot_count = len(template.shots)
    boundaries = [brief.duration_seconds * i // shot_count for i in range(shot_count + 1)]
    return {
        "template_id": template.id,
        "professional_source": ({"title": source_pattern.source_title, "url": source_pattern.source_url,
            "example": source_pattern.source_example, "mode": source_pattern.mode} if source_pattern else None),
        "adapted_source_direction": source_pattern.adapted_direction if source_pattern else None, "style": template.title, "category": template.category,
        "product_name": brief.name, "product_description": brief.description,
        "reference_image_ids": list(brief.reference_image_ids), "logo_id": brief.logo_id,
        "language": brief.language, "aspect_ratio": brief.aspect_ratio,
        "duration_seconds": brief.duration_seconds,
        "shots": [{"start": boundaries[i], "end": boundaries[i+1], "instruction": instruction}
                  for i, instruction in enumerate(template.shots)],
        "camera": template.camera, "lighting": template.lighting,
        "generation_constraints": [
            "Preserve the exact product identity from the uploaded reference images.",
            "Never replace the user's product with a famous brand or another product.",
            "Do not invent features, endorsements, certifications, or product claims.",
            "Add logo, readable titles, music and voiceover in post-production.",
            "Verify provider-supported clip duration before generation.",
        ],
        "status": "storyboard_only",
    }
