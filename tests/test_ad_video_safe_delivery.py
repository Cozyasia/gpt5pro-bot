import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from neyrobot_prod.ad_video_safe_delivery import deliver_once, DeliveryUncertain, delivery_state

class SafeDeliveryTests(unittest.TestCase):
    def test_success_sends_once(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"delivery.json"
            calls=[]
            async def send():
                calls.append(1)
                return SimpleNamespace(message_id=42)
            self.assertEqual(asyncio.run(deliver_once(p,send)),42)
            self.assertEqual(asyncio.run(deliver_once(p,send)),42)
            self.assertEqual(len(calls),1)

    def test_timeout_never_resends_automatically(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"delivery.json"
            calls=[]
            async def send():
                calls.append(1)
                raise TimeoutError()
            with self.assertRaises(DeliveryUncertain):
                asyncio.run(deliver_once(p,send))
            with self.assertRaises(DeliveryUncertain):
                asyncio.run(deliver_once(p,send))
            self.assertEqual(len(calls),1)
            self.assertEqual(delivery_state(p)["state"],"uncertain")

if __name__=="__main__":
    unittest.main()
