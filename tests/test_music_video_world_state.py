import ast
from pathlib import Path
import re
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"

CONTROL_BRIEF = """Длительность клипа: 30 секунд.
0–10 секунд: главный герой находится в лифте, убирает телефон, двери открываются, он выходит. Камера показывает лицо, затем плавно переходит к боковому ракурсу.
10–20 секунд: герой продолжает движение по коридору, выходит на солнечную улицу и подходит к ярко-оранжевому Lamborghini Urus.
20–30 секунд: в машине уже сидит взрослая брюнетка на правом переднем пассажирском сиденье. На её коленях открытая сумка Louis Vuitton с пачками долларов. Главный герой открывает левую водительскую дверь и садится за руль. В финале оба находятся внутри машины, автомобиль стоит.

Обязательные условия: один и тот же главный герой; никаких повторных выходов из лифта; никакой смены водителя и пассажира; реквизит не исчезает.
"""


def load_director_functions():
    names = {
        "_music_video_story_beats",
        "_music_video_world_state_ledger",
        "_vocal_scene_role_prompt",
    }
    nodes = [
        node
        for node in ast.parse(MAIN.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    env = {"re": re}
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"),
        env,
    )
    return env


class MusicVideoWorldStateTests(unittest.TestCase):
    def test_timestamped_blocks_map_one_to_one_without_repeating_the_whole_story(self):
        env = load_director_functions()
        beats = env["_music_video_story_beats"](CONTROL_BRIEF, 3)

        self.assertEqual(3, len(beats))
        self.assertIn("лифте", beats[0])
        self.assertNotIn("Lamborghini", beats[0])
        self.assertIn("Lamborghini", beats[1])
        self.assertNotIn("брюнетка", beats[1])
        self.assertIn("брюнетка", beats[2])
        self.assertNotIn("Обязательные условия", beats[2])

    def test_future_people_props_and_locations_are_hidden_until_their_scene(self):
        env = load_director_functions()
        prompt = env["_vocal_scene_role_prompt"](CONTROL_BRIEF, {"mode": "solo"}, 1, 3)

        self.assertIn("CURRENT ACTION", prompt)
        self.assertIn("лифте", prompt)
        self.assertNotIn("Lamborghini", prompt)
        self.assertNotIn("брюнетка", prompt)
        self.assertNotIn("Louis Vuitton", prompt)
        self.assertIn("UNOPENED FUTURE: 2", prompt)

    def test_completed_actions_are_ledger_history_and_cannot_restart(self):
        env = load_director_functions()
        prompt = env["_vocal_scene_role_prompt"](CONTROL_BRIEF, {"mode": "solo"}, 2, 3)

        self.assertIn("COMPLETED ACTIONS (history only; never replay)", prompt)
        self.assertIn("убирает телефон", prompt)
        self.assertIn("Lamborghini", prompt)
        self.assertNotIn("брюнетка", prompt)
        self.assertIn("do not restart the story", prompt)

    def test_final_scene_preserves_seats_props_and_stationary_end_state(self):
        env = load_director_functions()
        prompt = env["_vocal_scene_role_prompt"](CONTROL_BRIEF, {"mode": "solo"}, 3, 3)

        self.assertIn("брюнетка", prompt)
        self.assertIn("правом переднем пассажирском", prompt)
        self.assertIn("Louis Vuitton", prompt)
        self.assertIn("левую водительскую дверь", prompt)
        self.assertIn("автомобиль стоит", prompt)
        self.assertIn("seat assignments", prompt)
        self.assertIn("prop ownership", prompt)
        self.assertIn("UNOPENED FUTURE: 0", prompt)
        self.assertLessEqual(len(prompt), 2200)


if __name__ == "__main__":
    unittest.main()
