# -*- coding: utf-8 -*-
import asyncio
from io import BytesIO
import os
from types import SimpleNamespace
import unittest

from PIL import Image, ImageDraw

import celebrity_selfie_v131 as v131


def portrait_bytes():
    image = Image.new("RGB", (900, 1200), (120, 100, 90))
    draw = ImageDraw.Draw(image)
    for x in range(0, 900, 18):
        draw.line((x, 0, 900 - x // 2, 1200), fill=(35 + x % 180, 85, 145), width=4)
    draw.ellipse((275, 175, 625, 600), fill=(210, 170, 140), outline=(20, 20, 20), width=7)
    draw.ellipse((355, 320, 395, 360), fill=(0, 0, 0))
    draw.ellipse((505, 320, 545, 360), fill=(0, 0, 0))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class _Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))


class CelebritySelfieV131Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(
            v131.VERSION,
            "v131-celebrity-selfie-tolerant-face-preflight-2026-07-19",
        )

    def test_good_photo_is_accepted_when_local_detector_returns_zero(self):
        message = _Message()
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=777),
        )
        context = SimpleNamespace(user_data={})
        called = {"accepted": False}
        old_count = v131.impl._face_count
        old_accept = v131.impl._ORIGINAL_ACCEPT_USER_PHOTO
        old_strict = os.environ.pop("CELEBRITY_FACE_DETECTOR_STRICT", None)

        async def zero_faces(raw):
            return 0

        async def accepted(update_arg, context_arg, raw):
            called["accepted"] = bool(raw)

        v131.impl._face_count = zero_faces
        v131.impl._ORIGINAL_ACCEPT_USER_PHOTO = accepted
        try:
            asyncio.run(v131._accept_user_photo(update, context, portrait_bytes()))
        finally:
            v131.impl._face_count = old_count
            v131.impl._ORIGINAL_ACCEPT_USER_PHOTO = old_accept
            if old_strict is not None:
                os.environ["CELEBRITY_FACE_DETECTOR_STRICT"] = old_strict

        self.assertTrue(called["accepted"])
        self.assertEqual(message.sent, [])
        session = v131.core._session(context)
        self.assertTrue(session["selfie_quality"]["accepted"])
        self.assertEqual(session["selfie_quality"]["detector_warning"], "local_detector_miss")
        self.assertEqual(
            session["selfie_quality"]["gate"],
            "image_quality_hard_face_detector_advisory",
        )

    def test_strict_mode_can_still_reject_detector_miss(self):
        message = _Message()
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=778),
        )
        context = SimpleNamespace(user_data={})
        called = {"accepted": False}
        old_count = v131.impl._face_count
        old_accept = v131.impl._ORIGINAL_ACCEPT_USER_PHOTO
        old_strict = os.environ.get("CELEBRITY_FACE_DETECTOR_STRICT")

        async def zero_faces(raw):
            return 0

        async def accepted(update_arg, context_arg, raw):
            called["accepted"] = True

        v131.impl._face_count = zero_faces
        v131.impl._ORIGINAL_ACCEPT_USER_PHOTO = accepted
        os.environ["CELEBRITY_FACE_DETECTOR_STRICT"] = "1"
        try:
            asyncio.run(v131._accept_user_photo(update, context, portrait_bytes()))
        finally:
            v131.impl._face_count = old_count
            v131.impl._ORIGINAL_ACCEPT_USER_PHOTO = old_accept
            if old_strict is None:
                os.environ.pop("CELEBRITY_FACE_DETECTOR_STRICT", None)
            else:
                os.environ["CELEBRITY_FACE_DETECTOR_STRICT"] = old_strict

        self.assertFalse(called["accepted"])
        self.assertTrue(message.sent)
        self.assertIn("лицо не распознано", message.sent[0][0])

    def test_successful_identity_provider_result_is_not_discarded_by_local_miss(self):
        raw = portrait_bytes()
        old_task = v131.impl._piapi_task
        old_count = v131.impl._face_count
        old_strict = os.environ.pop("CELEBRITY_FACE_DETECTOR_STRICT", None)

        async def task(mod, task_type, inputs):
            self.assertEqual(task_type, "multi-face-swap")
            return raw

        async def zero_faces(result):
            return 0

        v131.impl._piapi_task = task
        v131.impl._face_count = zero_faces
        try:
            result = asyncio.run(v131._identity_lock(object(), raw, raw, raw))
        finally:
            v131.impl._piapi_task = old_task
            v131.impl._face_count = old_count
            if old_strict is not None:
                os.environ["CELEBRITY_FACE_DETECTOR_STRICT"] = old_strict

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
