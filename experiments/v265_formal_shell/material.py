"""Minimum norm on displacement convex hull, including rank-zero/one cases."""
import numpy as np

def minimum_thickness(t):
    t=np.asarray(t,float);best=float(np.linalg.norm(t,axis=1).min())
    for a,b in ((0,1),(1,2),(2,0)):
        d=t[b]-t[a];den=float(d@d)
        if den>0:
            q=t[a]+np.clip(-float(t[a]@d)/den,0,1)*d;best=min(best,float(np.linalg.norm(q)))
    e=np.stack([t[1]-t[0],t[2]-t[0]],axis=1)
    uv,_,rank,_=np.linalg.lstsq(e,-t[0],rcond=None)
    if rank==2 and min(uv)>=0 and uv.sum()<=1:best=min(best,float(np.linalg.norm(t[0]+e@uv)))
    return best

def polynomial_range(c):
    a,b,d=c;points=[0.,1.]
    if d!=0 and 0< -b/(2*d)<1:points.append(-b/(2*d))
    values=[a+b*t+d*t*t for t in points]
    return [float(min(values)),float(max(values))]

def ruled_separation(p,delta):
    # p = shared a,b, third vertex on each side. delta = full-depth displacements.
    e=p[1]-p[0];f=delta[0];g=delta[1]-delta[0];basis=np.stack([e,f,g],axis=1);ranges=[]
    if np.linalg.matrix_rank(basis)<3:
        n=np.cross(e,f);n/=np.linalg.norm(n)
        for j in [2,3]:
            ranges.append(polynomial_range([float((p[j]-p[0])@n),float((delta[j]-delta[0])@n),0.]))
        mode='planar'
    else:
        for j in [2,3]:
            k=np.linalg.solve(basis,p[j]-p[0]);h=np.linalg.solve(basis,delta[j]-delta[0]);extrema=[]
            # Implicit ruled interface Q=Z-X*Y; Q/v is affine u,v and quadratic s.
            for u,v in [(0,0),(1,0),(0,1)]:
                c=[k[2]-u*k[1]-v*k[0]*k[1],h[2]-u*h[1]-k[0]-v*(k[0]*h[1]+h[0]*k[1]),-h[0]-v*h[0]*h[1]]
                extrema.append(polynomial_range(c))
            ranges.append([min(x[0] for x in extrema),max(x[1] for x in extrema)])
        mode='bilinear_implicit'
    separated=(ranges[0][0]>0 and ranges[1][1]<0) or (ranges[1][0]>0 and ranges[0][1]<0)
    return dict(separated=bool(separated),ranges=ranges,mode=mode,condition_number=float(np.linalg.cond(basis)))
