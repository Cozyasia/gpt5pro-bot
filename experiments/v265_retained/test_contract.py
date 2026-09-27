import unittest,json,hashlib
from pathlib import Path
import numpy as np
from experiments.v265_mouth.component import build,IDENTITIES
from experiments.v265_commissure.candidates import anchor_weights
from .admission import coplanar_overlap
class Contracts(unittest.TestCase):
 def test_mouth_frozen(self):
  r=json.loads(Path(__file__).with_name('mouth-positive.json').read_text())
  for p,h in r['files'].items():self.assertEqual(hashlib.sha256(Path(p).read_bytes()).hexdigest(),h)
  for name,p in IDENTITIES.items():self.assertEqual(hashlib.sha256(anchor_weights(build(**p)).tobytes()).hexdigest(),r['weights'][name])
 def test_coplanar(self):
  v=np.array([[0,0,0],[1,0,0],[0,1,0],[.1,.1,0],[1.1,.1,0],[.1,1.1,0]],float);tr=np.arange(6).reshape(2,3)
  self.assertTrue(coplanar_overlap(v,tr,[0,1]));v[3:]+=np.array([2,2,0]);self.assertFalse(coplanar_overlap(v,tr,[0,1]))
if __name__=='__main__':unittest.main()
