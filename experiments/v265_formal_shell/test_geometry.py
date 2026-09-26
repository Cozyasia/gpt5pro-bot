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
 def test_material_thickness_handles_constant_direction(self):
  from .material import minimum_thickness
  self.assertAlmostEqual(minimum_thickness(np.tile([0,0,.001],(3,1))),.001)
  self.assertAlmostEqual(minimum_thickness(np.array([[-1,0,1],[1,0,1],[0,1,1.]])),1.)
 def test_adjacent_ruled_separator(self):
  from .material import ruled_separation
  p=np.array([[0,0,0],[1,0,0],[0,1,0],[0,-1,0]],float)
  d=np.tile([0,0,.1],(4,1))
  self.assertTrue(ruled_separation(p,d)['separated'])
  p[3]=[.5,.5,0]
  self.assertFalse(ruled_separation(p,d)['separated'])
 def test_inverse_prism(self):
  from .witness import inverse_prism
  p=np.array([[0,0,0],[1,0,0],[0,1,0]],float);d=np.tile([0,0,1.],(3,1))
  roots=inverse_prism(p,d,np.array([.2,.3,.4]))
  self.assertEqual(len(roots),1);self.assertAlmostEqual(roots[0]['depth_fraction'],.4)
  self.assertFalse(inverse_prism(p,d,np.array([2.,.3,.4])))
 def test_frozen_contract_and_fail_closed(self):
  import json
  from pathlib import Path
  from .admission import decide
  old=json.loads(Path('experiments/v265_shell_feasibility/contract.json').read_text());new=json.loads(Path('experiments/v265_formal_shell/contract.json').read_text())
  for k in ['thickness_min_m','construction_depth_m','inner_globe_min_m','exterior_deviation_m']:self.assertEqual(old[k],new[k])
  self.assertFalse(decide(True,False));self.assertFalse(decide(False,True));self.assertTrue(decide(True,True))
