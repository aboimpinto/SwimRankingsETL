"""Synthetic publication adapter for contract tests; never used against an app."""
import json
from pathlib import Path
import sys
stage, cp, output = sys.argv[1:]
c = json.loads(Path(cp).read_text()); b = Path(c['batchDirectory'])
r = {k: c[k] for k in ['batchId', 'inputHash', 'meetIds']}
if stage == 'publish':
    count = b / 'publish-count.txt'; n = int(count.read_text()) if count.exists() else 0; count.write_text(str(n+1))
    r.update(status='published', publication='123')
    (b / 'synthetic-commit.json').write_text(json.dumps(r))
    if (b / 'lose-receipt').exists(): raise SystemExit(1)
    if (b / 'wrong-receipt').exists(): r['batchId'] = 'wrong'
elif stage == 'reconcile':
    r = json.loads((b / 'synthetic-commit.json').read_text())
else:
    if (b / 'fail-verify').exists(): raise SystemExit(1)
    r.update(status='passed', publication=c['publication'], checked=8, failed=0)
Path(output).write_text(json.dumps(r))
