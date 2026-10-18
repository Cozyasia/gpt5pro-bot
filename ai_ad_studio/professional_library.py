"""Professional prompt compiler for all 100 advertising styles.

Source-inspired, original adaptations, not verbatim imports or 100 independently
verified third-party examples. External reference guides are credited below.
No provider request or billing happens in this module.
"""
from dataclasses import dataclass
from .catalog import get_template
from .creative_directions import CREATIVE_DIRECTIONS

REFERENCES = {
    "seedance_product": "https://www.seeddance.io/prompts",
    "seedance_i2v": "https://www.seeddance.io/blog/seedance-2-5-image-to-video-prompts",
    "seedance_commercial": "https://www.seedance.tv/blog/seedance-ai-commercial-video-guide",
    "runway_motion": "https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide",
    "product_ads": "https://memons.ai/seedance-prompts-product-ads",
}
CATEGORY_REFERENCES = {
    "fragrance": ("seedance_product", "seedance_i2v", "product_ads"),
    "electronics": ("seedance_product", "seedance_commercial", "product_ads"),
    "vehicles": ("seedance_commercial", "runway_motion"),
    "fashion": ("seedance_product", "seedance_commercial"),
    "food": ("seedance_product", "seedance_i2v"),
    "realestate": ("seedance_i2v", "runway_motion"),
    "digital": ("seedance_commercial", "runway_motion"),
    "travel": ("seedance_commercial", "runway_motion"),
    "universal": ("seedance_product", "runway_motion"),
}
CATEGORY_AUDIO = {
    "fragrance": "Minimal elegant orchestral texture and delicate glass detail.",
    "electronics": "Subtle precise electronic pulses and restrained mechanical foley.",
    "vehicles": "Cinematic low-frequency ambience and realistic environment sound.",
    "fashion": "Editorial instrumental rhythm with soft fabric movement.",
    "food": "Natural kitchen foley, soft inviting rhythmic background.",
    "realestate": "Calm cinematic instrumental and authentic ambient room tone.",
    "digital": "Clean contemporary electronic ambience; add UI sounds in post.",
    "travel": "Atmospheric instrumental music and natural location sound.",
    "universal": "Music matching the brand tone, with clear space for narration.",
}
CATEGORY_LENS = {
    "fragrance": "85mm hero portrait lens, 100mm macro for packaging details",
    "electronics": "50mm product hero, 100mm macro for surface details",
    "vehicles": "35mm wide tracking and 85mm detail shots",
    "fashion": "50mm editorial lens and 100mm accessory macro",
    "food": "85mm appetizing detail and overhead product framing",
    "realestate": "24mm architecture lens, stabilized and perspective-correct",
    "digital": "50mm device framing, sharp composited interface",
    "travel": "24mm establishing lens and 50mm detail",
    "universal": "50mm product hero and 85mm detail",
}
SHOT_CAMERAS = (
    "Slow dolly forward, starting at a medium shot and ending on a readable product hero.",
    "One controlled macro tracking move across an authentic visible product detail.",
    "Small 20-degree lateral orbit, with realistic parallax and no product morphing.",
    "Gentle stabilized pullback to show the product in its verified context.",
    "Locked centered hero shot for the final beat; reserve clean negative space for title compositing.",
)
SHOT_LIGHTS = (
    "Controlled studio key light and restrained rim highlight.",
    "Softbox reflection with realistic specular falloff.",
    "Art-direction lighting consistent with the selected environment.",
    "Balanced key and fill, maintaining real packaging colors.",
    "Stable product lighting and clean brand-safe background.",
)
SHOT_AUDIO = (
    "Soft opening accent and natural ambience.",
    "Detailed product-specific foley where physically appropriate.",
    "Gentle cinematic transition swell.",
    "Music builds toward a clear final brand beat.",
    "Music settles; reserve a clean ending for user-approved voiceover.",
)

@dataclass(frozen=True)
class ProfessionalShot:
    index: int
    duration_hint: str
    prompt: str
    camera: str
    lighting: str
    sound: str

def compile_professional_prompt(template_id: str, product_name: str,
                                product_description: str,
                                aspect_ratio: str = "9:16",
                                provider: str = "seedance") -> dict:
    if not product_name.strip() or not product_description.strip():
        raise ValueError("Product name and description are required")
    if aspect_ratio not in {"9:16", "16:9", "1:1"}:
        raise ValueError("Unsupported aspect ratio")
    if provider not in {"seedance", "kling", "runway"}:
        raise ValueError("Unsupported provider")
    template = get_template(template_id)
    art = CREATIVE_DIRECTIONS[template_id]
    shots = []
    for i, beat in enumerate(template.shots):
        # Runway's official guide favors concise positive motion descriptions.
        motion = SHOT_CAMERAS[i]
        base = (
            f"Image-to-video commercial shot {i+1}/5, {aspect_ratio}. "
            f"Use the uploaded image as the exact visual reference for {product_name}. "
            f"Verified product context: {product_description}. "
            f"Creative treatment: {art}. "
            f"Scene objective: {beat} "
            f"Camera: {motion} "
            f"Lighting: {SHOT_LIGHTS[i]} "
            "Maintain exact packaging geometry, materials, color and label position. "
            "Keep the product physically consistent across frames. "
            "Finish with a stable composition suitable for editing."
        )
        if provider == "runway":
            base = (
                f"The camera performs: {motion} "
                f"Visual atmosphere: {art}. {SHOT_LIGHTS[i]} "
                "The product in the input image remains visually consistent. "
                "Cinematic live-action commercial."
            )
        shots.append(ProfessionalShot(i+1, "approximately one fifth of the total duration",
                                      base, motion, SHOT_LIGHTS[i], SHOT_AUDIO[i]).__dict__)
    return {
        "template_id": template_id, "title": template.title,
        "provider": provider, "mode": "image_to_video",
        "product_name": product_name, "aspect_ratio": aspect_ratio,
        "art_direction": art, "lens": CATEGORY_LENS[template.category],
        "shots": shots, "music_direction": CATEGORY_AUDIO[template.category],
        "russian_voiceover_brief": (
            "Write a short original Russian advertisement based ONLY on verified product "
            "features supplied by the user. Do not invent claims, prices, or endorsements. "
            "Approve the final script before audio synthesis."
        ),
        "postproduction": (
            "Composite the user-provided logo, accurate titles, approved Russian voiceover "
            "and licensed music after video generation."
        ),
        "quality_checks": [
            "Match reference product identity and packaging",
            "Verify labels and logo separately in final compositing",
            "Check camera continuity, flicker, unwanted objects and cropping",
            "Check every advertised claim against the user brief",
            "Validate provider clip duration and input limits before paid generation",
        ],
        "source_guides": [REFERENCES[k] for k in CATEGORY_REFERENCES[template.category]],
        "provenance": "Original adaptation informed by published professional guides; not verbatim imported prompts",
        "tested_with_provider": False,
    }

def compile_library(provider: str = "seedance") -> tuple[dict, ...]:
    return tuple(
        compile_professional_prompt(tid, "[USER_PRODUCT_NAME]",
                                    "[USER_VERIFIED_PRODUCT_DESCRIPTION]",
                                    provider=provider)
        for tid in CREATIVE_DIRECTIONS
    )
