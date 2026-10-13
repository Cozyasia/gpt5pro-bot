"""No-charge regression tests for Veo multiscene continuity contract."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VeoContinuityTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for path in (
            ROOT / "main.py",
            ROOT / "neyrobot_prod/veo_scene_prompt.py",
            ROOT / "neyrobot_prod/veo_assembler.py",
        ):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_script_split_no_repetition(self):
        from neyrobot_prod.veo_multiscene import plan_video
        script = "Один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать"
        scenes = plan_video(30, script)
        self.assertEqual(len(scenes), 4)
        self.assertEqual(" ".join(x.spoken_text for x in scenes), script)

    def test_scene_beats_and_no_repeated_dialogue(self):
        from neyrobot_prod.veo_multiscene import plan_video
        from neyrobot_prod.veo_scene_prompt import scene_prompt
        scenes = plan_video(30, "Первая реплика. Вторая реплика. Третья реплика. Финал.")
        prompts = [scene_prompt(scene, "Финтех реклама") for scene in scenes]
        self.assertEqual(len(set(prompts)), 4)
        for scene, prompt in zip(scenes, prompts):
            self.assertIn(scene.spoken_text, prompt)
            self.assertIn("Speak these words ONCE only", prompt)
            self.assertIn("Do not invent on-screen words", prompt)
            self.assertIn("ONLY speech permitted", prompt)
            for other in scenes:
                if other.index != scene.index:
                    self.assertNotIn('The presenter says exactly in Russian: "' + other.spoken_text + '"', prompt)

    def test_ffmpeg_uses_low_memory_seamless_720p_default(self):
        source = (ROOT / "neyrobot_prod/veo_assembler.py").read_text(encoding="utf-8")
        for expected in ("width: int = 720", "height: int = 1280", '"-threads:v", "1"'):
            self.assertIn(expected, source)
        self.assertNotIn("fade=t=in", source)
        self.assertNotIn("afade=t=in", source)

    def test_preflight_before_charge(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        begin = source.index('    if engine == "veo" and duration > 8:')
        end = source.index('    provider_cost = _video_provider_cost_usd(engine, duration)', begin)
        self.assertIn("speech_match", source[begin:end])
        self.assertIn("plan_video(duration", source[begin:end])


if __name__ == "__main__":
    unittest.main()
