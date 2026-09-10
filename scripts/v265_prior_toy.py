"""NumPy-only engineering harness. No real faces or pretrained identity weights.

Toy raster input and procedural expression modes do NOT establish face fidelity.
Run as a script with PROD_HARDENING_ENABLED=0 to avoid application bootstrap.
"""
import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
import numpy as np

OBJ_SHA = '8bac80443397e113f41a8b565ea72c59390bc031d9defab289dba7bc0c54e618'


def mesh(path):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != OBJ_SHA:
        raise ValueError('canonical asset checksum mismatch')
    vertices, faces = [], []
    for line in data.decode().splitlines():
        if line.startswith('v '): vertices.append(list(map(float,line.split()[1:4])))
        if line.startswith('f '): faces.append([int(x.split('/')[0])-1 for x in line.split()[1:4]])
    v = np.asarray(vertices,dtype=np.float32)
    v /= np.linalg.norm(v[33]-v[263])
    return v,np.asarray(faces,dtype=np.int32)


def basis(v, f, dim):
    """Smooth procedural modes; identity and residual exclude expression subspace."""
    n=len(v); adj=np.zeros((n,n),np.float32)
    for a,b in ((0,1),(1,2),(2,0)):
        adj[f[:,a],f[:,b]]=1; adj[f[:,b],f[:,a]]=1
    lap=np.diag(adj.sum(1))-adj
    _,vec=np.linalg.eigh(lap.astype(np.float64))
    expression=np.zeros((n,3,4),np.float32)
    expression[[13,14,17,0],1,0]=[1,-1,-.5,.5]
    expression[[61,291],1,1]=1
    expression[[159,145],1,2]=[1,-1]
    expression[[386,374],1,3]=[1,-1]
    q=np.linalg.qr(expression.reshape(-1,4))[0].astype(np.float32)
    raw=np.zeros((n,3,dim),np.float32)
    for j in range(dim): raw[:,j%3,j]=vec[:,1+j//3]
    raw=raw.reshape(n*3,dim); raw-=q@(q.T@raw)
    b=np.linalg.qr(raw)[0].astype(np.float32)
    edges=np.unique(np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1),axis=0)
    eb=(b.reshape(n,3,dim)[edges[:,0]]-b.reshape(n,3,dim)[edges[:,1]]).reshape(-1,dim)
    gram=eb.T@eb/len(edges)
    return b,q,gram,edges


def compose(v,b,q,c,e):
    # Last 32 coefficients form the separate canonical residual decoder.
    prior=(b[:,:-32]@c[:-32]).reshape(-1,3)*.05
    residual=(b[:,-32:]@c[-32:]).reshape(-1,3)*.05
    return v+prior+residual+(q@e).reshape(-1,3)*.05,residual


def project(v,yaw):
    r=np.array([[np.cos(yaw),0,np.sin(yaw)],[0,1,0],[-np.sin(yaw),0,np.cos(yaw)]],np.float32)
    return v@r.T


def raster(v,yaw,light):
    p=project(v,yaw); yy,xx=np.mgrid[:24,:24]
    # Gaussian point splats of geometry, not an encoded coefficient barcode.
    coords=(p[:,:2]+[0,0.15])*8+[12,12]
    d=(xx[None]-coords[:,0,None,None])**2+(yy[None]-coords[:,1,None,None])**2
    im=(np.exp(-d/1.2)*(1+.12*p[:,2,None,None])).sum(0)
    im=np.tanh(im*.3)*light
    return im.astype(np.float32).ravel()


def dataset(v,b,q,rng,count=64):
    coefficients=rng.uniform(-.7,.7,(count,b.shape[1])).astype(np.float32)
    images=[]
    for c in coefficients:
        views=[]
        for yaw in (-.25,0,.25):
            geom,_=compose(v,b,q,c,rng.uniform(-.5,.5,4))
            views.append(raster(geom,yaw,rng.uniform(.85,1.15)))
        images.append(views)
    return np.asarray(images),coefficients


def forward(x,w):
    h=np.tanh(x@w['w1']+w['b1'])
    y=np.tanh(h@w['w2']+w['b2'])
    return y,h


