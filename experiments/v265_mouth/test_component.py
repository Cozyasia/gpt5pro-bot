import unittest
import numpy as np
from .component import build,jaw_only,expression
from .validate import validate,segment_distance,point_triangle

class MouthTests(unittest.TestCase):
 def test_neutral_topology_contact(self):
  r=validate(build());self.assertTrue(r['pass']);self.assertEqual(r['intersections'],0);self.assertEqual(r['connected_components'],13)
 def test_thickness_clearance(self):
  r=validate(build());self.assertAlmostEqual(r['min_signed_lip_separation_m'],.003);self.assertGreater(r['teeth_oral_clearance']['metres'],.004)
 def test_rigid_teeth(self):
  t=build();n=t['vertices'].copy();v=expression(t,1,1,1,1,1);u=t['teeth']['upper'];l=t['teeth']['lower']
  np.testing.assert_array_equal(v[u],n[u]);np.testing.assert_allclose(np.linalg.norm(v[l]-v[l[0]],axis=1),np.linalg.norm(n[l]-n[l[0]],axis=1),atol=1e-15);np.testing.assert_array_equal(n,t['vertices'])
 def test_identity_neutral(self):
  t=build();np.testing.assert_array_equal(jaw_only(t,0),t['vertices'])
 def test_distances(self):
  d=segment_distance(np.array([[0.,0,0]]),np.array([[1.,0,0]]),np.array([[.5,-1,1.]]),np.array([[.5,1,1.]]));np.testing.assert_allclose(d,[1.])
  tri=np.array([[[0.,0,0],[1,0,0],[0,1,0]]]);np.testing.assert_allclose(point_triangle(np.array([[.2,.2,2.]]),tri),[2.])
if __name__=='__main__':unittest.main()
