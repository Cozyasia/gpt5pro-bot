from dataclasses import FrozenInstanceError
import unittest


from music_video_scene_plan import (
    SceneContract,
    ScenePlan,
    chunk_review_messages,
    render_scene_plan_review,
    scene_plan_from_dict,
    scene_plan_from_explicit_timeline,
)


MUSIC_BRIEF = (
    "Русский уличный рэп, мужской вокал. Короткое тёмное инструментальное "
    "вступление без вокала, после него начинается мужской рэп."
)

VIDEO_BRIEF = """Длительность клипа: 30 секунд.
0–10 секунд: герой в лифте убирает телефон в карман, двери открываются, он выходит и идёт по коридору. Камера сначала показывает лицо, затем переходит в 3/4 и профиль.
10–20 секунд: герой продолжает движение, выходит на солнечную улицу и подходит к ярко-оранжевому Lamborghini Urus.
20–30 секунд: брюнетка остаётся на переднем правом пассажирском сиденье с открытой сумкой Louis Vuitton и пачками долларов. Герой открывает левую водительскую дверь и садится за руль; автомобиль стоит.
"""


def control_payload():
    return {
        "duration_s": 30,
        "aspect": "3:4",
        "vocal_start_s": 2.0,
        "scenes": [
            {
                "index": 1,
                "start_s": 0,
                "end_s": 10,
                "action": "Убрать телефон в карман один раз, выйти из лифта и идти по коридору; камера проходит от фронта к 3/4 и профилю.",
                "start_state": "Герой внутри лифта, телефон в руке, двери закрыты.",
                "end_state": "Телефон в кармане, обе руки свободны, герой идёт по коридору вне лифта.",
                "world_state": ["location=corridor", "phone=in_pocket", "hands=free", "elevator=completed"],
                "completed_actions": [],
                "future_count": 2,
                "lip_sync_start_s": 2.0,
                "lip_sync_end_s": 6.0,
            },
            {
                "index": 2,
                "start_s": 10,
                "end_s": 20,
                "action": "Продолжить движение из коридора, выйти на улицу и подойти к оранжевому Lamborghini Urus.",
                "start_state": "Герой идёт по коридору, телефон остаётся в кармане.",
                "end_state": "Герой снаружи возле водительской стороны Urus.",
                "world_state": ["location=street", "phone=in_pocket", "vehicle=orange_urus", "driver=protagonist"],
                "completed_actions": ["Телефон убран", "Выход из лифта завершён"],
                "future_count": 1,
                "lip_sync_start_s": None,
                "lip_sync_end_s": None,
            },
            {
                "index": 3,
                "start_s": 20,
                "end_s": 30,
                "action": "Сохранить брюнетку справа с сумкой; открыть левую водительскую дверь и сесть за руль.",
                "start_state": "Брюнетка уже справа на пассажирском сиденье; герой снаружи у левой двери.",
                "end_state": "Герой за рулём слева, брюнетка пассажир справа, сумка и деньги остаются у неё, автомобиль стоит.",
                "world_state": ["driver=protagonist", "passenger=brunette_right", "bag=passenger_lap", "vehicle=stationary"],
                "completed_actions": ["Телефон убран", "Выход из лифта завершён", "Подход к Urus завершён"],
                "future_count": 0,
                "lip_sync_start_s": 22.0,
                "lip_sync_end_s": 28.0,
            },
        ],
    }


class ScenePlanDomainTests(unittest.TestCase):
    def test_scene_plan_is_frozen_and_preserves_control_case_state(self):
        plan = scene_plan_from_dict(control_payload(), expected_duration_s=30, expected_aspect="3:4")

        self.assertIsInstance(plan, ScenePlan)
        self.assertEqual((1, 2, 3), tuple(scene.index for scene in plan.scenes))
        self.assertIn("phone=in_pocket", plan.scenes[0].world_state)
        self.assertIn("driver=protagonist", plan.scenes[2].world_state)
        self.assertIn("passenger=brunette_right", plan.scenes[2].world_state)
        self.assertIn("bag=passenger_lap", plan.scenes[2].world_state)
        with self.assertRaises(FrozenInstanceError):
            plan.duration_s = 60
        with self.assertRaises(FrozenInstanceError):
            plan.scenes[0].action = "restart elevator"

    def test_validation_rejects_timeline_gaps_and_short_lipsync_ranges(self):
        payload = control_payload()
        payload["scenes"][1]["start_s"] = 11
        with self.assertRaisesRegex(ValueError, "contiguous"):
            scene_plan_from_dict(payload, expected_duration_s=30, expected_aspect="3:4")

        payload = control_payload()
        payload["scenes"][0]["lip_sync_end_s"] = 3.5
        with self.assertRaisesRegex(ValueError, "2 to 10 seconds"):
            scene_plan_from_dict(payload, expected_duration_s=30, expected_aspect="3:4")

    def test_validation_rejects_stale_duration_or_aspect(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            scene_plan_from_dict(control_payload(), expected_duration_s=60, expected_aspect="3:4")
        with self.assertRaisesRegex(ValueError, "aspect"):
            scene_plan_from_dict(control_payload(), expected_duration_s=30, expected_aspect="9:16")

    def test_explicit_timeline_maps_one_to_one_without_repeating_full_story(self):
        plan = scene_plan_from_explicit_timeline(
            VIDEO_BRIEF,
            duration_s=30,
            aspect="3:4",
            wants_vocals=True,
            vocal_start_s=2.0,
        )

        self.assertEqual(3, len(plan.scenes))
        self.assertIn("лифте", plan.scenes[0].action)
        self.assertNotIn("Lamborghini", plan.scenes[0].action)
        self.assertIn("Lamborghini", plan.scenes[1].action)
        self.assertNotIn("брюнетка", plan.scenes[1].action)
        self.assertIn("брюнетка", plan.scenes[2].action)
        self.assertEqual((0.0, 10.0), (plan.scenes[0].start_s, plan.scenes[0].end_s))

    def test_review_is_lossless_and_uses_exact_plan_scenes(self):
        plan = scene_plan_from_dict(control_payload(), expected_duration_s=30, expected_aspect="3:4")
        long_tail = "ФИНАЛЬНОЕ УСЛОВИЕ " + ("не терять реквизит; " * 260)
        video_brief = VIDEO_BRIEF + long_tail

        review = render_scene_plan_review(plan, MUSIC_BRIEF, video_brief)
        chunks = chunk_review_messages(review, limit=3900)

        self.assertIn(long_tail.strip(), review)
        self.assertIn(plan.scenes[0].action, review)
        self.assertIn(plan.scenes[2].end_state, review)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))
        self.assertEqual(review, "".join(chunks))

    def test_vocal_plan_requires_at_least_one_lipsync_interval(self):
        payload = control_payload()
        for scene in payload["scenes"]:
            scene["lip_sync_start_s"] = None
            scene["lip_sync_end_s"] = None
        with self.assertRaisesRegex(ValueError, "lip-sync interval"):
            scene_plan_from_dict(
                payload,
                expected_duration_s=30,
                expected_aspect="3:4",
                require_lip_sync=True,
            )


if __name__ == "__main__":
    unittest.main()
