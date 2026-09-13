import unittest,json,hashlib
from pathlib import Path
import numpy as np
from .closure import deform
from experiments.v265_retained.surface import build
class TestClosure(unittest.TestCase):
 def test_neutral_immutable(self):
  t=build();r=json.loads(Path(__file__).with_name('neutral-positive.json').read_text())
  self.assertEqual(hashlib.sha256(t['vertices'].tobytes()).hexdigest(),r['vertices']);self.assertEqual(hashlib.sha256(t['triangles'].tobytes()).hexdigest(),r['topology'])
  for c in ('E','F'):
   np.testing.assert_array_equal(deform(c,0)['vertices'],t['vertices'])
   d=deform(c,1);mask=t['labels']!='eyelid';np.testing.assert_array_equal(d['vertices'][mask],t['vertices'][mask]);np.testing.assert_array_equal(d['triangles'],t['triangles'])
 def test_invalid(self):
  with self.assertRaises(ValueError):deform('E',1.1)
if __name__=='__main__':unittest.main()
