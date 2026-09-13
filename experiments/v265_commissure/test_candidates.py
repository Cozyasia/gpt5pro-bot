import unittest
import numpy as np
from experiments.v265_mouth.component import build,jaw_only
from .candidates import deform_d,deform_c,anchor_weights
from .audit import metrics

class Tests(unittest.TestCase):
 def test_positive_fixture(self):
  import json,hashlib
  from pathlib import Path
  from experiments.v265_mouth.component import IDENTITIES
  r=json.loads(Path(__file__).with_name('neutral-fixture.json').read_text())
  for name,p in IDENTITIES.items():
   t=build(**p);self.assertEqual(hashlib.sha256(t['vertices'].tobytes()).hexdigest(),r[name]['vertices_sha256']);self.assertEqual(hashlib.sha256(t['triangles'].tobytes()).hexdigest(),r[name]['triangles_sha256'])
 def test_neutral_bitexact(self):
  t=build();before=t['vertices'].copy();np.testing.assert_array_equal(deform_d(t,0),before);deform_d(t,1);np.testing.assert_array_equal(before,t['vertices'])
 def test_corner_anchors(self):
  t=build();w=anchor_weights(t);self.assertAlmostEqual(w[192],.5);self.assertAlmostEqual(w[224],.5);self.assertTrue(((w>=0)&(w<=1)).all())
 def test_dental_rigid(self):
  t=build();v=deform_d(t,1);n=t['vertices'];np.testing.assert_array_equal(v[t['teeth']['upper']],n[t['teeth']['upper']]);l=t['teeth']['lower'];np.testing.assert_allclose(np.linalg.norm(v[l]-v[l[0]],axis=1),np.linalg.norm(n[l]-n[l[0]],axis=1),atol=1e-15)
 def test_c_retains_negative(self):
  t=build(width=.018);v,n,tr=deform_c(t,1);self.assertGreater(metrics(v,n,tr)['edge_max'],15)
 def test_d_resolves_short_edge(self):
  t=build(width=.018);m=metrics(deform_d(t,1),t['vertices'],t['triangles']);self.assertLess(m['edge_max'],2)
if __name__=='__main__':unittest.main()
