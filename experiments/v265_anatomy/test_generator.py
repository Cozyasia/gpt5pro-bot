"""Regression tests preserve rejection, not claim anatomical qualification."""
import unittest
import numpy as np
from .generator import template, identity, express, lineage, accessory
from .audit import structure

class AnatomyTests(unittest.TestCase):
    def test_reference_constructor(self):
        s=structure(template())
        self.assertEqual(s['degenerate_triangles'],[])
        self.assertEqual(s['nonmanifold_edges'],0)
        self.assertEqual(s['inconsistent_winding'],0)
        self.assertEqual(s['boundary_edges'],s['expected_outer_edges'])

    def test_polar_collapse_negative(self):
        self.assertEqual(structure(template(True))['degenerate_triangles'],[8171,8172])

    def test_neutral_immutable(self):
        t=template();n=identity(t,lineage()[0]['factors']);saved=n.copy()
        express(t,n,np.ones(8))
        np.testing.assert_array_equal(n,saved)
        np.testing.assert_array_equal(express(t,n,np.zeros(8)),n)

    def test_root_disjoint(self):
        groups={}
        for row in lineage(): groups.setdefault(row['root'],set()).add(row['split'])
        self.assertEqual(len(groups),128)
        self.assertTrue(all(len(s)==1 for s in groups.values()))

    def test_open_mouth_negative(self):
        t=template();n=identity(t,lineage()[417]['factors']);rng=np.random.default_rng(265406)
        for _ in range(2):e=rng.uniform(-1,1,8);e[1]=abs(e[1])
        opening=np.zeros(8);opening[1]=e[1];v=express(t,n,opening)
        a=v[t['triangles']];b=n[t['triangles']]
        bad=(np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0])*np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0])).sum(1)<=0
        self.assertEqual(np.flatnonzero(bad).tolist(),[8111])

    def test_accessory_separate(self):
        for kind in (1,2,3):
            a=accessory(kind)
            self.assertTrue(np.isfinite(a['vertices']).all())
            self.assertEqual(set(a['semantic']),{9,11 if kind==3 else 10})
            self.assertTrue(((a['alpha']>0)&(a['alpha']<=1)).all())

if __name__=='__main__':unittest.main()
