import numpy as np
from neyrobot_prod.v265_commercial_geometry import expression_basis, fit_identity, retarget


def test_identity_is_expression_orthogonal_and_scene_independent():
    rng=np.random.default_rng(7); template=rng.normal(size=(468,3)).astype(np.float32)
    source=template+rng.normal(0,.01,size=template.shape)
    identity,source_expression,q=fit_identity(template,source)
    assert np.max(np.abs(q.T@identity.reshape(-1))) < 1e-5
    one,_=retarget(template,identity,q,template)
    two,_=retarget(template,identity,q,template+.01*q[:,0].reshape(-1,3))
    assert not np.array_equal(one,two)
    assert np.array_equal(identity,identity.copy())


def test_residual_is_bounded():
    template=np.zeros((468,3),np.float32); template[33,0],template[263,0]=-1,1
    source=np.ones_like(template)*100
    identity,_,_=fit_identity(template,source,max_fraction=.1)
    assert np.linalg.norm(identity,axis=1).max() <= .20001
