import unittest,numpy as np
from .neutral import construct
from experiments.v265_retained.surface import build
class MaterialTests(unittest.TestCase):
 def test_frozen_exterior_and_correspondence(self):
  n=build();t=construct();np.testing.assert_array_equal(t['vertices'][:len(n['vertices'])],n['vertices']);np.testing.assert_array_equal(t['triangles'][:len(n['triangles'])],n['triangles'])
  for d in t['domains']:
   delta=t['vertices'][d['inner_vertices']]-t['vertices'][d['outer_vertices']]
   np.testing.assert_allclose(delta,np.broadcast_to([0,0,.0001],delta.shape),rtol=0,atol=1e-17)
   self.assertEqual({x['role'] for x in d['margin_paths']},{'upper','lower'})
   for p in d['margin_paths']:self.assertTrue(np.all(np.diff(p['material_u'])>0))
 def test_no_negative_wall(self):
  with self.assertRaises(ValueError):construct(0)
if __name__=='__main__':unittest.main()
