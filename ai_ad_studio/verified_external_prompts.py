"""Index of individual, identifiable published advertising prompt examples.

This file intentionally stores *metadata and links*, not verbatim copyrighted
prompt bodies. The original prompts are available at the source URL.
Never label this as 100 imported prompts until 100 distinct source items
have been checked individually.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ExternalPrompt:
    id: str
    publisher: str
    pack: str
    source_url: str
    source_item: str
    product_type: str
    adaptation_slots: tuple[str, ...]
    verified: bool = True

MEMONS_ADS = "https://memons.ai/seedance-prompts-product-ads"
RUNWAY_92 = "https://runway.com/resources/ai-video-prompting-guide"
REQUIRED = ("product_name", "reference_image", "verified_description", "brand_assets")
PROMPTS = (
    ExternalPrompt("M-ADS-01", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "1. Perfume bottle turntable reveal", "fragrance", REQUIRED),
    ExternalPrompt("M-ADS-02", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "2. Sneaker splash on rotating platform", "footwear", REQUIRED),
    ExternalPrompt("M-ADS-03", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "3. Watch macro on black velvet", "watch", REQUIRED),
    ExternalPrompt("M-ADS-04", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "4. Cosmetic jar with ingredient toss", "skincare", REQUIRED),
    ExternalPrompt("M-ADS-05", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "5. Sneaker box unboxing on desk", "footwear", REQUIRED),
    ExternalPrompt("M-ADS-06", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "6. Morning coffee ritual with the brand", "coffee", REQUIRED),
    ExternalPrompt("M-ADS-07", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "7. Skincare set on a sunny vanity", "skincare", REQUIRED),
    ExternalPrompt("M-ADS-08", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "8. Tech gift unwrap by the window", "electronics", REQUIRED),
    ExternalPrompt("M-ADS-09", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "9. Cola can pour over ice", "beverage", REQUIRED),
    ExternalPrompt("M-ADS-10", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "10. Burger stack build with cheese pull", "food", REQUIRED),
    ExternalPrompt("M-ADS-11", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "11. Espresso pour into a branded cup", "coffee", REQUIRED),
    ExternalPrompt("M-ADS-12", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "12. Chocolate bar snap macro", "food", REQUIRED),
    ExternalPrompt("M-ADS-13", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "13. Wireless earbuds case open", "electronics", REQUIRED),
    ExternalPrompt("M-ADS-14", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "14. Smartphone rotating hero shot", "electronics", REQUIRED),
    ExternalPrompt("M-ADS-15", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "15. Laptop lid-open desk reveal", "electronics", REQUIRED),
    ExternalPrompt("M-ADS-16", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "16. Smartwatch wrist raise close-up", "electronics", REQUIRED),
    ExternalPrompt("M-ADS-17", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "17. Serum dropper drip macro", "skincare", REQUIRED),
    ExternalPrompt("M-ADS-18", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "18. Foundation swatch on skin", "cosmetics", REQUIRED),
    ExternalPrompt("M-ADS-19", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "19. Lipstick bullet twist-up", "cosmetics", REQUIRED),
    ExternalPrompt("M-ADS-20", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "20. Vertical unboxing hook for Reels", "universal", REQUIRED),
    ExternalPrompt("M-ADS-21", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "21. Vertical product-in-hand tagline", "universal", REQUIRED),
    ExternalPrompt("M-ADS-22", "Memons", "22 Seedance Prompts for Product & Ad Video", MEMONS_ADS, "22. Vertical before-and-after skincare spot", "skincare", REQUIRED),
    ExternalPrompt("R-PROD-01", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 1. Perfume turntable", "fragrance", REQUIRED),
    ExternalPrompt("R-PROD-02", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 2. Watch macro", "watch", REQUIRED),
    ExternalPrompt("R-PROD-03", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 3. Coffee pour", "coffee", REQUIRED),
    ExternalPrompt("R-PROD-04", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 4. Running shoe splash", "footwear", REQUIRED),
    ExternalPrompt("R-PROD-05", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 5. Coastal car tracking", "vehicle", REQUIRED),
    ExternalPrompt("R-PROD-06", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 6. Headphones on table", "electronics", REQUIRED),
    ExternalPrompt("R-PROD-07", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 7. Flowing dress fabric", "fashion", REQUIRED),
    ExternalPrompt("R-PROD-08", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 8. Melting chocolate macro", "food", REQUIRED),
    ExternalPrompt("R-PROD-09", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 9. Bicycle forest tracking", "bicycle", REQUIRED),
    ExternalPrompt("R-PROD-10", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 10. Wine pour", "beverage", REQUIRED),
    ExternalPrompt("R-PROD-11", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 11. Sneaker sole detail", "footwear", REQUIRED),
    ExternalPrompt("R-PROD-12", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 12. Luggage airport tracking", "travel_accessory", REQUIRED),
    ExternalPrompt("R-PROD-13", "Runway", "92 Ready-to-Use Prompts / Product Demonstrations", RUNWAY_92, "Product demonstration 13. Luxury candle lighting", "home_fragrance", REQUIRED),
)
assert len(PROMPTS) == 35
assert len({p.id for p in PROMPTS}) == len(PROMPTS)

def list_verified_prompts(product_type: str | None = None) -> tuple[ExternalPrompt, ...]:
    return tuple(p for p in PROMPTS if product_type is None or p.product_type == product_type)
