"""Brand-neutral advertising style catalog."""
from dataclasses import dataclass
from .creative_directions import professional_shots, CREATIVE_DIRECTIONS

@dataclass(frozen=True)
class Template:
    id: str
    category: str
    title: str
    shots: tuple[str, ...]
    lighting: str
    camera: str

CATEGORIES = {
    "fragrance": ("Luxury Perfume", "Golden Macro", "Silk Reveal", "Minimalist Bottle", "Editorial Noir", "Botanical Aura", "Crystal Light", "Art Deco", "Romantic Glow", "Modern Elegance", "Dark Velvet", "White Studio", "Water Reflection", "Night Luxury", "Signature Reveal"),
    "electronics": ("Flagship Reveal", "Precision Macro", "Tech Noir", "Floating Product", "Desk Lifestyle", "Light Trails", "Feature Showcase", "Minimal White", "Cinematic Launch", "Hands-on Demo", "Industrial Edge", "Color Spectrum", "Smart Home", "Future Interface", "Premium Unboxing"),
    "vehicles": ("Night Drive", "Studio Reveal", "Road Freedom", "Detail Focus", "Mountain Motion", "Urban Motion", "Luxury Garage", "Coastal Journey", "Performance Film", "Heritage Story"),
    "fashion": ("Runway Spotlight", "Editorial Studio", "Silk Motion", "Jewelry Macro", "Golden Hour", "Monochrome", "Street Luxury", "Craftsmanship", "Museum Display", "Fashion Film", "Minimal Wardrobe", "Evening Glamour", "Soft Romance", "Avant Garde", "Premium Unboxing"),
    "food": ("Fresh Ingredient", "Macro Texture", "Chef's Table", "Steam Reveal", "Cafe Morning", "Premium Plating", "Slow Pour", "Colorful Splash", "Artisan Story", "Restaurant Mood"),
    "realestate": ("Villa Tour", "Sunrise Exterior", "Pool Lifestyle", "Architectural Lines", "Golden Hour Home", "Luxury Interior", "Coastal Escape", "Garden Reveal", "Penthouse View", "Resort Experience"),
    "digital": ("App Showcase", "Problem Solution", "Trust Story", "Interface Demo", "Founder Vision", "Minimal Tech", "Feature Sequence", "Everyday Use", "Security Concept", "Global Service"),
    "travel": ("Destination Dream", "Hotel Reveal", "Adventure Motion", "Spa Calm", "Island Escape", "City Weekend", "Resort Lifestyle", "Experience Story", "Sunset Journey", "Luxury Retreat"),
    "universal": ("Hero Product", "UGC Testimonial", "Problem Solution", "Premium Cinematic", "Social Quick Cut"),
}

SHOT_PLAN = (
    "Reveal the exact user-supplied product in a controlled hero composition.",
    "Show a realistic close-up of a verified physical detail or feature.",
    "Demonstrate a benefit supported by the product description without inventing claims.",
    "Present a cinematic lifestyle or environment shot consistent with the product.",
    "Finish with a stable clean product packshot reserved for post-production titles.",
)
TEMPLATES = tuple(Template(
    id=f"{category}-{index:03d}", category=category, title=title,
    shots=professional_shots(f'{category}-{index:03d}'), lighting="Premium cinematic, physically plausible reflections",
    camera="Smooth dolly, macro tracking and stable final hero shot",
) for category, titles in CATEGORIES.items() for index, title in enumerate(titles, 1))
assert len(TEMPLATES) == 100
assert len(CREATIVE_DIRECTIONS) == 100

def get_template(template_id: str) -> Template:
    return next(t for t in TEMPLATES if t.id == template_id)

def list_templates(category: str | None = None) -> tuple[Template, ...]:
    return tuple(t for t in TEMPLATES if category is None or t.category == category)
