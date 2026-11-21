import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from neyrobot_prod import bootstrap,jobs
class StartupTest(unittest.IsolatedAsyncioTestCase):
 async def test_long_running_recovery_does_not_block_application_startup(self):
  gate=asyncio.Event(); started=asyncio.Event()
  async def recover(*args):started.set();await gate.wait()
  app=SimpleNamespace(bot_data={});mod=SimpleNamespace()
  with patch.object(bootstrap,'_runtime_module',return_value=mod),patch.object(jobs,'recover_pending',side_effect=recover),patch.object(jobs,'patch_runtime',return_value=True):
   await asyncio.wait_for(bootstrap._post_init_recovery(app),timeout=.3)
   await asyncio.wait_for(started.wait(),timeout=.3)
   task=app.bot_data['_neyronix_recovery_task'];self.assertFalse(task.done())
   task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
