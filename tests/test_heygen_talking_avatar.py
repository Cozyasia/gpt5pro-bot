# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from neyrobot_prod.heygen_talking_avatar import (
    avatar_from_api,
    build_talking_avatar_payload,
    selection_key,
    voice_from_api,
    select_vertical_look,
)


class HeyGenTalkingAvatarTests(unittest.TestCase):
    def test_catalog_records_keep_provider_ids_and_preview_urls(self) -> None:
        avatar = avatar_from_api({
            "avatar_id": "avatar-123",
            "name": "Aya",
            "gender": "female",
            "preview_image_url": "https://cdn.example/aya.jpg",
        })
        voice = voice_from_api({
            "voice_id": "voice-123",
            "name": "Rex - Serious",
            "language": "Multilingual",
            "gender": "male",
            "preview_audio_url": "https://cdn.example/rex.wav",
        })

        self.assertEqual(avatar.avatar_id, "avatar-123")
        self.assertTrue(avatar.preview_image_url.endswith("aya.jpg"))
        self.assertEqual(voice.voice_id, "voice-123")
        self.assertTrue(voice.preview_audio_url.endswith("rex.wav"))

    def test_group_avatar_prefers_a_vertical_look(self) -> None:
        base = avatar_from_api({"avatar_id": "base", "name": "Aya", "group_id": "group-1"})
        look = select_vertical_look(base, {
            "data": {"looks": [
                {"avatar_id": "landscape", "name": "Aya wide", "aspect_ratio": "16:9"},
                {"avatar_id": "portrait", "name": "Aya portrait", "aspect_ratio": "9:16"},
            ]}
        })
        self.assertEqual(look.avatar_id, "portrait")

    def test_video_payload_uses_the_user_selected_avatar_and_voice(self) -> None:
        payload = build_talking_avatar_payload(
            avatar_id="avatar-123",
            voice_id="voice-123",
            script="Здравствуйте!",
            title="Neyro-Bot Studio",
        )

        self.assertEqual(payload["avatar_id"], "avatar-123")
        self.assertEqual(payload["voice_id"], "voice-123")
        self.assertEqual(payload["aspect_ratio"], "9:16")
        self.assertNotEqual(selection_key(101), selection_key(202))


if __name__ == "__main__":
    unittest.main()
