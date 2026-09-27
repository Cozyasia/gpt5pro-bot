"""Proof-only batch on unchanged G2. Does not modify neutral admission."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from fractions import Fraction as Q
import numpy as np
from .preflight import geometry
from .pair_proof import prove_pair, replay, serial


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_vertices(rows,mapping,depth):
    """Authoritative serialized G2 coordinates, never regenerated trig positions."""
    v={}
    for r in rows:
        i=r['vertex'];v[i]=list(r['position_m'])
        v[mapping[i]]=[float(p)+float(depth)*float(d) for p,d in zip(r['position_m'],r['direction'])]
    return v


def geometry_digest(v,tr):
    data=json.dumps({'material_vertices':sorted(v.items()),'triangles':tr.tolist()},separators=(',',':'))
    return hashlib.sha256(data.encode()).hexdigest()


def pair_maps(vertices,mapping,ids,rows,depth):
    a,b,c,d=ids;aa=[a,b,c];bb=[a,b,d]
    mesh=[[vertices[x] for x in aa],[vertices[mapping[x]] for x in aa],
          [vertices[x] for x in bb],[vertices[mapping[x]] for x in bb]]
    directions={r['vertex']:r['direction'] for r in rows}
    field=[]
    for face in (aa,bb):
        outer=[[Q(float(x)) for x in vertices[i]] for i in face]
        inner=[[outer[j][k]+Q(depth)*Q(directions[i][k]) for k in range(3)]
               for j,i in enumerate(face)]
        field.extend([outer,inner])
    return mesh,field


def verify_bound(r,mesh,field):
    for proof,inputs in ((r,mesh),(r['formal_field_proof'],field)):
        expected=serial([[[Q(x) for x in row] for row in inputs[i]] for i in range(4)])
        got=proof['certificate']['maps']
        if [got[0][0],got[0][1],got[1][0],got[1][1]]!=expected:return False
        if not replay(proof):return False
    return True


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    source=Path('docs/engineering/v265-formal-shell')
    rows=json.loads((source/'cones.json').read_text())
    contract=json.loads((source/'frozen-contract.json').read_text())
    old=json.loads((source/'global-field.json').read_text())
    pairs=[x for x in old['ruled_separations'] if not x['separated']]
    assert len(pairs)==old['remaining_unresolved']==89
    assert len({tuple(x['triangles']) for x in pairs})==89
    # Representative first; no pair-specific proof logic.
    pairs.sort(key=lambda x:(x['triangles']!=[7676,7747],x['triangles']))
    t=geometry(rows,contract['construction_depth_m']);tr=t['triangles']
    mapping={a:b for domain in t['domains'] for a,b in zip(domain['outer_vertices'],domain['inner_vertices'])}
    v=frozen_vertices(rows,mapping,contract['construction_depth_m'])
    snapshot=geometry_digest(v,tr)
    result=[]
    for pair in pairs:
        a,b,c,d=pair['vertices'];aa=[a,b,c];bb=[a,b,d]
        assert set(aa)==set(tr[pair['triangles'][0]]) and set(bb)==set(tr[pair['triangles'][1]])
        assert set(aa)&set(bb)=={a,b}
        mesh,field=pair_maps(v,mapping,pair['vertices'],rows,contract['construction_depth_m'])
        r=prove_pair(*mesh)
        r['formal_field_proof']=prove_pair(*field)
        if r['classification']!='UNRESOLVED_NUMERICAL':
            assert r['formal_field_proof']['classification']==r['classification']
            assert verify_bound(r,mesh,field)
        r.update(triangles=pair['triangles'],shared_edge=[a,b],third_vertices=[c,d],
                 inner_vertex_ids=[[mapping[x] for x in aa],[mapping[x] for x in bb]],
                 frozen_depth_m=contract['construction_depth_m'],
                 local_shell_directions=[x for x in rows if x['vertex'] in pair['vertices']])
        name='pair-'+ '-'.join(map(str,pair['triangles']))+'.json'
        (out/name).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
        result.append(dict(triangles=pair['triangles'],classification=r['classification'],
                           maximum_subdivision_depth=max(r['maximum_subdivision_depth'],r['formal_field_proof']['maximum_subdivision_depth']),
                           visited_nodes=r['visited_nodes']+r['formal_field_proof']['visited_nodes'],file=name,sha256=digest(out/name)))
        print(pair['triangles'],r['classification'],'depth',r['maximum_subdivision_depth'],flush=True)
    assert snapshot==geometry_digest(v,tr)
    counts=Counter(x['classification'] for x in result)
    summary=dict(input_pairs=89,counts={k:counts[k] for k in [
        'CERTIFIED_SEPARATE','ALLOWED_SHARED_INTERFACE','CERTIFIED_FORBIDDEN_INTERSECTION','UNRESOLVED_NUMERICAL']},
        geometry_changed=False,geometry_sha256=snapshot,
        geometry_hash_scope='Authoritative cones.json material positions, rounded inner endpoints and complete integer topology; excludes regenerated floating nonmaterial positions.',
        maximum_subdivision_depth=max(x['maximum_subdivision_depth'] for x in result),
        visited_nodes=sum(x['visited_nodes'] for x in result),
        minimum_interior_separation_m=0,numerical_tolerance=0,
        scope='Exact certificates for all 89 pairs, both frozen rounded mesh endpoints and exact p+w*h*d field. Both source-bound and replayed.',
        global_injectivity='UNQUALIFIED',neutral_shell_admission='NOT_RUN',blink='NOT_RUN',
        remaining_global_obligations=[
            'Existing 449 separators and all other cell-pair exclusions are floating numerical evidence, not replayed exact certificates.',
            'Complete volume versus unrelated exterior/globe exclusion and allowed boundary contact classification.',
            'Global assembly of pair and single-cell injectivity coverage.'],
        source_hashes={n:digest(source/n) for n in ['cones.json','frozen-contract.json','global-field.json']},
        execution_checkout_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        code_hashes={str(p):digest(p) for p in Path('experiments/v265_formal_shell').glob('*.py')},pairs=result)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['pairs','code_hashes','source_hashes']},indent=2))
    return summary


def replay_batch(out):
    out=Path(out);summary=json.loads((out/'summary.json').read_text())
    source=Path('docs/engineering/v265-formal-shell')
    for name,h in summary['source_hashes'].items():
        assert digest(source/name)==h,('source hash',name)
    rows=json.loads((source/'cones.json').read_text())
    contract=json.loads((source/'frozen-contract.json').read_text())
    pairs={tuple(x['triangles']):x for x in json.loads((source/'global-field.json').read_text())['ruled_separations'] if not x['separated']}
    t=geometry(rows,contract['construction_depth_m']);tr=t['triangles']
    mapping={a:b for d in t['domains'] for a,b in zip(d['outer_vertices'],d['inner_vertices'])}
    v=frozen_vertices(rows,mapping,contract['construction_depth_m'])
    assert geometry_digest(v,tr)==summary['geometry_sha256']
    seen=set();counts=Counter()
    for entry in summary['pairs']:
        key=tuple(entry['triangles']);assert key in pairs and key not in seen;seen.add(key)
        path=out/entry['file'];assert digest(path)==entry['sha256']
        r=json.loads(path.read_text());assert r['triangles']==entry['triangles']
        assert r['classification']==entry['classification']
        pair=pairs[key];mesh,field=pair_maps(v,mapping,pair['vertices'],rows,contract['construction_depth_m'])
        if r['classification']!='UNRESOLVED_NUMERICAL':assert verify_bound(r,mesh,field)
        counts[r['classification']]+=1
    assert seen==set(pairs) and len(seen)==summary['input_pairs']==89
    assert all(counts[k]==v for k,v in summary['counts'].items())
    print('REPLAY: 89/89 source-bound pairs; mesh + formal field certificates verified')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('out');ap.add_argument('--replay',action='store_true');args=ap.parse_args()
    replay_batch(args.out) if args.replay else run(args.out)
