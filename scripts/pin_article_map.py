#!/usr/bin/env python3
"""Write /workspace/affiliate/pin-article-map.json mapping each pin to its live article URL (for Affiliate Dave)."""
import json, re, glob, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pins = {p['id']: p for p in json.load(open('/workspace/affiliate/pins.json'))}
out = []
for f in sorted(glob.glob('content/2*.md')):
    t = open(f).read()
    m = re.search(r'^id: (.+)$', t, re.M); s = re.search(r'^slug: (.+)$', t, re.M)
    p = pins.get(m.group(1).strip()) if m else None
    if p and s:
        out.append({"pin_id": p['id'], "pin_url": p.get('pin_url', ''), "product": p['product_name'],
                    "article_url": f"https://joehartmann.com/articles/{s.group(1).strip()}/"})
json.dump(out, open('/workspace/affiliate/pin-article-map.json', 'w'), indent=1)
print(f"Mapped {len(out)} pins")
