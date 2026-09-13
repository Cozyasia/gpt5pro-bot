import unittest
import numpy as np
from .mechanics import assembly,articulate
from .contact import intersections
from experiments.v265_anatomy.generator import identity,lineage

class MechanicsTests(unittest.TestCase):
 def test_admission_rejects_neutral(self):
  from .admission import require_valid
  t=assembly();n=identity(t,lineage()[417]['factors'])
  with self.assertRaisesRegex(ValueError,'neutral penetration'):require_valid(t,n,n)
 def test_contact_witness(self):
  v=np.array([[0,0,0],[2,0,0],[0,2,0],[.5,.5,-1],[.5,.5,1],[1.5,.5,1.]])
  r=intersections(v,np.array([[0,1,2],[3,4,5]]));self.assertEqual(r['proper_intersection_pairs'],[[0,1]])
 def test_separated(self):
  v=np.array([[0,0,0],[2,0,0],[0,2,0],[0,0,1],[2,0,1],[0,2,1.]])
  self.assertEqual(intersections(v,np.array([[0,1,2],[3,4,5]]))['proper_intersection_pairs'],[])
 def test_neutral_no_mutation(self):
  t=assembly();n=identity(t,lineage()[417]['factors']);before=n.copy()
  for c in ('A','B'):
   np.testing.assert_array_equal(articulate(t,n,np.zeros(8),c),n)
   articulate(t,n,np.ones(8),c);np.testing.assert_array_equal(n,before)
 def test_dental_rigid_ownership(self):
  t=assembly();n=identity(t,lineage()[417]['factors']);e=np.ones(8)
  for c in ('A','B'):
   v=articulate(t,n,e,c);np.testing.assert_array_equal(v[t['upper_teeth']],n[t['upper_teeth']])
   low=t['lower_teeth'];np.testing.assert_allclose(np.linalg.norm(v[low]-v[low[0]],axis=1),np.linalg.norm(n[low]-n[low[0]],axis=1),atol=1e-15)
 def test_neutral_mouth_not_clear(self):
  t=assembly();n=identity(t,lineage()[417]['factors']);ids=np.flatnonzero(np.isin(t['semantic'][t['triangles']],[3,4,5,6]).any(1))
  self.assertGreater(len(intersections(n,t['triangles'],ids)['proper_intersection_pairs']),0)
if __name__=='__main__':unittest.main()
