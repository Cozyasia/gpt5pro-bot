"""Original anatomical assembly, recovered and corrected after scratch reset.

Not qualified anatomy. No external assets. All coordinates are metres.
"""
import numpy as np

VERSION = 'anatomy-v4-assembly-2'
FEATURES = [
 ('forehead',0,-.72,.65,.24),('left_orbit',-.4,-.25,.25,.17),
 ('right_orbit',.4,-.25,.25,.17),('bridge',0,-.18,.10,.24),
 ('tip',0,.06,.15,.12),('left_ala',-.16,.15,.09,.08),
 ('right_ala',.16,.15,.09,.08),('left_cheek',-.51,.2,.29,.26),
 ('right_cheek',.51,.2,.29,.26),('maxilla',0,.29,.43,.15),
 ('philtrum',0,.30,.07,.10),('upper_lip',0,.39,.34,.05),
 ('lower_lip',0,.48,.34,.055),('left_jaw',-.65,.65,.24,.24),
 ('right_jaw',.65,.65,.24,.24),('chin',0,.84,.34,.19)]
FACTORS = [name+'/'+factor for name,*_ in FEATURES for factor in
           ['depth','horizontal_extent','vertical_extent','horizontal_offset','vertical_offset']]
CLASSES = ['skin','eyelid','eyeball','upper_lip','lower_lip','mouth_cavity',
           'teeth','nostril_rim','nostril_cavity','glasses_frame','transparent_lens','opaque_lens']
HOLES=[('left_eye',-.4,-.25,.20,.10),('right_eye',.4,-.25,.20,.10),
       ('mouth',0,.43,.34,.075),('left_nostril',-.17,.16,.055,.045),
       ('right_nostril',.17,.16,.055,.045)]

def boundary_loops(tri):
    edges=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]])
    _,inv,count=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    neighbors={}
    for a,b in edges[count[inv]==1]:
        neighbors.setdefault(int(a),[]).append(int(b));neighbors.setdefault(int(b),[]).append(int(a))
    if any(len(v)!=2 for v in neighbors.values()):raise ValueError('boundary is not a collection of cycles')
    unused=set(neighbors);result=[]
    while unused:
        start=min(unused);ring=[start];previous=None;current=start
        while True:
            nxt=next(v for v in neighbors[current] if v!=previous)
            if nxt==start:break
            if nxt in ring:raise ValueError('repeated boundary vertex')
            ring.append(nxt);previous,current=current,nxt
        unused.difference_update(ring);result.append(np.array(ring,int))
    return sorted(result,key=len,reverse=True)

def template(legacy_polar=False):
    nx,ny=59,71;u,v=np.meshgrid(np.linspace(-1,1,nx),np.linspace(-1,1,ny))
    uv=np.stack([u.ravel(),v.ravel()],1);x,y=uv.T
    vertices=np.stack([.075*x*np.sqrt(1-.55*y*y),.105*y,
                       -.009*(1-x*x)-.019*np.exp(-(x/.16)**2-((y-.02)/.25)**2)],1)
    a=np.arange(nx*ny).reshape(ny,nx)[:-1,:-1].ravel()
    tri=np.concatenate([np.stack([a,a+1,a+nx],1),np.stack([a+1,a+nx+1,a+nx],1)])
    centers=uv[tri].mean(1);keep=np.ones(len(tri),bool)
    for _,cx,cy,rx,ry in HOLES:keep&=((centers[:,0]-cx)/rx)**2+((centers[:,1]-cy)/ry)**2>1
    tri=tri[keep];rings=boundary_loops(tri)
    if len(rings)!=6:raise ValueError('five anatomical apertures required')
    points=list(vertices);coords=list(uv);faces=list(tri);sem=[0]*len(points);objects=[0]*len(points);parts={}
    directed=set(map(tuple,np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]).tolist()))
    def add(p,q,label,obj=0):
        ids=np.arange(len(points),len(points)+len(p));points.extend(p);coords.extend(q)
        sem.extend([label]*len(p) if np.ndim(label)==0 else label);objects.extend([obj]*len(p));return ids
    def join(old,new):
        for i in range(len(old)):
            j=(i+1)%len(old);faces.extend([[old[i],old[j],new[i]],[old[j],new[j],new[i]]])
    for ring in rings[1:]:
        if (int(ring[0]),int(ring[1])) in directed:ring=ring[::-1]
        h=min(HOLES,key=lambda h:np.linalg.norm(uv[ring].mean(0)-h[1:3]));name,cx,cy,rx,ry=h
        base=vertices[ring];q=uv[ring];prev=ring;parts[name]=[]
        theta=np.arctan2((q[:,1]-cy)/ry,(q[:,0]-cx)/rx)
        for level,(sx,deep) in enumerate(zip([.95,.82,.76,.70,.6],[-.001,-.002,0,.009,.017]),1):
            sy=[.9,.5,.025,.6,.6][level-1] if name=='mouth' else sx
            if legacy_polar:
                target=np.stack([cx+rx*sx*np.cos(theta),cy+ry*sy*np.sin(theta)],1)
            else:
                # Preserve injective boundary parameterization: radial angle alone
                # collapses distinct grid vertices lying on the same ray.
                target=np.array([cx,cy])+(q-[cx,cy])*[sx,sy]
            p=base.copy();p[:,:2]+=(target-q)*[.075,.105];p[:,2]+=deep
            label=(np.where(q[:,1]<cy,3,4) if level<4 else np.full(len(q),5)) if name=='mouth' else (7 if level<4 else 8) if 'nostril' in name else 1
            new=add(p,target,label);join(prev,new);parts[name].extend(new.tolist());prev=new
        center=add(np.mean(np.asarray(points)[prev],0)[None],np.array([[cx,cy]]),5 if name=='mouth' else 8 if 'nostril' in name else 1)[0]
        for i in range(len(prev)):faces.append([prev[i],prev[(i+1)%len(prev)],center])
    def ellipsoid(center,radius,label,obj,n=24,m=12):
        rows=[]
        for j in range(1,m):
            phi=np.pi*j/m;theta=np.arange(n)*2*np.pi/n
            p=np.stack([np.sin(phi)*np.cos(theta),np.cos(phi)*np.ones(n),np.sin(phi)*np.sin(theta)],1)*radius+center
            rows.append(add(p,p[:,:2]/[.075,.105],label,obj))
        for old,new in zip(rows,rows[1:]):join(old,new)
        for row,sign in [(rows[0],1),(rows[-1],-1)]:
            p=center+np.array([0,sign*radius[1],0]);cap=add(p[None],(p[:2]/[.075,.105])[None],label,obj)[0]
            for i in range(n):faces.append([row[(i+1)%n],row[i],cap] if sign==1 else [row[i],row[(i+1)%n],cap])
    for side in (-1,1):ellipsoid(np.array([side*.029,-.026,-.010]),np.array([.014,.010,.010]),2,1 if side<0 else 2)
    for k in range(8):ellipsoid(np.array([-.020+k*.0057,.044,.004]),np.array([.0027,.006,.003]),6,3+k,8,5)
    used=np.unique(faces);remap=np.full(len(points),-1,int);remap[used]=np.arange(len(used))
    return dict(vertices=np.array(points,dtype='f8')[used],triangles=remap[np.array(faces)],
                uv=np.array(coords)[used],semantic=np.array(sem)[used],object=np.array(objects)[used],
                parts={k:remap[v].tolist() for k,v in parts.items()},outer_boundary=remap[rings[0]])

