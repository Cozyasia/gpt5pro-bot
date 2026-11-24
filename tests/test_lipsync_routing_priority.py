import ast, unittest
from test_seedance_aspect_selection import patched_source

class LipSyncRoutingTests(unittest.TestCase):
 def test_text_handler_has_priority_over_medical_text_handler(self):
  tree=ast.parse(patched_source())
  matches=[]
  for node in ast.walk(tree):
   if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr!='add_handler' or not node.args: continue
   handler=node.args[0]
   if isinstance(handler,ast.Call) and len(handler.args)>1 and isinstance(handler.args[1],ast.Name) and handler.args[1].id=='on_direct_lipsync_text':
    matches.append(next((ast.literal_eval(k.value) for k in node.keywords if k.arg=='group'),0))
  self.assertTrue(matches)
  self.assertLess(min(matches),-4,'medical text handler also occupies group -4 and wins first match')
 def test_mode_cleanup_includes_direct_lipsync_state(self):
  tree=ast.parse(patched_source())
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_clear_transient_flows')
  literals={n.value for n in ast.walk(fn) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
  self.assertTrue({'direct_lipsync_stage','direct_lipsync_video_bytes','direct_lipsync_image_bytes','direct_lipsync_image_name'} <= literals)
