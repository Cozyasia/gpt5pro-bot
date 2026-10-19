"""Independent numerical contracts, without downloading any model assets."""
import unittest
import numpy as np
from scripts.v265_prior_toy import compose, forward, project, train


class PriorToyTests(unittest.TestCase):
    def test_expression_changes_neither_neutral_identity_nor_residual(self):
        rng=np.random.default_rng(8)
        qr=np.linalg.qr(rng.normal(size=(180,132)))[0].astype(np.float32)
        b,q=qr[:,:128],qr[:,128:]
        v=np.zeros((60,3),np.float32); c=rng.uniform(-1,1,128)
        neutral,r1=compose(v,b,q,c,np.zeros(4))
        expressive,r2=compose(v,b,q,c,np.ones(4))
        np.testing.assert_array_equal(r1,r2)
        np.testing.assert_allclose(expressive-neutral,(q@np.ones(4)).reshape(-1,3)*.05,atol=1e-7)
        self.assertLess(np.max(np.abs(q.T@r1.ravel())),1e-7)

    def test_pose_preserves_pairwise_distances(self):
        v=np.random.default_rng(9).normal(size=(20,3))
        p=project(v,.8)
        np.testing.assert_allclose(np.linalg.norm(p[1:]-p[:-1],axis=1),np.linalg.norm(v[1:]-v[:-1],axis=1),rtol=1e-6)

    def test_optimizer_can_learn_synthetic_supervision(self):
        # Test optimizer plumbing on a small known signal, not face capacity.
        rng=np.random.default_rng(1); c=rng.uniform(-.5,.5,(12,4)).astype(np.float32)
        x=np.repeat(c[:,None],3,axis=1)
        w,h=train(x,c,np.eye(4,dtype=np.float32),100,rng)
        self.assertLess(h[-1]['mse'],h[0]['mse']*.1)
        self.assertTrue(np.isfinite(forward(x[:,0],w)[0]).all())
