#!/usr/bin/env python3
"""CodeLens Regression Checker — CI/CD compatible.

Compares current benchmark results against a baseline snapshot.
Exits 1 on regression (>5% F1 decrease). Exit 0 = pass.

Usage:
    python check_regression.py                    # vs latest snapshot
    python check_regression.py --baseline b.json  # vs specific baseline
    python check_regression.py --update           # save current as baseline
    python check_regression.py --threshold 0.10   # 10% threshold
"""
import os, sys, json, argparse
from datetime import datetime, timezone
from typing import Dict, Any, Optional

SDIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(SDIR, "results")
SNAPSHOTS = os.path.join(SDIR, "snapshots")
LATEST = os.path.join(RESULTS, "latest.json")

def load(path):
    if not os.path.exists(path): return None
    try:
        with open(path) as f: return json.load(f)
    except: return None

def find_snapshot():
    if not os.path.isdir(SNAPSHOTS): return None
    ss = sorted([f for f in os.listdir(SNAPSHOTS) if f.endswith('.json')], reverse=True)
    return os.path.join(SNAPSHOTS, ss[0]) if ss else None

def compare(cur, base, threshold=0.05):
    r = {"threshold":threshold,"regressions":[],"improvements":[],"has_regression":False}
    for fn in cur.get("fixtures",{}):
        cf = cur["fixtures"][fn]; bf = base.get("fixtures",{}).get(fn,{})
        for cn in cf.get("commands",{}):
            cm = cf["commands"][cn].get("metrics",{})
            bm = bf.get("commands",{}).get(cn,{}).get("metrics",{})
            entry = {"fixture":fn,"command":cn,"base":bm,"current":cm}
            reg = imp = False
            for m in ("f1","precision","recall"):
                cv,bv = cm.get(m,0), bm.get(m,0); d = cv-bv
                if cv>0 or bv>0:
                    if d < -threshold: reg=True; entry[f"{m}_delta"]=round(d,4)
                    elif d > threshold: imp=True; entry[f"{m}_delta"]=round(d,4)
            if cm.get("fpr",0)-bm.get("fpr",0)>threshold:
                reg=True; entry["fpr_delta"]=round(cm["fpr"]-bm["fpr"],4)
            if reg: r["regressions"].append(entry); r["has_regression"]=True
            elif imp: r["improvements"].append(entry)
    sd = cur.get("summary",{}); bd = base.get("summary",{})
    r["summary_delta"] = {"avg_f1_delta": round(sd.get("avg_f1",0)-bd.get("avg_f1",0),4)}
    if sd.get("avg_f1",0)-bd.get("avg_f1",0) < -threshold: r["has_regression"]=True
    return r

def save_snapshot(data, name=None):
    os.makedirs(SNAPSHOTS, exist_ok=True)
    if not name: name = f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    if not name.endswith('.json'): name += '.json'
    p = os.path.join(SNAPSHOTS, name)
    with open(p,'w') as f: json.dump(data,f,indent=2,ensure_ascii=False)
    print(f"Snapshot: {p}")
    return p

def report(comp):
    print(f"\n{'='*70}\n  REGRESSION CHECK (threshold={comp['threshold']*100:.0f}%)\n{'='*70}")
    if comp["regressions"]:
        print(f"\n  ⚠ REGRESSIONS ({len(comp['regressions'])}):")
        for r in comp["regressions"]:
            print(f"    {r['fixture']}/{r['command']}:")
            for m in ("f1","precision","recall"):
                if f"{m}_delta" in r:
                    print(f"      {m}: {r['base'].get(m,0):.3f}→{r['current'].get(m,0):.3f} (Δ{r[f'{m}_delta']:+.3f})")
    else:
        print("\n  ✓ NO REGRESSIONS")
    if comp["improvements"]:
        print(f"\n  ↑ IMPROVEMENTS ({len(comp['improvements'])}):")
        for r in comp["improvements"]:
            ds = [f"{m}:Δ{r[f'{m}_delta']:+.3f}" for m in ("f1","precision","recall") if f"{m}_delta" in r]
            print(f"    + {r['fixture']}/{r['command']}: {', '.join(ds)}")
    sd = comp.get("summary_delta",{})
    print(f"\n  Summary: avg_f1 Δ={sd.get('avg_f1_delta',0):+.4f}")
    res = "FAIL" if comp["has_regression"] else "PASS"
    print(f"  RESULT: {res}\n{'='*70}\n")

def main():
    p = argparse.ArgumentParser(description="CodeLens Regression Checker")
    p.add_argument("--baseline","-b",type=str,default=None)
    p.add_argument("--current","-c",type=str,default=LATEST)
    p.add_argument("--threshold","-t",type=float,default=0.05)
    p.add_argument("--update","-u",action="store_true")
    p.add_argument("--output","-o",type=str,default=None)
    a = p.parse_args()
    cur = load(a.current)
    if not cur: print(f"No results at {a.current}. Run benchmarks first."); sys.exit(2)
    if a.update: save_snapshot(cur); sys.exit(0)
    bp = a.baseline or find_snapshot()
    if not bp: print("No baseline. Saving current."); save_snapshot(cur); sys.exit(0)
    base = load(bp)
    if not base: print(f"Can't load {bp}"); sys.exit(2)
    comp = compare(cur, base, a.threshold)
    if a.output:
        with open(a.output,'w') as f: json.dump(comp,f,indent=2,ensure_ascii=False)
    report(comp)
    sys.exit(1 if comp["has_regression"] else 0)

if __name__ == "__main__": main()
