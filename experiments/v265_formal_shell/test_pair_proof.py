import unittest
from fractions import Fraction as Q
import importlib.util


class PairProof(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('experiments.v265_formal_shell.pair_proof'))
        from . import pair_proof
        return pair_proof

    def fixture(self, third=-1, shift=0):
        a=[[0,0,0],[1,0,0],[0,1,0]]
        b=[[0,0,shift],[1,0,shift],[0,third,shift]]
        return a,[[x,y,z+1] for x,y,z in a],b,[[x,y,z+1] for x,y,z in b]

    def test_allowed_interface(self):
        p=self.api(); r=p.prove_pair(*self.fixture())
        self.assertEqual(r['classification'],'ALLOWED_SHARED_INTERFACE')
        self.assertEqual(r['minimum_interior_separation_m'],0)
        self.assertTrue(p.replay(r))

    def test_real_overlap_never_passes(self):
        p=self.api();r=p.prove_pair(*self.fixture(third=1))
        self.assertEqual(r['classification'],'UNRESOLVED_NUMERICAL')

    def test_strict_separation_no_epsilon(self):
        p=self.api();a,ai,b,bi=self.fixture(shift=2)
        for gap in [Q(1),Q(1,10**30)]:
            b=[[Q(x),Q(y),Q(z)-1+gap] for x,y,z in b]
            bi=[[x,y,z+1] for x,y,z in b]
            r=p.prove_pair(a,ai,b,bi)
            self.assertEqual(r['classification'],'CERTIFIED_SEPARATE')
            self.assertTrue(p.replay(r))
            a,ai,b,bi=self.fixture(shift=2)

    def test_budget_cannot_pass(self):
        p=self.api();r=p.prove_pair(*self.fixture(),max_nodes=0)
        self.assertEqual(r['classification'],'UNRESOLVED_NUMERICAL')

    def test_interval_contains_exact_products(self):
        p=self.api();a=p.I(Q(-1,3),Q(2,7));b=p.I(Q(-7,11),Q(9,13));c=a*b
        for x in [a.lo,a.hi,Q(0)]:
            for y in [b.lo,b.hi,Q(0)]:self.assertTrue(c.lo<=x*y<=c.hi)

    def test_tampered_certificate_rejected(self):
        p=self.api();r=p.prove_pair(*self.fixture());r['certificate']['leaves']=[]
        self.assertFalse(p.replay(r))

    def test_different_interface_not_accepted(self):
        p=self.api();a,ai,b,bi=self.fixture();bi[0][0]=Q(1,10**20)
        r=p.prove_pair(a,ai,b,bi)
        self.assertNotEqual(r['classification'],'ALLOWED_SHARED_INTERFACE')

    def test_source_binding_rejects_different_mesh(self):
        p=self.api()
        from .prove_unresolved import verify_bound
        inputs=self.fixture();r=p.prove_pair(*inputs)
        r['formal_field_proof']=p.prove_pair(*inputs)
        self.assertTrue(verify_bound(r,inputs,inputs))
        different=self.fixture();different[0][2][0]=1
        self.assertFalse(verify_bound(r,different,inputs))

    def test_missing_subdivision_branch_rejected(self):
        p=self.api();r=p.prove_pair(*self.fixture())
        r['certificate']['leaves'][0]['path']='0'
        self.assertFalse(p.replay(r))

    def test_zero_volume_never_passes(self):
        p=self.api();a,ai,b,bi=self.fixture()
        self.assertEqual(p.prove_pair(a,a,b,b)['classification'],'UNRESOLVED_NUMERICAL')
