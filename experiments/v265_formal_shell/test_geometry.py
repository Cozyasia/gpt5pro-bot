import unittest
import numpy as np
from .cones import classify
class Geometry(unittest.TestCase):
 def test_cone_classes(self):
  self.assertEqual(classify([[0,0,1]])['classification'],'FEASIBLE_CONE')
  self.assertEqual(classify([[0,0,1],[0,0,-1]])['classification'],'DEGENERATE_CONE')
  self.assertEqual(classify(np.r_[np.eye(3),-np.eye(3)])['classification'],'EMPTY_CONE')
 def test_prism_jacobian(self):
  from .field import prism_min
  p=np.array([[0,0,0],[1,0,0],[0,1,0]],float)
  self.assertAlmostEqual(prism_min(p,np.tile([0,0,1.],(3,1)),.1)[0],1.)
  self.assertLess(prism_min(p,np.array([[0,0,1],[-20,0,1],[0,0,1]]),.1)[0],0.)
