import asyncio,sqlite3,os,tempfile,subprocess
from pathlib import Path
from tests.test_promo_attempt_wiring import PromoWiringTests
from neyrobot_prod.kling_finance_scope import OutcomeUnknown,current
class PromoUnknownTest(PromoWiringTests):
 def setUp(self):
  root=Path(__file__).resolve().parents[1]
  self.patched_tmp=tempfile.TemporaryDirectory();target=Path(self.patched_tmp.name)/'main.py';target.write_bytes((root/'main.py').read_bytes())
  for name in ('main_kling_billing_failures.patch','main_promo_attempts_v1.patch','main_kling_no_duplicate.patch','main_kling_aspect_delivery.patch','main_kling_delivery_claim.patch','main_kling_finance_recovery.patch'):
   subprocess.run(['patch','--batch','-p1','-i',str(root/'ops'/name)],cwd=self.patched_tmp.name,check=True,stdout=subprocess.DEVNULL)
  self.previous_source=os.environ.get('PROMO_TEST_SOURCE');os.environ['PROMO_TEST_SOURCE']=str(target)
  import tests.test_promo_attempt_wiring as promo_tests
  self.previous_constant=promo_tests.SOURCE;promo_tests.SOURCE=target
  super().setUp()
 def tearDown(self):
  super().tearDown();self.patched_tmp.cleanup()
  import tests.test_promo_attempt_wiring as promo_tests
  promo_tests.SOURCE=self.previous_constant
  if self.previous_source is None:os.environ.pop('PROMO_TEST_SOURCE',None)
  else:os.environ['PROMO_TEST_SOURCE']=self.previous_source
 def test_unknown_keeps_actual_reservation_and_surfaces_warning(self):
  async def provider():
   self.assertEqual(current()['kind'],'promo')
   raise OutcomeUnknown()
  asyncio.run(self.env['_try_pay_then_do'](self.update,self.context,42,'kling',1,provider,remember_kind='image_to_video_kling'))
  self.assertEqual(self.count(),1)
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM promo_attempts').fetchone()[0],'reserved')
  self.assertIn('сохранена',self.update.effective_message.reply_text.await_args.args[0])
