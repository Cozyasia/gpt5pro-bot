import unittest
from unittest.mock import patch
import sys
import types
from neyrobot_prod.studio_menu_start import parse_studio_start, studio_start_markup

class StartRouteTests(unittest.TestCase):
    def test_allowed(self):
        self.assertEqual(parse_studio_start(["studio_market"]),("market","ent:brief:product_ad"))
        self.assertEqual(parse_studio_start(["studio_realty"]),("realty","revideo:start"))
        self.assertEqual(parse_studio_start(["studio_advert"]),("advert","ent:brief:product_ad"))
    def test_rejected(self):
        for args in ([],["studio_admin"],["studio_mode:medicine"],["studio_market","extra"],["other"],["studio_"+"x"*100],None):
            self.assertIsNone(parse_studio_start(args))
    def test_button_requires_click(self):
        class Button:
            def __init__(self,text,callback_data):self.text,self.callback_data=text,callback_data
        class Markup:
            def __init__(self,inline_keyboard):self.inline_keyboard=inline_keyboard
        with patch.dict(sys.modules,{"telegram":types.SimpleNamespace(InlineKeyboardButton=Button,InlineKeyboardMarkup=Markup)}):
            title,markup=studio_start_markup(["studio_market"])
        self.assertEqual(title,"Маркетплейсы")
        self.assertEqual(markup.inline_keyboard[0][0].callback_data,"ent:brief:product_ad")
