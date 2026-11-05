"""Explicit local evaluation registration; never print the returned token."""
import argparse
import json
import os
import time
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
        body=urllib.parse.urlencode({'name':name,'mail':email,'comment':'Technical evaluation of MetaHumanSDK 3D Face Reconstruction for potential commercial server-side AI selfie use. Evaluation will use public test fixtures only; no private/user photographs.'}).encode()
        req=urllib.request.Request('https://api.metahumansdk.io/auth/token',data=body,headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req,timeout=20) as response:
                    print('registration_attempt',attempt+1,'http_status',response.status,flush=True)
                    payload=json.loads(response.read(65536))
                break
            except urllib.error.HTTPError as error:
                print('registration_attempt',attempt+1,'http_status',error.code,flush=True)
                error.close()
                if error.code not in (500,502,503,504) or attempt==2: raise
            except (urllib.error.URLError,TimeoutError):
                print('registration_attempt',attempt+1,'transport_error',flush=True)
                if attempt==2: raise
            time.sleep((3,8)[attempt])
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
