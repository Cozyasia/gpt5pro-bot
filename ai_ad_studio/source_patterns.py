"""Curated external professional prompt patterns and their provenance.

Entries are independently adapted short directions rather than reproductions
of full third-party collections. Attribution stays available to operators.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class SourcePattern:
    template_id: str
    source_title: str
    source_url: str
    source_example: str
    mode: str
    adapted_direction: str

SEED_LIBRARY = "https://www.seeddance.io/prompts"
RUNWAY_LIBRARY = "https://runway.com/resources/ai-video-prompting-guide"
RUNWAY_MOTION = "https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide"

SOURCE_PATTERNS = (
    SourcePattern("fragrance-001", "SeedVideo prompt library", SEED_LIBRARY, "Premium skincare bottle", "image_to_video", "Product on premium stone surface; measured macro orbit, warm side illumination and consistent reference packaging."),
    SourcePattern("fragrance-002", "SeedVideo prompt library", SEED_LIBRARY, "Product photo turntable", "image_to_video", "Preserve product geometry and packaging; small turntable rotation with controlled moving highlight."),
    SourcePattern("electronics-001", "SeedVideo prompt library", SEED_LIBRARY, "Headphones color launch", "image_to_video", "Centered electronic product on a geometric plinth, narrow light bands sweeping across authentic surfaces."),
    SourcePattern("electronics-002", "SeedVideo prompt library", SEED_LIBRARY, "Product demo", "image_to_video", "Subtle rotation on dark reflective platform, gentle push-in and crisp edge illumination."),
    SourcePattern("fashion-004", "SeedVideo prompt library", SEED_LIBRARY, "Watch detail sequence", "image_to_video", "Extreme macro of authentic dial or accessory detail, gradual transition to a balanced overhead hero view."),
    SourcePattern("food-002", "SeedVideo prompt library", SEED_LIBRARY, "Food photography animation", "image_to_video", "Gentle steam and minimal orbit reveal existing plated-food texture; ingredients and arrangement stay constant."),
    SourcePattern("food-008", "SeedVideo prompt library", SEED_LIBRARY, "Packaged snack social ad", "image_to_video", "Bright countertop, energetic short motion beat and final front-facing package reveal."),
    SourcePattern("realestate-001", "SeedVideo prompt library", SEED_LIBRARY, "Interior design walkthrough", "image_to_video", "Stabilized doorway-to-window move preserving reference architecture, materials and furniture."),
    SourcePattern("digital-001", "SeedVideo prompt library", SEED_LIBRARY, "App promo", "text_to_video", "Smooth interface-card parallax around device; insert accurate user-provided UI screens during compositing."),
    SourcePattern("vehicles-002", "SeedVideo prompt library", SEED_LIBRARY, "Brand film opener", "image_to_video", "Slow frontal vehicle reveal through atmospheric haze with restrained cinematic backlight."),
    SourcePattern("universal-001", "Runway video prompting guide", RUNWAY_LIBRARY, "Camera movement + scene + action + details", "image_to_video", "Single hero shot with explicit dolly direction, one product action, simple background and clear light."),
    SourcePattern("universal-004", "Runway Gen-4 video prompting guide", RUNWAY_MOTION, "Motion-focused image-to-video prompting", "image_to_video", "Describe camera and scene movement around the uploaded product without redundantly recreating its identity."),
)

PATTERNS_BY_TEMPLATE = {pattern.template_id: pattern for pattern in SOURCE_PATTERNS}

def source_for_template(template_id: str) -> SourcePattern | None:
    return PATTERNS_BY_TEMPLATE.get(template_id)
