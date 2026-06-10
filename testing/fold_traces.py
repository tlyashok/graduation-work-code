# -*- coding: utf-8 -*-
# go tool pprof -traces -> свёрнутые стеки (folded) для flamegraph.pl
import sys, re
folded = {}
block = []
def flush(block):
    stack = []
    val = 0
    for i, ln in enumerate(block):
        m = re.match(r'\s+([\d.]+)(ms|s|us|ns)?\s+(\S.*)$', ln)
        if i == 0 and m:
            num = float(m.group(1)); unit = m.group(2) or 'ms'
            mult = {'ns':1e-6,'us':1e-3,'ms':1,'s':1e3}[unit]
            val = num*mult  # в мс
            stack.append(m.group(3).strip())
        else:
            f = ln.strip()
            if f and not set(f) <= {'-','+',' '}:
                stack.append(f)
    if stack and val > 0:
        key = ";".join(reversed(stack))   # корень слева
        folded[key] = folded.get(key, 0) + val

for ln in sys.stdin:
    if set(ln.strip()) <= {'-','+'} and ln.strip():
        if block: flush(block); block = []
    elif ln.strip().startswith('File:') or ln.strip().startswith('Type:') or ln.strip().startswith('Build') or ln.strip().startswith('Time:') or ln.strip().startswith('Duration:'):
        continue
    else:
        if ln.strip(): block.append(ln.rstrip())
if block: flush(block)

for k,v in folded.items():
    print(f"{k} {int(round(v))}")
