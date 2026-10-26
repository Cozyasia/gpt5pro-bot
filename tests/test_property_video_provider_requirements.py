import os
import unittest
from unittest.mock import patch

from property_video_execution import _require_provider


class PropertyVideoProviderRequirementTests(unittest.TestCase):
    def test_music_accepts_comet_key_used_by_suno_transport(self):
        env = {
            "COMET_API_KEY": "comet-key",
            "OPENAI_TTS_KEY": "tts-key",
        }
        with patch.dict(os.environ, env, clear=True):
            _require_provider("kling", "both")


if __name__ == "__main__":
    unittest.main()