def train(x,c,gram,steps,rng):
    d=c.shape[1]
    w={'w1':rng.normal(0,.03,(x.shape[-1],192)).astype(np.float32),'b1':np.zeros(192,np.float32),
       'w2':rng.normal(0,.03,(192,d)).astype(np.float32),'b2':np.zeros(d,np.float32)}
    m={k:np.zeros_like(t) for k,t in w.items()}; z={k:np.zeros_like(t) for k,t in w.items()}
    history=[]
    for step in range(steps+1):
        ix=rng.integers(0,len(x),16); a=x[ix,0]; b=x[ix,2]; target=c[ix]
        pred,h=forward(np.concatenate([a,b]),w)
        err=pred-np.concatenate([target,target]); pair=pred[:16]-pred[16:]
        topology=np.mean(np.sum((pred@gram)*pred,axis=1))
        if step in (0,steps):
            all_pred,_=forward(x.reshape(-1,x.shape[-1]),w)
            all_pred=all_pred.reshape(len(c),3,d)
            history.append({'step':step,'mse':float(np.mean((all_pred-c[:,None])**2)),
                            'edge_energy':float(topology),'cross_view_mse':float(np.mean((all_pred[:,0]-all_pred[:,2])**2))})
        if step==steps: break
        grad=2*err/err.size + .02*(pred@gram)/len(pred)
        grad[:16]+=.2*pair/pair.size; grad[16:]-=.2*pair/pair.size
        dz=grad*(1-pred**2)
        dh=(dz@w['w2'].T)*(1-h*h)
        g={'w2':h.T@dz,'b2':dz.sum(0),'w1':np.concatenate([a,b]).T@dh,'b1':dh.sum(0)}
        for k in w:
            m[k]=.9*m[k]+.1*g[k]; z[k]=.999*z[k]+.001*g[k]**2
            w[k]-=.003*(m[k]/(1-.9**(step+1)))/(np.sqrt(z[k]/(1-.999**(step+1)))+1e-8)
    return w,history


def run(a):
    rng=np.random.default_rng(265); v,f=mesh(a.canonical); b,q,gram,edges=basis(v,f,a.dim)
    x,c=dataset(v,b,q,rng); mean=x[:48].mean((0,1)); x-=mean
    start=time.perf_counter(); w,history=train(x[:48],c[:48],gram,a.steps,rng)
    pred,_=forward(x[48:].reshape(-1,576),w); pred=pred.reshape(16,3,a.dim)
    training_seconds=time.perf_counter()-start
    samples=[]
    for _ in range(100):
        start=time.perf_counter(); y,_=forward(x[48,0:1],w)
        geom,residual=compose(v,b,q,y[0],np.zeros(4)); project(geom,.25)
        samples.append((time.perf_counter()-start)*1000)
    tri=v[f]; normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    t=geom[f]; n=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])
    area=np.linalg.norm(n,axis=1)/np.maximum(np.linalg.norm(normals,axis=1),1e-12)
    report={'scope':'procedural engineering toy only; NOT identity quality','seed':265,'canonical_sha256':OBJ_SHA,
      'identity_coefficients':a.dim,'parametric_coefficients':a.dim-32,'residual_coefficients':32,
      'vertices':len(v),'triangles':len(f),'identities_train':48,'identities_holdout':16,'views_per_identity':3,
      'history':history,'holdout_coefficient_mse':float(np.mean((pred-c[48:,None])**2)),
      'holdout_zero_prior_mse':float(np.mean(c[48:]**2)),
      'holdout_cross_view_mse':float(np.mean((pred[:,0]-pred[:,2])**2)),
      'expression_orthogonality_max':float(np.max(np.abs(q.T@b))),
      'residual_max_local_magnitude_iod':float(np.linalg.norm(residual,axis=1).max()),
      'toy_orientation_failures':int(np.count_nonzero(np.sum(n*normals,axis=1)<=0)),
      'toy_area_ratio_range':[float(area.min()),float(area.max())],
      'encoder_bytes':sum(t.nbytes for t in w.values()),'geometry_buffers_bytes':sum(t.nbytes for t in (v,f,b,q,gram,edges)),
      'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      'training_seconds':training_seconds,'inference_p50_ms':float(np.median(samples)),
      'inference_p95_ms':float(np.percentile(samples,95)),
      'real_identity_capacity_proven':False,'production_memory_qualified':False}
    a.output.mkdir(parents=True,exist_ok=True)
    np.savez(a.output/'toy_checkpoint.npz',**w,template=v,triangles=f,basis=b,expression=q,mean=mean,input_image=x[48,0]+mean)
    (a.output/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def inference(checkpoint,output):
    initial=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with np.load(checkpoint,allow_pickle=False) as z:
        w={k:z[k] for k in ('w1','b1','w2','b2')}
        v,b,q=z['template'],z['basis'],z['expression']
        x=(z['input_image']-z['mean'])[None]
    durations=[]
    for _ in range(110):
        start=time.perf_counter(); c,_=forward(x,w)
        geom,res=compose(v,b,q,c[0],np.array([-.3,0,0,0],np.float32))
        posed=project(geom,.25)
        durations.append((time.perf_counter()-start)*1000)
    report={'scope':'fresh isolated NumPy toy encoder + canonical decoder + target pose; excludes application and MediaPipe inference',
            'initial_rss_kib':initial,'inference_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'p50_ms':float(np.median(durations[10:])),'p95_ms':float(np.percentile(durations[10:],95)),
            'output_shape':list(posed.shape),'finite':bool(np.isfinite(posed).all()),'production_qualified':False}
    Path(output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--canonical'); p.add_argument('--dim',type=int,choices=(128,256),default=128)
    p.add_argument('--infer-checkpoint')
    p.add_argument('--steps',type=int,default=400); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.infer_checkpoint: inference(a.infer_checkpoint,a.output)
    elif a.canonical: run(a)
    else: p.error('--canonical or --infer-checkpoint is required')
