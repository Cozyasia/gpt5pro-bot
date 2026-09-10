"""Explicit local evaluation registration; never print the returned token."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def main():
    p=argparse.ArgumentParser();p.add_argument('--secret-file',type=Path,required=True);a=p.parse_args()
    if os.environ.get('CI'): raise SystemExit('Local evaluation only; CI registration forbidden')
    email=os.environ.get('V265_EVALUATION_EMAIL','').strip()
    name=os.environ.get('V265_EVALUATION_NAME','').strip()
    if not email or not name: raise SystemExit('Set V265_EVALUATION_EMAIL and V265_EVALUATION_NAME for the authorised registrant')
    path=a.secret_file.resolve();repo=Path(__file__).resolve().parents[1]
    if path==repo or repo in path.parents: raise SystemExit('Secret file must be outside the repository')
    # Reserve an owner-only file before requesting the one-time token.
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        body=urllib.parse.urlencode({'name':name,'mail':email,'comment':'Evaluation of 3D face reconstruction on public fixtures only. No private user photos or production traffic.'}).encode()
        req=urllib.request.Request('https://api.metahumansdk.io/auth/token',data=body,headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as response:
            payload=json.loads(response.read(65536))
        token=payload.get('result',{}).get('token')
        if not isinstance(token,str) or not token: raise ValueError('missing token')
        with os.fdopen(fd,'w') as handle:
            fd=None;handle.write(token+'\n')
        print('Evaluation token saved; production rights remain unqualified')
    except Exception:
        if fd is not None: os.close(fd)
        path.unlink(missing_ok=True)
        raise SystemExit('Registration failed; no credentials or response body logged') from None


if __name__=='__main__': main()
