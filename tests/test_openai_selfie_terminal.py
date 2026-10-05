# -*- coding: utf-8 -*-
"""Selfie job behavior at the image API and Telegram delivery boundaries."""
import asyncio
import base64
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class TimedOut(Exception):
    pass


class NetworkError(Exception):
    pass


class ApplicationHandlerStop(Exception):
    pass


class Message:
    def __init__(self):
        self.texts = []
        self.documents = []
        self.timeout_text = None
        self.timeout_document = False

    async def reply_text(self, value, **kwargs):
        if self.timeout_text and self.timeout_text in value:
            self.timeout_text = None
            raise TimedOut("Timed out")
        self.texts.append(value)
        return types.SimpleNamespace(message_id=100 + len(self.texts))

    async def reply_document(self, document, **kwargs):
        self.documents.append((document.getvalue(), document.name, kwargs))
        if self.timeout_document:
            raise TimedOut("Timed out")
        return types.SimpleNamespace(message_id=200 + len(self.documents))


class Context:
    def __init__(self):
        self.user_data = {
            "openai_selfie_active": True,
            "openai_selfie_photo": b"p" * 1200,
            "openai_selfie_hero": "hero_a",
        }


class Update:
    def __init__(self, msg, data=None):
        self.effective_message = msg
        self.effective_user = types.SimpleNamespace(id=123)
        self.callback_query = None
        if data:
            async def answer():
                pass
            self.callback_query = types.SimpleNamespace(
                data=data, message=msg, answer=answer, id="callback-1"
            )


def load_lane():
    package = types.ModuleType("neyrobot_prod")
    package.__path__ = [str(ROOT / "neyrobot_prod")]
    base = types.ModuleType("neyrobot_prod.celebrity_selfie")
    base.CHARACTERS = {
        "hero_a": {"name": "Герой А", "required_refs": 3, "country": "ru"},
        "hero_b": {"name": "Герой Б", "required_refs": 3, "country": "ru"},
    }
    base.SCENES = {"park": ("Парк", "A quiet park scene")}
    catalog = types.ModuleType("neyrobot_prod.selfie_v208_overlay")
    catalog.COUNTRIES = {"ru": ("Россия", "Россия")}
    package.celebrity_selfie = base
    package.selfie_v208_overlay = catalog
    telegram = types.ModuleType("telegram")
    ext = types.ModuleType("telegram.ext")
    ext.ApplicationHandlerStop = ApplicationHandlerStop
    error = types.ModuleType("telegram.error")
    error.TimedOut = TimedOut
    error.NetworkError = NetworkError
    httpx = types.ModuleType("httpx")
    httpx.Timeout = lambda *a, **kw: None
    names = {
        "neyrobot_prod": package,
        "neyrobot_prod.celebrity_selfie": base,
        "neyrobot_prod.selfie_v208_overlay": catalog,
        "telegram": telegram,
        "telegram.ext": ext,
        "telegram.error": error,
        "httpx": httpx,
    }
    with patch.dict(sys.modules, names):
        spec = importlib.util.spec_from_file_location(
            "neyrobot_prod.openai_selfie_exp_v1",
            ROOT / "neyrobot_prod" / "openai_selfie_exp_v1.py",
        )
        lane = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lane)
    return lane, base


class SelfieTerminalTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lane, self.base = load_lane()
        self.real_edit = self.lane._openai_edit
        self.mod = types.SimpleNamespace(
            InlineKeyboardButton=lambda label, callback_data: types.SimpleNamespace(
                text=label, callback_data=callback_data
            ),
            InlineKeyboardMarkup=lambda rows: types.SimpleNamespace(inline_keyboard=rows),
            AI_SELFIE_UNIT_COST_USD=0.20,
        )
        self.runner_failures = []
        self.edits = []
        self.edit_error = None
        self.msg = Message()
        self.context = Context()
        self.update = Update(self.msg)

        async def edit(photo, slug, scene, scene_photo=b""):
            self.edits.append((photo, slug, scene, scene_photo))
            if self.edit_error:
                raise self.edit_error
            return b"PNG" * 1000

        async def runner(update, context, uid, engine, price, action, **kwargs):
            ok = await action()
            if not ok and not kwargs.get("silent_failure"):
                self.msg.texts.append("❌ Задача не выполнена. Попробуйте позже.")
            return ok

        self.mod._try_pay_then_do = runner
        self.patches = [
            patch.object(self.lane, "_runtime", return_value=self.mod),
            patch.object(self.lane, "_hero_refs", return_value=[Path("a"), Path("b"), Path("c")]),
            patch.object(self.lane, "_openai_edit", side_effect=edit),
            patch.dict(sys.modules, {
                "neyrobot_prod": types.SimpleNamespace(
                    celebrity_selfie=self.base,
                    selfie_v208_overlay=sys.modules.get("neyrobot_prod.selfie_v208_overlay")
                    or types.SimpleNamespace(COUNTRIES={"ru": ("Россия", "Россия")}),
                ),
                "telegram.ext": types.SimpleNamespace(ApplicationHandlerStop=ApplicationHandlerStop),
                "telegram.error": types.SimpleNamespace(TimedOut=TimedOut, NetworkError=NetworkError),
            }),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    async def generate(self):
        return await self.lane._generate(self.update, self.context, "A quiet park scene")

    async def test_progress_send_timeout_does_not_abort_image_request(self):
        self.msg.timeout_text = "создаю селфи"
        await self.generate()
        self.assertEqual(len(self.edits), 1)
        self.assertEqual(len(self.msg.documents), 1)
        self.assertFalse(any("Не удалось" in s or "Задача не выполнена" in s for s in self.msg.texts))

    async def test_control_message_timeout_cannot_reclassify_delivered_image_as_failure(self):
        self.msg.timeout_text = "Можно повторить"
        await self.generate()
        self.assertEqual(len(self.msg.documents), 1)
        self.assertFalse(any("Не удалось" in s or "Задача не выполнена" in s for s in self.msg.texts))

    async def test_ambiguous_document_timeout_is_never_retried_or_reported_as_definite_failure(self):
        self.msg.timeout_document = True  # Telegram accepted the file before the client timed out.
        await self.generate()
        self.assertEqual(len(self.edits), 1)
        self.assertEqual(len(self.msg.documents), 1)
        self.assertFalse(any("Не удалось" in s or "Задача не выполнена" in s for s in self.msg.texts))

    async def test_network_disconnect_during_delivery_is_also_uncertain(self):
        async def disconnected(document, **kwargs):
            self.msg.documents.append((document.getvalue(), document.name, kwargs))
            raise NetworkError("disconnected before response")
        self.msg.reply_document = disconnected
        await self.generate()
        self.assertEqual(len(self.msg.documents), 1)
        self.assertFalse(any("Не удалось" in s or "Задача не выполнена" in s for s in self.msg.texts))

    async def test_image_api_timeout_reports_one_failure_without_internal_exception(self):
        self.edit_error = TimeoutError("provider timed out")
        await self.generate()
        failures = [s for s in self.msg.texts if "Не удалось" in s or "Задача не выполнена" in s]
        self.assertEqual(len(failures), 1)
        self.assertNotIn("TimeoutError", failures[0])
        self.assertEqual(len(self.msg.documents), 0)

    async def test_double_tap_on_scene_starts_only_one_job(self):
        self.context.user_data["openai_selfie_scene_ready"] = True
        update = Update(self.msg, "oaiselfie:scene:park")
        for _ in range(2):
            with self.assertRaises(ApplicationHandlerStop):
                await self.lane.callback(update, self.context)
        self.assertEqual(len(self.edits), 1)
        self.assertEqual(len(self.msg.documents), 1)

    async def test_repeating_same_photo_and_changing_hero_are_separate_jobs(self):
        self.context.user_data["openai_selfie_scene_ready"] = True
        for data in ("oaiselfie:scene:park", "oaiselfie:repeat", "oaiselfie:scene:park",
                     "oaiselfie:hero:hero_b", "oaiselfie:scene:park"):
            with self.assertRaises(ApplicationHandlerStop):
                await self.lane.callback(Update(self.msg, data), self.context)
        self.assertEqual([item[1] for item in self.edits], ["hero_a", "hero_a", "hero_b"])
        self.assertEqual(len(self.msg.documents), 3)

    async def test_custom_scene_photo_preserved_in_single_image_request(self):
        self.context.user_data["openai_selfie_scene_ready"] = True
        with self.assertRaises(ApplicationHandlerStop):
            await self.lane.callback(Update(self.msg, "oaiselfie:scene:custom"), self.context)
        with patch.object(self.lane, "_download_photo", return_value=b"s" * 1600):
            with self.assertRaises(ApplicationHandlerStop):
                await self.lane.media(self.update, self.context)
        self.assertEqual(len(self.edits), 1)
        self.assertEqual(self.edits[0][3], b"s" * 1600)
        self.assertEqual(len(self.msg.documents), 1)

    async def test_photo_outside_selfie_mode_remains_for_existing_handler(self):
        self.context.user_data["openai_selfie_active"] = False
        await self.lane.media(self.update, self.context)
        self.assertEqual(self.msg.texts, [])
        self.assertEqual(self.edits, [])

    async def test_slow_image_request_keeps_one_job_until_completion(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow(photo, slug, scene, scene_photo=b""):
            self.edits.append((photo, slug, scene, scene_photo))
            entered.set()
            await release.wait()
            return b"PNG" * 1000

        with patch.object(self.lane, "_openai_edit", side_effect=slow):
            task = asyncio.create_task(self.generate())
            await entered.wait()
            await asyncio.sleep(0.03)
            self.assertEqual(len(self.msg.documents), 0)
            self.assertFalse(any("Не удалось" in s for s in self.msg.texts))
            release.set()
            await task
        self.assertEqual(len(self.msg.documents), 1)

    async def test_front_facing_photo_is_forwarded_unchanged(self):
        self.context.user_data["openai_selfie_photo"] = b"front" * 300
        await self.generate()
        self.assertEqual(self.edits[0][0], b"front" * 300)

    async def test_image_edit_reference_order_for_preset_and_custom_scene(self):
        requests = []

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, headers, data, files):
                requests.append((url, data, files))
                return types.SimpleNamespace(
                    status_code=200,
                    json=lambda: {"data": [{"b64_json": base64.b64encode(b"PNG" * 1000).decode()}]},
                )

        with tempfile.TemporaryDirectory() as folder:
            refs = []
            for i in range(3):
                path = Path(folder) / f"hero_{i}.jpg"
                path.write_bytes(bytes([65+i]) * 1200)
                refs.append(path)
            with patch.object(self.lane, "_hero_refs", return_value=refs), \
                 patch.object(self.lane.httpx, "AsyncClient", return_value=Client(), create=True), \
                 patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                await self.real_edit(b"user" * 300, "hero_a", "A quiet park scene")
                await self.real_edit(b"user" * 300, "hero_b", "Custom", scene_photo=b"scene" * 300)

        self.assertEqual([item[2][0][1][0] for item in requests], ["user.jpg", "scene.jpg"])
        self.assertEqual([item[2][1][1][0] for item in requests], ["hero_1.jpg", "user.jpg"])
        self.assertEqual(len(requests[0][2]), 4)
        self.assertEqual(len(requests[1][2]), 5)

    async def test_job_log_correlates_request_and_terminal_without_input_data(self):
        with self.assertLogs("gpt-bot", level="INFO") as captured:
            await self.generate()
        lines = [s for s in captured.output if "SELFIE_JOB" in s]
        self.assertTrue(any("event=image_request_start" in s for s in lines))
        self.assertTrue(any("event=telegram_delivery_confirmed" in s for s in lines))
        self.assertTrue(any("event=terminal" in s and "state=SUCCESS" in s for s in lines))
        self.assertEqual(len({s.split("job=")[1].split()[0] for s in lines}), 1)
        self.assertNotIn("A quiet park scene", " ".join(lines))

    async def test_user_messages_do_not_expose_internal_names(self):
        await self.lane.command(self.update, self.context)
        combined = " ".join(self.msg.texts)
        for internal in ("OpenAI", "V265", "experimental", "direct-edit", "TimedOut"):
            self.assertNotIn(internal, combined)
