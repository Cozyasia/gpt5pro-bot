import argparse,json
from pathlib import Path
from . import audit,qualification,expressions,attachment

def run(out):
 out=Path(out);audit.run(out)
 if not json.loads((out/'summary.json').read_text())['contact_pass']:return
 qualification.run(out)
 if not json.loads((out/'qualification.json').read_text())['passed']:return
 expressions.run(out)
 if not json.loads((out/'expression-summary.json').read_text())['passed']:return
 attachment.run(out)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
