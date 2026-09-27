"""Exact-rational, adaptive sufficient injectivity proof for an edge-glued pair.

Numerical optimization proposes ONE fixed preconditioner. Only rational interval
Sylvester tests can certify it. No sampling, numerical residual, or tolerance can
admit a pair. See proof-plan.md for the integrated-derivative argument.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
import itertools
import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class I:
    lo: Q
    hi: Q

    def __post_init__(self):
        if self.lo > self.hi:
            raise ValueError('reversed interval')

    def __add__(self, other):
        b = interval(other)
        return I(self.lo+b.lo, self.hi+b.hi)

    __radd__ = __add__

    def __neg__(self):
        return I(-self.hi, -self.lo)

    def __sub__(self, other):
        return self + -interval(other)

    def __mul__(self, other):
        b = interval(other)
        values = [x*y for x in (self.lo,self.hi) for y in (b.lo,b.hi)]
        return I(min(values), max(values))

    __rmul__ = __mul__


def interval(x):
    return x if isinstance(x,I) else I(Q(x),Q(x))


def matrix(x):
    return [[Q(v) for v in row] for row in x]


def serial(x):
    if isinstance(x,Q):
        return str(x)
    if isinstance(x,I):
        return [str(x.lo),str(x.hi)]
    if isinstance(x,(list,tuple)):
        return [serial(v) for v in x]
    return x


def det(a):
    return (a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
            -a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
            +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))


def polygon(box):
    """Vertices of rectangle intersect {u>=0,t>=0,u+t<=1}."""
    (ul,uh),(tl,th),_ = box
    points = {(u,t) for u in (ul,uh) for t in (tl,th) if u+t<=1}
    points |= {(u,1-u) for u in (ul,uh) if tl<=1-u<=th}
    points |= {(1-t,t) for t in (tl,th) if ul<=1-t<=uh}
    return sorted(points)


def map_point(p,q,u,t,w):
    b = (1-u-t,u,t)
    return [sum(b[i]*((1-w)*p[i][k]+w*q[i][k]) for i in range(3)) for k in range(3)]


def spatial(p,q,box):
    pts = [map_point(p,q,u,t,w) for u,t in polygon(box) for w in box[2]]
    return [I(min(x[k] for x in pts),max(x[k] for x in pts)) for k in range(3)] if pts else None


def jacobian(p,q,u,t,w,side):
    d = [[q[i][k]-p[i][k] for k in range(3)] for i in range(3)]
    return [[p[1][k]-p[0][k]+w*(d[1][k]-d[0][k]),
             side*(p[2][k]-p[0][k]+w*(d[2][k]-d[0][k])),
             (1-u-t)*d[0][k]+u*d[1][k]+t*d[2][k]] for k in range(3)]


ROOT = ((Q(0),Q(1)),)*3


def propose(maps):
    js = np.array([jacobian(p,q,u,t,w,side) for (p,q),side in zip(maps,(1,-1))
                   for u,t in polygon(ROOT) for w in (0,1)],dtype=float)
    c = np.linalg.inv(js.mean(axis=0))
    ms = c@js

    def objective(z):
        s = np.exp(np.r_[0.,z])
        m = ms*s[None,:,None]/s[None,None,:]
        return -np.linalg.eigvalsh((m+m.transpose(0,2,1))/2)[:,0].min()

    fit = minimize(objective,[0.,-3.],method='Nelder-Mead',options={'maxiter':400})
    if not np.isfinite(fit.fun) or fit.fun>=0:
        return None
    s = np.exp(np.r_[0.,fit.x])
    if not np.isfinite(s).all() or (s<=0).any():
        return None
    return matrix(c.tolist()),[Q(float(v)) for v in s],Q(float(-fit.fun/4))


def proof_bounds(p,q,box,side,c,s,mu):
    vertices = polygon(box)
    if not vertices:
        return None
    values = []
    for u,t in vertices:
        for w in box[2]:
            j = jacobian(p,q,u,t,w,side)
            a = [[s[i]*sum(c[i][k]*j[k][l] for k in range(3))/s[l]
                  for l in range(3)] for i in range(3)]
            values.append([[(a[i][l]+a[l][i])/2-(mu if i==l else 0)
                            for l in range(3)] for i in range(3)])
    # Each Jacobian entry is affine in (u,t,w); vertex bounds enclose it everywhere.
    h = [[I(min(v[i][j] for v in values),max(v[i][j] for v in values))
          for j in range(3)] for i in range(3)]
    minors = [h[0][0],h[0][0]*h[1][1]-h[0][1]*h[1][0],det(h)]
    return minors


def split(box,axis):
    lo,hi = box[axis];mid=(lo+hi)/2
    a=list(box);b=list(box);a[axis]=(lo,mid);b[axis]=(mid,hi)
    return tuple(a),tuple(b)


def prove_pair(a,ai,b,bi,max_depth=24,max_nodes=20000):
    maps = [(matrix(a),matrix(ai)),(matrix(b),matrix(bi))]
    bounds = [spatial(p,q,ROOT) for p,q in maps]
    residual = [bounds[0][i]-bounds[1][i] for i in range(3)]
    cert = {'maps':serial(maps),'leaves':[],'splits':[]}
    r = dict(classification='UNRESOLVED_NUMERICAL',minimum_interior_separation_m=None,
             lower_separation_bound_m=0,maximum_subdivision_depth=0,visited_nodes=0,
             numerical_tolerance=0,arithmetic='exact rational over frozen binary64 endpoints',
             root_parameter_boxes=serial([ROOT,ROOT]),spatial_coordinate_intervals_m=serial(bounds),
             first_conflicting_boxes=[],residual_interval_m=serial(residual),
             residual_interval_width_m=[float(x.hi-x.lo) for x in residual],certificate=cert)
    gap = max([x.lo for x in residual]+[-x.hi for x in residual])
    if gap>0:
        r.update(classification='CERTIFIED_SEPARATE',lower_separation_bound_m=str(gap))
        return r
    r['first_conflicting_boxes'] = [dict(a=serial(ROOT),b=serial(ROOT),residual_m=serial(residual))]
    if max_nodes<=0:
        r['reason']='NODE_BUDGET';return r
    if maps[0][0][:2]!=maps[1][0][:2] or maps[0][1][:2]!=maps[1][1][:2]:
        r['reason']='NO_IDENTICAL_EDGE_INTERFACE';return r
    try:
        proposal = propose(maps)
    except (np.linalg.LinAlgError,ValueError,FloatingPointError):
        proposal = None
    if proposal is None:
        r['reason']='NO_MONOTONICITY_PROPOSAL_NOT_COLLISION';return r
    c,s,mu = proposal
    if det(c)==0:
        r['reason']='SINGULAR_PRECONDITIONER';return r
    cert.update(C=serial(c),S=serial(s),mu=str(mu),method='fixed_preconditioned_strict_monotonicity')
    pending=[(i,ROOT,'') for i in (0,1)]
    while pending:
        side,box,path=pending.pop();r['visited_nodes']+=1
        depth=len(path);r['maximum_subdivision_depth']=max(depth,r['maximum_subdivision_depth'])
        if r['visited_nodes']>max_nodes:
            r['reason']='NODE_BUDGET';return r
        p,q=maps[side];minors=proof_bounds(p,q,box,1 if side==0 else -1,c,s,mu)
        if minors is None or all(x.lo>0 for x in minors):
            cert['leaves'].append(dict(side=side,path=path,box=serial(box),
                kind='EMPTY_DOMAIN' if minors is None else 'STRICT_MONOTONICITY',
                sylvester_minor_intervals=serial(minors) if minors else [],
                spatial_intervals_m=serial(spatial(p,q,box)) if minors else []))
            continue
        if depth>=max_depth:
            r['reason']='DEPTH_BUDGET';return r
        # Split the coordinate whose trial children give the most certified boxes;
        # ties cycle to prevent starvation. This affects cost, never validity.
        candidates=[]
        for axis in range(3):
            children=split(box,axis);score=0
            for child in children:
                m=proof_bounds(p,q,child,1 if side==0 else -1,c,s,mu)
                score+=int(m is None or all(x.lo>0 for x in m))
            candidates.append((score,-((axis-depth)%3),axis,children))
        _,_,axis,children=max(candidates)
        cert['splits'].append(dict(side=side,path=path,axis=axis))
        pending.extend((side,ch,path+str(k)) for k,ch in enumerate(children))
    norm_upper=sum(abs(s[i]*c[i][j]) for i in range(3) for j in range(3))
    r.update(classification='ALLOWED_SHARED_INTERFACE',minimum_interior_separation_m=0,
             equality_confined_to_shared_interface=True,
             monotonicity_lower_bound=str(mu),
             physical_separation_per_scaled_parameter_norm_lower_bound_m=str(mu/norm_upper),
             reason='Exact interval SPD over convex glued domain; equality implies identical u,y,w.')
    return r


def replay(r):
    """Recompute every inequality and complete subdivision coverage, no optimizer."""
    try:
        cert=r['certificate'];maps=[(matrix(p),matrix(q)) for p,q in cert['maps']]
        if r['classification']=='CERTIFIED_SEPARATE':
            a,b=[spatial(p,q,ROOT) for p,q in maps]
            gap=max([a[i].lo-b[i].hi for i in range(3)]+[b[i].lo-a[i].hi for i in range(3)])
            return gap>0 and Q(r['lower_separation_bound_m'])<=gap
        if r['classification']!='ALLOWED_SHARED_INTERFACE':return False
        if maps[0][0][:2]!=maps[1][0][:2] or maps[0][1][:2]!=maps[1][1][:2]:return False
        c=matrix(cert['C']);s=[Q(x) for x in cert['S']];mu=Q(cert['mu'])
        if mu<=0 or min(s)<=0 or det(c)==0:return False
        leaves={(x['side'],x['path']):x for x in cert['leaves']}
        splits={(x['side'],x['path']):x for x in cert['splits']}
        if len(leaves)!=len(cert['leaves']) or len(splits)!=len(cert['splits']):return False
        visited=set();pending=[(i,ROOT,'') for i in (0,1)]
        while pending:
            side,box,path=pending.pop();key=(side,path);visited.add(key)
            if key in leaves:
                if key in splits or leaves[key]['box']!=serial(box):return False
                m=proof_bounds(*maps[side],box,1 if side==0 else -1,c,s,mu)
                if m is not None and not all(x.lo>0 for x in m):return False
            elif key in splits:
                axis=splits[key]['axis']
                if axis not in (0,1,2):return False
                pending.extend((side,ch,path+str(k)) for k,ch in enumerate(split(box,axis)))
            else:return False
        return visited==set(leaves)|set(splits)
    except (KeyError,ValueError,TypeError,ZeroDivisionError,IndexError):
        return False