def identity(t,factors):
    p=np.asarray(factors).reshape(16,5);v=t['vertices'].copy();x,y=t['uv'].T
    for k,(_,cx,cy,sx,sy) in enumerate(FEATURES):
        depth,wx,wy,ox,oy=p[k];dx=x-cx-.035*ox;dy=y-cy-.025*oy
        g=np.exp(-(dx/(sx*np.exp(.14*wx)))**2-(dy/(sy*np.exp(.14*wy)))**2)
        v[:,2]-=.0022*depth*g;v[:,0]+=.0015*wx*dx*g;v[:,1]+=.0015*wy*dy*g
    return v

def express(t,neutral,e):
    v=neutral.copy();x,y=t['uv'].T
    mouth=np.exp(-(x/.45)**4-((y-.43)/.19)**4);eye=np.exp(-((abs(x)-.4)/.29)**4-((y+.25)/.17)**4)
    v[:,1]-=.005*e[0]*(x/.4)**2*mouth
    v[:,1]+=.005*e[1]*np.tanh((y-.43)/.06)*mouth
    lip=(t['semantic']==3)|(t['semantic']==4);radius=np.sqrt((x/.34)**2+((y-.43)/.075)**2)
    v[lip,1]+=.007*e[1]*np.sign(y[lip]-.43)*np.clip(1-radius[lip],0,1)
    v[:,1]-=.001*e[2]*np.tanh((y-.43)/.08)*mouth;v[:,2]-=.002*e[3]*mouth
    v[:,1]+=.002*e[4]*x*mouth
    v[:,1]-=.002*e[5]*np.exp(-((abs(x)-.4)/.26)**2-((y+.4)/.1)**2)
    lid=t['object']==0;v[lid,1]-=.002*e[6]*np.tanh((y[lid]+.25)/.045)*eye[lid]
    v[lid,2]-=.001*e[7]*eye[lid];return v

def lineage():
    rng=np.random.default_rng(2654);rows=[]
    for root in range(128):
        base=rng.uniform(-.8,.8,80);split='train' if root<80 else 'validation' if root<104 else 'test'
        for child in range(4):rows.append(dict(root=root,identity=root*4+child,split=split,factors=np.clip(base+rng.uniform(-.15,.15,80),-1,1)))
    return rows

def accessory(kind=1):
    if kind not in (1,2,3):raise ValueError('thin/transparent, thick/tinted, opaque')
    vv=[];tt=[];ss=[];alpha=[]
    for side in (-1,1):
        start=len(vv);n,m=48,8;r=.0007 if kind==1 else .0015
        for i in range(n):
            a=2*np.pi*i/n
            for j in range(m):
                b=2*np.pi*j/m;vv.append([side*.030+(.019+r*np.cos(b))*np.cos(a),-.026+(.014+r*np.cos(b))*np.sin(a),-.025+r*np.sin(b)]);ss.append(9);alpha.append(1.)
        for i in range(n):
            for j in range(m):
                a=start+i*m+j;b=start+((i+1)%n)*m+j;c=start+i*m+(j+1)%m;d=start+((i+1)%n)*m+(j+1)%m;tt.extend([[a,b,c],[b,d,c]])
        center=len(vv);vv.append([side*.030,-.026,-.025]);ss.append(11 if kind==3 else 10);alpha.append([.1,.4,1][kind-1])
        for i in range(n):
            a=2*np.pi*i/n;vv.append([side*.030+.018*np.cos(a),-.026+.013*np.sin(a),-.025]);ss.append(11 if kind==3 else 10);alpha.append([.1,.4,1][kind-1])
        for i in range(n):tt.append([center,center+1+i,center+1+(i+1)%n])
    return dict(vertices=np.array(vv),triangles=np.array(tt),semantic=np.array(ss),alpha=np.array(alpha))
