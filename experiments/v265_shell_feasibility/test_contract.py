import unittest,json
from pathlib import Path
import numpy as np
from .analyze import ray
class Contracts(unittest.TestCase):
 def test_ray_witness(self):
  v=np.array([[-1,-1,2],[1,-1,2],[0,1,2]],float);tr=np.array([[0,1,2]])
  r=ray(np.zeros(3),np.array([0,0,1]),v,tr,[]);self.assertAlmostEqual(r['metres'],2)
  self.assertIsNone(ray(np.zeros(3),np.array([0,0,-1]),v,tr,[]))
 def test_bad_normal_direction_blocks_construction(self):
  from .analyze import fields
  _,rows=fields();bad=[r for r in rows if not r['direction_feasible']]
  self.assertEqual(len(bad),19);self.assertTrue(any(r['vertex']==1720 and r['incident_normal_dot_min']<-.3 for r in bad))
 def test_predeclared_contract(self):
  c=json.loads(Path(__file__).with_name('contract.json').read_text())
  self.assertGreater(c['thickness_min_m'],0);self.assertGreater(c['inner_globe_min_m'],0)
  self.assertEqual(c['proper_crossings_max'],0);self.assertEqual(c['exterior_deviation_m'],0)
if __name__=='__main__':unittest.main()
