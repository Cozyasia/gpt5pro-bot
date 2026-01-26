
import os
ENGINE_HELP={
"runway":"Text/Image → Video (9 сек)",
"luma":"Image → Video",
"sora":"Text/Image → Video (Comet)",
"kling":"Image → Video (Comet)"
}
async def run_engine(engine,mode,prompt,photo):
    if engine=="runway" and not os.getenv("RUNWAY_API_KEY"):
        return "❌ Runway: нет RUNWAY_API_KEY"
    if engine in ("sora","kling") and not os.getenv("COMET_API_KEY"):
        return f"❌ {engine}: нет COMET_API_KEY"
    if engine=="luma" and not os.getenv("LUMA_API_KEY"):
        return "❌ Luma: нет LUMA_API_KEY"
    return f"✅ {engine.upper()} запущен ({mode})."
