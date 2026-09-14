"""Failed continuous opening experiment; never selected for training."""
import json
import numpy as np
from .generator import template,identity,express,lineage

def run():
    t=template();rows=lineage();rng=np.random.default_rng(265406);counts=[0,0];cases=[]
    for i in range(32):
        n=identity(t,rows[416+i]['factors']);e=rng.uniform(-1,1,8);e[1]=abs(e[1]);v=express(t,n,e)
        x,y=t['uv'].T;lip=np.isin(t['semantic'],[3,4]);radius=np.sqrt((x/.34)**2+((y-.43)/.075)**2)
        w=v.copy();w[lip,1]-=.007*e[1]*np.sign(y[lip]-.43)*np.clip(1-radius[lip],0,1)
        w[:,1]+=.007*e[1]*np.tanh((y-.43)/.01)*np.exp(-(x/.34)**4-((y-.43)/.075)**4)
        b=n[t['triangles']];ref=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]);result=[]
        for j,p in enumerate([v,w]):
            a=p[t['triangles']];nn=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]);bad=int(((nn*ref).sum(1)<=0).sum());counts[j]+=bad;result.append(bad)
        cases.append(dict(identity=416+i,discontinuous=result[0],continuous=result[1]))
    return dict(discontinuous_failures=counts[0],continuous_failures=counts[1],selected=False,cases=cases)
if __name__=='__main__':print(json.dumps(run(),indent=2))
