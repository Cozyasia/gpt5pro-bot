"""Verified, source-backed metadata for the 52 HeyDreaming advertising prompts.

Original full text is available in the source prompts.json. Attribution and
license are preserved; no synthetic prompts are represented as imports.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class LibraryEntry:
    id: str
    title: str
    category: str
    tags: tuple[str, ...]
    duration: str
    aspect: str
    source_url: str
    license: str
    publisher: str

PROMPTS = (
    LibraryEntry("frost-glass-serum-condensation-macro", "Frost-Glass Serum, Condensation Macro", "product-showcase", ("skincare","macro","condensation","fog"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sneaker-360-turntable-studio", "Sneaker, 360 Turntable Studio", "product-showcase", ("sneakers","turntable","studio","gel-light"), "6s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("espresso-pour-crema-physics", "Espresso Pour, Crema Physics", "product-showcase", ("coffee","liquid","crema","backlight"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("earbuds-exploded-view-levitation", "Earbuds, Exploded-View Levitation", "product-showcase", ("gadget","levitation","exploded-view","techwear"), "6s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("candle-ambient-slow-ignite", "Candle, Ambient Slow Ignite", "product-showcase", ("candle","cozy","ambient-glow","warm-light"), "8s", "4:5", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("eyewear-motion-control-light-streaks", "Eyewear, Motion-Control Light Streaks", "product-showcase", ("eyewear","motion-control","anamorphic","studio"), "6s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("bathroom-mirror-skincare-truth", "Bathroom Mirror Skincare Truth", "ugc-authentic", ("skincare","selfie","mirror"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sneaker-unboxing-on-stairs", "Sneaker Unboxing On Stairs", "ugc-authentic", ("sneakers","unboxing","streetwear"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("desk-coffee-morning-ritual", "Desk Coffee Morning Ritual", "ugc-authentic", ("coffee","morning","testimonial"), "8s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("car-vlog-supplement-confession", "Car Vlog Supplement Confession", "ugc-authentic", ("supplements","car-vlog","day-in-life"), "10s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("candle-cozy-rainy-night", "Candle Cozy Rainy Night", "ugc-authentic", ("candle","cozy","asmr"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("try-on-eyewear-street-spin", "Try-On Eyewear Street Spin", "ugc-authentic", ("eyewear","try-on","street"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("coffee-bloom-resurrection", "Coffee Bloom Resurrection", "before-after", ("coffee","macro","before-after","appetizing"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sneaker-out-of-mud", "Sneaker Out Of Mud", "before-after", ("sneakers","whip-pan","studio","transformation"), "8s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("dull-skin-to-glow", "Dull Skin To Glow", "before-after", ("skincare","macro-beauty","glow-up","before-after"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("cluttered-desk-candle-reset", "Cluttered Desk Candle Reset", "before-after", ("candle","match-cut","ambiance","lifestyle"), "10s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("foggy-lens-to-sharp", "Foggy Lens To Sharp", "before-after", ("eyewear","rack-focus","POV","clarity"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("glass-serum-unbox", "Glass Serum Unbox", "unboxing-asmr", ("skincare","macro","oddly-satisfying"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sneaker-tissue-reveal", "Sneaker Tissue Reveal", "unboxing-asmr", ("sneakers","tactile","reveal"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("watch-drawer-slide", "Watch Drawer Slide", "unboxing-asmr", ("watch","luxury","precision-click"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("gadget-foam-cradle", "Gadget Foam Cradle", "unboxing-asmr", ("gadget","tech","satisfying-click"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("candle-wax-press", "Candle Wax Press", "unboxing-asmr", ("candle","cozy","wax-press"), "8s", "4:5", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("cracked-heels-glass-floor", "Cracked Heels, Glass Floor", "problem-solution", ("skincare","pain-point","macro","transformation"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("burnt-tongue-steady-sip", "Burnt Tongue, Steady Sip", "problem-solution", ("coffee","gadget","pattern-interrupt","lifestyle"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("foggy-lens-sharp-city", "Foggy Lens, Sharp City", "problem-solution", ("eyewear","POV","clarity","pattern-interrupt"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("3pm-crash-lit-desk", "3pm Crash, Lit Desk", "problem-solution", ("supplements","crash-recovery","top-down","transformation"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("scuffed-soles-clean-strike", "Scuffed Soles, Clean Strike", "problem-solution", ("sneakers","macro","slow-motion","before-after"), "10s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sunrise-pour-over-ritual", "Sunrise Pour-Over Ritual", "lifestyle-brand", ("coffee","morning-ritual","warm","slow-living"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("rain-slick-city-run-at-dusk", "Rain-Slick City Run At Dusk", "lifestyle-brand", ("sneakers","fitness","cinematic","dusk"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("conservatory-serum-calm", "Conservatory Serum Calm", "lifestyle-brand", ("skincare","wellness","minimal","clean-beauty"), "6s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("candlelit-vinyl-wind-down", "Candlelit Vinyl Wind-Down", "lifestyle-brand", ("candles","home","cozy","evening"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("boardwalk-eyewear-heat-haze", "Boardwalk Eyewear Heat-Haze", "lifestyle-brand", ("eyewear","lifestyle","summer","confident"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("cross-section-cutaway-cold-brew-filter", "Cross-Section Cutaway: Cold-Brew Filter", "feature-explainer", ("coffee","cross-section","macro","how-it-works"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("x-ray-energy-return-running-midsole", "X-Ray Energy Return: Running Midsole", "feature-explainer", ("sneakers","x-ray","slow-motion","energy-return"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("absorption-time-lapse-hydrating-serum", "Absorption Time-Lapse: Hydrating Serum", "feature-explainer", ("skincare","time-lapse","macro","absorption"), "6s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("thermal-data-overlay-smart-mug", "Thermal Data Overlay: Smart Mug", "feature-explainer", ("gadget","thermal-overlay","ui-callout","smart-home"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("exploded-assembly-reveal-clean-burn-candle", "Exploded-Assembly Reveal: Clean-Burn Candle", "feature-explainer", ("candle","exploded-view","ambient","clean-burn"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("pov-morning-skincare-drop", "POV Morning Skincare Drop", "social-trend", ("pov","skincare","asmr","ugc"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("green-screen-spec-reveal", "Green-Screen Spec Reveal", "social-trend", ("green-screen","gadget","explainer","ugc"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("this-or-that-sneaker-split", "This Or That Sneaker Split", "social-trend", ("comparison","sneakers","split-screen"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("glow-up-transformation-whip", "Glow-Up Transformation Whip", "social-trend", ("transformation","glow-up","beauty","trend"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("expectation-vs-reality-candle", "Expectation Vs Reality Candle", "social-trend", ("expectation-vs-reality","candle","trend","mood"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("black-serum-cold-marble", "Black Serum, Cold Marble", "luxury-premium", ("skincare","macro","editorial"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("espresso-slow-pour", "Espresso, Slow Pour", "luxury-premium", ("coffee","food","slow-motion"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sneaker-wet-concrete", "Sneaker, Wet Concrete", "luxury-premium", ("sneakers","streetwear","action"), "8s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("eyewear-desert-noon", "Eyewear, Desert Noon", "luxury-premium", ("eyewear","fashion","macro"), "6s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("candle-midnight-library", "Candle, Midnight Library", "luxury-premium", ("candle","home","ambient"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("cold-brew-pour-cascade", "Cold Brew Pour Cascade", "food-beverage", ("coffee","macro","liquid-pour","appetite"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("honey-drizzle-on-toast", "Honey Drizzle On Toast", "food-beverage", ("food","honey","texture","slow-motion"), "6s", "1:1", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("ramen-steam-ritual", "Ramen Steam Ritual", "food-beverage", ("food","noodles","steam","cinematic"), "8s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("sparkling-citrus-burst", "Sparkling Citrus Burst", "food-beverage", ("beverage","sparkling","fizz","product-hero"), "6s", "9:16", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
    LibraryEntry("chocolate-fold-and-crackle", "Chocolate Fold And Crackle", "food-beverage", ("food","chocolate","macro","indulgent"), "6s", "16:9", "https://github.com/LichAmnesia/awesome-ad-video-prompts/blob/main/prompts.json", "CC BY 4.0", "LichAmnesia / HeyDreaming"),
)
assert len(PROMPTS) == 52
assert len({p.id for p in PROMPTS}) == 52
