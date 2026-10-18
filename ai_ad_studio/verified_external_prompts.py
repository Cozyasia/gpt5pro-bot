"""Verified external prompt-pack index, not generated prompts.

Store identifiers, links and transformation slots. Original full prompts remain
at the publishers' URLs until redistribution rights are established.
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
    ExternalPrompt("M-ADS-01","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"1. Perfume bottle turntable reveal","perfume",REQUIRED),
    ExternalPrompt("M-ADS-02","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"2. Sneaker splash on rotating platform","footwear",REQUIRED),
    ExternalPrompt("M-ADS-03","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"3. Watch macro on black velvet","watch",REQUIRED),
    ExternalPrompt("M-ADS-06","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"6. Coffee bag morning pour-over","coffee",REQUIRED),
    ExternalPrompt("M-ADS-07","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"7. Skincare set on a sunny vanity","skincare",REQUIRED),
    ExternalPrompt("M-ADS-08","Memons","22 Seedance Prompts for Product & Ad Video",MEMONS_ADS,"8. Tech gift unwrap by the window","electronics",REQUIRED),
    ExternalPrompt("R-PROD-01","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 1. Perfume turntable","perfume",REQUIRED),
    ExternalPrompt("R-PROD-02","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 2. Watch macro","watch",REQUIRED),
    ExternalPrompt("R-PROD-03","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 3. Coffee pour","coffee",REQUIRED),
    ExternalPrompt("R-PROD-04","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 4. Running shoe splash","footwear",REQUIRED),
    ExternalPrompt("R-PROD-05","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 5. Coastal car tracking","vehicle",REQUIRED),
    ExternalPrompt("R-PROD-06","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 6. Headphones on table","electronics",REQUIRED),
    ExternalPrompt("R-PROD-07","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 7. Flowing dress fabric","fashion",REQUIRED),
    ExternalPrompt("R-PROD-08","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 8. Melting chocolate macro","food",REQUIRED),
    ExternalPrompt("R-PROD-09","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 9. Bicycle forest tracking","bicycle",REQUIRED),
    ExternalPrompt("R-PROD-10","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 10. Wine pour","beverage",REQUIRED),
    ExternalPrompt("R-PROD-11","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 11. Sneaker sole detail","footwear",REQUIRED),
    ExternalPrompt("R-PROD-12","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 12. Luggage airport tracking","travel_accessory",REQUIRED),
    ExternalPrompt("R-PROD-13","Runway","92 Ready-to-Use Prompts",RUNWAY_92,"Product demonstration 13. Luxury candle lighting","home_fragrance",REQUIRED),
)

def list_verified_prompts(product_type: str | None = None) -> tuple[ExternalPrompt, ...]:
    return tuple(p for p in PROMPTS if product_type is None or p.product_type == product_type)
