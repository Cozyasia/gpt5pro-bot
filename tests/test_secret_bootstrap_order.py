from pathlib import Path
import unittest


class SecretBootstrapOrderTests(unittest.TestCase):
    def test_bootstrap_precedes_provider_imports(self):
        source = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
        self.assertLess(source.index('bootstrap_secret_environment()'), source.index('from video_studio import'))
        self.assertLess(source.index('bootstrap_secret_environment()'), source.index('from music_video_scene_plan import'))


if __name__ == '__main__':
    unittest.main()
