import ast,asyncio,json,logging,time,unittest,tempfile,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'main.py'
class Tests(unittest.TestCase):
 def setUp(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'main.py';p.write_bytes(P.read_bytes())
   subprocess.run(['patch','--batch','-p1','-i',str(ROOT/'ops/main_kling_billing_failures.patch')],cwd=td,check=True,stdout=subprocess.DEVNULL)
   source=p.read_text()
  tree=ast.parse(source); names={'_create_and_poll_i2v','_poll_video_task_generic'}
  funcs=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in names]
  self.ns={'__name__':'test', 'time':time,'json':json,'asyncio':asyncio,'log':logging.getLogger('test'),'Update':object,'httpx':SimpleNamespace(AsyncClient=object),'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'_api_error_preview':lambda r:'','_extract_first_url':lambda v:None,'_is_unsupported_relay_mode_error':lambda x:False}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*funcs],type_ignores=[])),str(P),'exec'),self.ns)
  self.update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
 def test_kling_missing_api_key_is_unsuccessful(self):
  out=asyncio.run(self.ns['_create_and_poll_i2v'](self.update,'https://example.invalid','',[],[],'Kling image→video'))
  self.assertIs(out,False)
 def test_kling_failed_task_is_unsuccessful(self):
  response=SimpleNamespace(status_code=200,json=lambda:{'status':'failed','data':{'task_status_msg':'failure'}})
  client=SimpleNamespace(get=AsyncMock(return_value=response))
  out=asyncio.run(self.ns['_poll_video_task_generic'](self.update,client,{},'https://example.invalid',['/task/{id}'],'1','Kling image→video'))
  self.assertIs(out,False)
 def test_kling_completed_without_video_is_unsuccessful(self):
  response=SimpleNamespace(status_code=200,json=lambda:{'status':'completed'})
  client=SimpleNamespace(get=AsyncMock(return_value=response))
  out=asyncio.run(self.ns['_poll_video_task_generic'](self.update,client,{},'https://example.invalid',['/task/{id}'],'1','Kling image→video'))
  self.assertIs(out,False)
 def test_kling_successful_delivery_is_successful(self):
  response=SimpleNamespace(status_code=200,json=lambda:{'status':'completed','output':'https://example.invalid/result.mp4'})
  client=SimpleNamespace(get=AsyncMock(return_value=response))
  self.ns['_extract_first_url']=lambda v: v if isinstance(v,str) else None
  deliver=AsyncMock();self.ns['_reply_video_from_url']=deliver
  out=asyncio.run(self.ns['_poll_video_task_generic'](self.update,client,{},'https://example.invalid',['/task/{id}'],'1','Kling image→video'))
  self.assertIs(out,True);deliver.assert_awaited_once()
if __name__=='__main__':unittest.main()
