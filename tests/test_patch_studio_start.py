import ast
import unittest
from scripts.patch_studio_start import patch

SOURCE = 'async def cmd_start(update, context):\n    if not _claim_start_update(update):\n        return\n    if await _handle_payment_start_payload(update, context):\n        return\n    await update.effective_chat.send_message(START_TEXT)\n'

class PatchStartTests(unittest.TestCase):
    def test_payment_precedes_studio(self):
        result = patch(SOURCE)
        ast.parse(result)
        self.assertLess(result.index('if await _handle_payment_start_payload'), result.index('studio_start_markup(context.args)'))
        self.assertLess(result.index('studio_start_markup(context.args)'), result.index('START_TEXT'))

    def test_refuses_double_patch(self):
        with self.assertRaises(ValueError):
            patch(patch(SOURCE))

    def test_duplicate_definitions_target_final_active_handler(self):
        legacy = 'async def cmd_start(update, context):\n    if await _handle_payment_start_payload(update, context):\n        return\n    await update.effective_chat.send_message(OLD_START)\n\n'
        result = patch(legacy + SOURCE)
        self.assertEqual(result.count('studio_start_markup(context.args)'), 1)
        self.assertLess(result.index('OLD_START'), result.index('studio_start_markup(context.args)'))

    def test_refuses_unguarded_legacy_handler(self):
        legacy = 'async def cmd_start(update, context):\n    if await _handle_payment_start_payload(update, context):\n        return\n'
        with self.assertRaises(ValueError):
            patch(legacy)
