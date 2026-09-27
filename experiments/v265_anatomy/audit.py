"""Persist negative anatomy evidence before any training admission."""
import json,hashlib,resource,time,argparse
from pathlib import Path
import numpy as np
from .generator import template,identity,express,lineage,accessory,VERSION,FACTORS,CLASSES
from experiments.v265_prior.evaluate import topology_metrics

def structure(t):
    tri=t['triangles'];edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]])
    _,inv,count=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    winding=np.bincount(inv,weights=np.where(edges[:,0]<edges[:,1],1,-1));v=t['vertices'][tri]
    area=np.linalg.norm(np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0]),axis=1)
    return dict(vertices=len(t['vertices']),triangles=len(tri),degenerate_triangles=np.where(area<=1e-12)[0].tolist(),nonmanifold_edges=int((count>2).sum()),inconsistent_winding=int(((count==2)&(winding!=0)).sum()),boundary_edges=int((count==1).sum()),expected_outer_edges=len(t['outer_boundary']))

def run(out):
    start=time.monotonic();out=Path(out);out.mkdir(parents=True,exist_ok=True);t=template();rows=lineage();neutral=np.stack([identity(t,r['factors']) for r in rows]);top=structure(t)
    train=neutral[:320].reshape(320,-1).copy();train-=train.mean(0);singular=np.sqrt(np.linalg.eigvalsh(train@train.T).clip(0))[::-1]
    cases=[];rng=np.random.default_rng(265406)
    for i in range(32):
        n=neutral[416+i];e=rng.uniform(-1,1,8);e[1]=abs(e[1]);v=express(t,n,e);tri=t['triangles'];a=v[tri];b=n[tri]
        normal=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]);reference=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]);bad_reference=np.linalg.norm(reference,axis=1)<=1e-12;bad=(normal*reference).sum(1)<=0
        metrics=topology_metrics(v,n,tri) if not bad_reference.any() else {'error':'invalid reference topology'}
        cases.append(dict(identity=416+i,root=rows[416+i]['root'],expression=e.tolist(),bad_reference=int(bad_reference.sum()),orientation_failures=int(bad.sum()),regions={name:int((t['semantic'][tri[bad,0]]==k).sum()) for k,name in enumerate(CLASSES)},metrics=metrics))
        if (bad.any() or bad_reference.any()) and not (out/'first-failure.npz').exists():np.savez_compressed(out/'first-failure.npz',neutral=n,expressed=v,triangles=tri,invalid=np.flatnonzero(bad|bad_reference),factors=rows[416+i]['factors'],expression=e)
    result=dict(generator=VERSION,topology=top,legacy_polar_topology=structure(template(True)),effective_rank=int((singular>singular[0]*1e-5).sum()),rank_relative_tolerance=1e-5,energy_rank_99=int(np.searchsorted(np.cumsum(singular**2)/np.sum(singular**2),.99)+1),energy_rank_999=int(np.searchsorted(np.cumsum(singular**2)/np.sum(singular**2),.999)+1),rank_fit='TRAIN roots only',identity_count=512,renders=0,lineage=dict(roots=128,descendants_per_root=4,train_roots=80,val_roots=24,test_roots=24,train=320,val=96,test=96),stress=cases,orientation_failures=sum(c['orientation_failures'] for c in cases),stage_a_admitted=False,full_anatomy_qualified=False,v0=False,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,seconds=time.monotonic()-start)
    (out/'audit.json').write_text(json.dumps(result,indent=2))
    (out/'lineage.json').write_text(json.dumps([{k:v for k,v in r.items() if k!='factors'} for r in rows],indent=2))
    (out/'provenance.json').write_text(json.dumps(dict(generator=VERSION,generator_sha256=hashlib.sha256(Path(__file__).with_name('generator.py').read_bytes()).hexdigest(),external_assets=[],source_assets='original analytic code only; no external primitive meshes/face weights',texture_sources='not implemented',accessories='original torus and disk equations',seed=2654,distribution='root U(-.8,.8)^80; child root+U(-.15,.15)^80 clipped[-1,1]',factor_names=FACTORS,status='ENGINEERING_ONLY',commercial_training_allowed=False),indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='stress'},indent=2));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');a=p.parse_args();run(a.out)
