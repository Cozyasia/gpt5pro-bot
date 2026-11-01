from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "web" / "studio_menu.html").read_text(
    encoding="utf-8"
)


def test_miniapp_is_rebranded_and_targets_neyronix():
    assert "NEYRONIX" in HTML
    assert "botUsername:'neyronixbot'" in HTML
    assert "progpt5_bot" not in HTML
    assert "NEYRO-BOT GPT 5 STUDIO" not in HTML


def test_every_catalog_card_is_available_through_a_slug_not_raw_callback():
    for slug in (
        "medicine", "video", "market", "celebrity", "realty", "photo",
        "music", "study", "work", "assistant", "advert",
    ):
        assert f"route:'{slug}'" in HTML
    assert "sendData(" not in HTML
    assert "callback_data" not in HTML


def test_mobile_layout_keeps_compact_banner_cards_and_bottom_nav():
    assert "min-height:258px!important" not in HTML
    assert "@media(max-width:390px)" in HTML
    assert ".bottom-nav" in HTML
    assert "safe-area-inset-bottom" in HTML
