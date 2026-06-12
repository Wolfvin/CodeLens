#!/usr/bin/env python3
"""CodeLens Benchmark Runner — Accuracy and performance benchmarking.

Usage:
    python run_benchmarks.py                          # Full suite
    python run_benchmarks.py --quick                  # Fast subset
    python run_benchmarks.py --fixture vulnerable_app # Specific fixture
    python run_benchmarks.py --output results.json    # Save to file
    python run_benchmarks.py --compare baseline.json  # Compare vs baseline
"""
import os, sys, json, time, yaml, subprocess, argparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CODELENS_DIR = os.path.dirname(SCRIPT_DIR)
CODELENS_SCRIPTS = os.path.join(CODELENS_DIR, "scripts")
FIXTURES_DIR = os.path.join(SCRIPT_DIR, "fixtures")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
SNAPSHOTS_DIR = os.path.join(SCRIPT_DIR, "snapshots")

def ensure_dirs():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

def load_ground_truth(fixture_path):
    gt = os.path.join(fixture_path, "ground_truth.yaml")
    if not os.path.exists(gt): return {}
    with open(gt) as f: return yaml.safe_load(f) or {}

def run_codelens_command(command, workspace, extra_args=None, timeout=120):
    cmd = [sys.executable, os.path.join(CODELENS_SCRIPTS, "codelens.py"),
           command, workspace, "--format", "json", "--top", "0"]
    if extra_args: cmd.extend(extra_args)
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=CODELENS_DIR, env={**os.environ, "PYTHONPATH": CODELENS_SCRIPTS})
        elapsed = time.time() - start
        if proc.stdout.strip():
            try: result = json.loads(proc.stdout.strip())
            except json.JSONDecodeError: result = {"status": "error", "error": "JSON parse error"}
        else:
            result = {"status": "error", "error": "No output"}
        return result, elapsed, proc.returncode
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}, time.time() - start, -1
    except Exception as e:
        return {"status": "error", "error": str(e)}, time.time() - start, -1

def extract_findings(result, command):
    findings = []
    if result.get("status") not in ("ok", None, ""): return findings

    if command == "dead-code":
        for cat, items in (result.get("results", {}) or {}).items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                         "name": item.get("name", item.get("match","")), "category": cat})
    elif command == "secrets":
        for item in result.get("findings", []):
            if isinstance(item, dict):
                findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                 "name": item.get("type",""), "category": item.get("type","secret")})
    elif command == "complexity":
        for item in result.get("functions", []):
            if isinstance(item, dict):
                cc = item.get("cyclomatic", 0)
                findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                 "name": item.get("name",""), "category": "high_complexity" if cc > 15 else "normal",
                                 "cyclomatic": cc})
    elif command == "smell":
        for cat, items in (result.get("by_category", {}) or {}).items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                         "name": item.get("message",""), "category": cat})
    elif command == "debug-leak":
        for item in result.get("leaks", []):
            if isinstance(item, dict):
                findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                 "name": item.get("match",""), "category": item.get("category","")})
    elif command == "perf-hint":
        for item in result.get("hints", []):
            if isinstance(item, dict):
                findings.append({"file": item.get("file",""), "line": item.get("line",0),
                                 "name": item.get("hint",""), "category": item.get("category","")})
    elif command == "circular":
        for ct in ("function_calls", "import_chains", "css_imports"):
            for cycle in result.get(ct, []):
                if isinstance(cycle, dict):
                    chain = cycle.get("chain", cycle.get("cycle", []))
                    findings.append({"file": chain[0] if chain else "", "line": 0,
                                     "name": " -> ".join(str(n) for n in chain) if chain else "", "category": ct})
    return findings

def calc_metrics(tp, fp, fn, tn=0):
    p = tp/(tp+fp) if (tp+fp)>0 else 0.0
    r = tp/(tp+fn) if (tp+fn)>0 else 0.0
    f1 = 2*p*r/(p+r) if (p+r)>0 else 0.0
    fpr = fp/(fp+tn) if (fp+tn)>0 else 0.0
    return {"precision": round(p,4), "recall": round(r,4), "f1": round(f1,4),
            "fpr": round(fpr,4), "tp": tp, "fp": fp, "fn": fn, "tn": tn}

def scope_findings(findings, scope_files):
    """Filter findings to only those within scope_files. Returns (in_scope, out_of_scope)."""
    if not scope_files:
        return findings, []
    in_scope, out = [], []
    for f in findings:
        f_file = f.get("file", "")
        matched = any(sf in f_file or f_file.endswith(sf) for sf in scope_files)
        (in_scope if matched else out).append(f)
    return in_scope, out

def match_findings(findings, gt_locs, command):
    """Greedy best-match: highest score first, each GT matched at most once."""
    candidates = []
    for fi, f in enumerate(findings):
        ff, fl, fn, fc = f.get("file",""), f.get("line",0), f.get("name","").lower(), f.get("category","").lower()
        for gi, g in enumerate(gt_locs):
            gf, gl, gn, gt = g.get("file",""), g.get("line",0), g.get("name","").lower(), g.get("type","").lower()
            gc = g.get("category","").lower()
            file_ok = gf in ff or ff.endswith(gf) or os.path.basename(gf)==os.path.basename(ff)
            if not file_ok: continue
            score = 0; matched = False
            if command == "secrets":
                ld = abs(fl-gl) if fl and gl else 999
                nm = gn and (gn in fn or fn in gn)
                tm = gt and gt in fn
                if ld <= 3: matched, score = True, 100-ld
                elif nm or tm: matched, score = True, 50
            elif command == "complexity":
                nm = gn and (gn in fn or fn in gn)
                if nm: matched, score = True, 100 if gn==fn else 80
            elif command == "dead-code":
                nm = gn and (gn in fn or fn in gn)
                ld = abs(fl-gl) if fl and gl else 999
                if nm and ld<=3: matched, score = True, 100
                elif nm: matched, score = True, 80
                elif ld<=3: matched, score = True, 60
            elif command == "debug-leak":
                ld = abs(fl-gl) if fl and gl else 999
                cm = gc and (gc in fc or fc in gc)
                if ld<=3: matched, score = True, 100-ld
                elif cm: matched, score = True, 50
            elif command in ("smell", "perf-hint"):
                nm = gn and (gn in fn or fn in gn)
                cm = gc and (gc in fc or fc in gc)
                if cm and nm: matched, score = True, 100
                elif nm: matched, score = True, 80
                elif cm: matched, score = True, 60
            elif command == "circular":
                cyc = g.get("cycle", [])
                if cyc:
                    overlap = sum(1 for n in cyc if str(n).lower() in fn)
                    if overlap >= len(cyc)*0.5: matched, score = True, overlap*30
                else: matched, score = True, 10
            if matched: candidates.append((fi, gi, score))
    candidates.sort(key=lambda x: -x[2])
    tp, mf, mg = 0, set(), set()
    for fi, gi, _ in candidates:
        if fi not in mf and gi not in mg: tp += 1; mf.add(fi); mg.add(gi)
    return tp, len(findings)-len(mf), len(gt_locs)-len(mg)

COMMANDS = {
    "dead-code":  {"gt_key":"dead_code",  "desc":"Dead code detection",     "t":0.85,"c":0.82},
    "secrets":    {"gt_key":"secrets",     "desc":"Hardcoded secrets",       "t":0.95,"c":0.90},
    "complexity": {"gt_key":"complexity",  "desc":"High complexity",         "t":0.98,"c":0.95},
    "smell":      {"gt_key":"dead_code",   "desc":"Code smells",             "t":0.80,"c":0.78},
    "debug-leak": {"gt_key":"debug_leaks", "desc":"Debug leaks",             "t":0.85,"c":0.75},
    "perf-hint":  {"gt_key":"perf_antipatterns","desc":"Performance hints",  "t":0.75,"c":0.70},
    "circular":   {"gt_key":"circular_dependencies","desc":"Circular deps",  "t":0.90,"c":0.85},
}
QUICK = ["dead-code","secrets","complexity","debug-leak"]

def run_benchmark_suite(fixture_name=None, quick=False, output_file=None, compare_file=None):
    ensure_dirs()
    ts = datetime.now(timezone.utc).isoformat()
    cmds = QUICK if quick else list(COMMANDS.keys())
    fdirs = [os.path.join(FIXTURES_DIR, fixture_name)] if fixture_name else [
        os.path.join(FIXTURES_DIR, d) for d in sorted(os.listdir(FIXTURES_DIR))
        if os.path.isdir(os.path.join(FIXTURES_DIR, d)) and os.path.exists(os.path.join(FIXTURES_DIR, d, "ground_truth.yaml"))]
    ar = {"timestamp":ts, "version":"1.0.0", "quick_mode":quick, "fixtures":{}, "summary":{}, "token_efficiency":{}}
    for fd in fdirs:
        fn = os.path.basename(fd); ic = "clean" in fn
        gt = load_ground_truth(fd); fr = {"commands":{}}
        print(f"\n{'='*70}\n  Benchmarking: {fn}\n{'='*70}")
        for cmd in cmds:
            cfg = COMMANDS[cmd]; gk = cfg["gt_key"]
            print(f"  codelens {cmd} {fn} ...", end=" ", flush=True)
            res, elapsed, _ = run_codelens_command(cmd, fd)
            findings = extract_findings(res, cmd)
            gd = gt.get(gk, {}); exp = gd.get("expected", gd.get("expected_high",0))
            glocs = gd.get("locations", [])
            scope = gd.get("scope_files", [])
            if ic:
                src = sum(1 for r,d,fs in os.walk(fd) for f in fs if any(f.endswith(e) for e in ('.py','.js','.ts','.tsx','.jsx'))
                          if not any(x in r for x in ('.codelens','__pycache__','node_modules')))
                fset = set(f.get("file","") for f in findings if f.get("file"))
                fp = len(findings); tn = max(src-len(fset), 0)
                metrics = calc_metrics(0, fp, 0, tn)
            else:
                sf, _ = scope_findings(findings, scope)
                if cmd == "complexity":
                    th = gd.get("threshold",15)
                    sf = [f for f in sf if f.get("cyclomatic",0) >= th]
                tp, fp, fn2 = match_findings(sf, glocs, cmd)
                metrics = calc_metrics(tp, fp, fn2)
            mt = metrics["f1"] >= cfg["t"] if not ic else metrics.get("fpr",1) < 0.05
            bc = metrics["f1"] > cfg["c"]
            cr = {"description":cfg["desc"],"expected_count":exp,"found_count":len(findings),
                  "metrics":metrics,"elapsed_seconds":round(elapsed,3),
                  "target_f1":cfg["t"],"competitor_f1":cfg["c"],
                  "meets_target":mt,"beats_competitor":bc}
            fr["commands"][cmd] = cr
            if ic:
                icon = "✓" if mt else "✗"
                print(f"{icon} FPR={metrics.get('fpr',0):.3f} ({fp}FP {tn}TN) {elapsed:.2f}s")
            else:
                icon = "✓" if mt else "✗"
                print(f"{icon} F1={metrics['f1']:.3f} P={metrics['precision']:.3f} R={metrics['recall']:.3f} "
                      f"TP={metrics['tp']} FP={metrics['fp']} FN={metrics['fn']} {elapsed:.2f}s")
        ar["fixtures"][fn] = fr
    ar["summary"] = _summary(ar)
    ar["token_efficiency"] = _tokens(fdirs, quick)
    sp = output_file or os.path.join(RESULTS_DIR, f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(sp,'w') as f: json.dump(ar,f,indent=2,ensure_ascii=False)
    with open(os.path.join(RESULTS_DIR,"latest.json"),'w') as f: json.dump(ar,f,indent=2,ensure_ascii=False)
    print(f"\nSaved: {sp}")
    if compare_file and os.path.exists(compare_file): _compare(ar, compare_file)
    _report(ar)
    return ar

def _summary(ar):
    f1s,ps,rs,fprs = [],[],[],[]; mt=bt=tot=0
    for fn,fd in ar["fixtures"].items():
        ic = "clean" in fn
        for cn,cd in fd.get("commands",{}).items():
            tot+=1; m=cd.get("metrics",{})
            if ic: fprs.append(m.get("fpr",0))
            elif m.get("f1",0)>0 or m.get("tp",0)>0:
                f1s.append(m["f1"]); ps.append(m["precision"]); rs.append(m["recall"])
            if cd.get("meets_target"): mt+=1
            if cd.get("beats_competitor"): bt+=1
    return {"avg_f1":round(sum(f1s)/len(f1s),4) if f1s else 0,
            "avg_precision":round(sum(ps)/len(ps),4) if ps else 0,
            "avg_recall":round(sum(rs)/len(rs),4) if rs else 0,
            "avg_fpr_clean":round(sum(fprs)/len(fprs),4) if fprs else 0,
            "meets_target_pct":round(mt/tot*100,1) if tot else 0,
            "beats_competitor_pct":round(bt/tot*100,1) if tot else 0,
            "total_commands_run":tot}

def _tokens(fdirs, quick):
    if not fdirs: return {}
    ws = fdirs[0]; cmds = QUICK[:2] if quick else ["dead-code","secrets"]; out = {}
    for cmd in cmds:
        cr = {}
        for mode, extra in [("json",["--format","json"]),("ai",["--format","ai"]),("ai_lite",["--format","ai","--lite"])]:
            r,e,_ = run_codelens_command(cmd, ws, extra_args=extra)
            s = json.dumps(r) if isinstance(r,dict) else str(r)
            cr[mode] = {"estimated_tokens": len(s)//4}
        jt = cr["json"]["estimated_tokens"] or 1
        cr["ai_savings_pct"] = round((1-cr["ai"]["estimated_tokens"]/jt)*100,1)
        cr["ai_lite_savings_pct"] = round((1-cr["ai_lite"]["estimated_tokens"]/jt)*100,1)
        out[cmd] = cr
    return out

def _compare(cur, bf):
    try:
        with open(bf) as f: base = json.load(f)
    except: print("⚠ Could not load baseline"); return
    print(f"\n── vs Baseline: {bf} ──")
    for fn in cur.get("fixtures",{}):
        cf = cur["fixtures"][fn]; bff = base.get("fixtures",{}).get(fn,{})
        for cn in cf.get("commands",{}):
            cf1 = cf["commands"][cn].get("metrics",{}).get("f1",0)
            bf1 = bff.get("commands",{}).get(cn,{}).get("metrics",{}).get("f1",0)
            d = cf1-bf1
            if abs(d)>0.05: print(f"  {'↑' if d>0 else '⚠'} {fn}/{cn}: F1 {bf1:.3f}→{cf1:.3f} (Δ{d:+.3f})")

def _report(ar):
    s = ar.get("summary",{})
    print(f"\n{'='*70}\n  CODELENS BENCHMARK REPORT\n  {ar.get('timestamp','')}\n{'='*70}")
    print(f"\n── Summary ──")
    print(f"  Avg F1: {s.get('avg_f1',0):.3f}  Precision: {s.get('avg_precision',0):.3f}  Recall: {s.get('avg_recall',0):.3f}")
    print(f"  Avg FPR (clean): {s.get('avg_fpr_clean',0):.3f}  Targets met: {s.get('meets_target_pct',0):.1f}%  Beats competitor: {s.get('beats_competitor_pct',0):.1f}%")
    for fn,fd in ar.get("fixtures",{}).items():
        ic = "clean" in fn
        print(f"\n── {fn} {'(FPR)' if ic else ''} ──")
        for cn,cd in fd.get("commands",{}).items():
            m=cd.get("metrics",{}); icon="✓" if cd.get("meets_target") else "✗"
            if ic:
                print(f"  {cn:<14} FPR={m.get('fpr',0):.3f} FP={m.get('fp',0)} TN={m.get('tn',0)} {icon}")
            else:
                print(f"  {cn:<14} F1={m.get('f1',0):.3f} P={m.get('precision',0):.3f} R={m.get('recall',0):.3f} "
                      f"TP={m.get('tp',0)} FP={m.get('fp',0)} FN={m.get('fn',0)} {icon}")
    td = ar.get("token_efficiency",{})
    if td:
        print(f"\n── Token Efficiency ──")
        for cn,ct in td.items():
            if isinstance(ct,dict) and "json" in ct:
                jt=ct["json"].get("estimated_tokens",0); at=ct["ai"].get("estimated_tokens",0)
                lt=ct["ai_lite"].get("estimated_tokens",0)
                print(f"  {cn:<14} JSON:{jt} AI:{at} AI+Lite:{lt} Lite save:{ct.get('ai_lite_savings_pct',0):+.1f}%")
    print(f"\n{'='*70}")

def main():
    p = argparse.ArgumentParser(description="CodeLens Benchmark Suite")
    p.add_argument("--quick",action="store_true")
    p.add_argument("--fixture",type=str,default=None)
    p.add_argument("--output","-o",type=str,default=None)
    p.add_argument("--compare",type=str,default=None)
    a = p.parse_args()
    r = run_benchmark_suite(fixture_name=a.fixture, quick=a.quick, output_file=a.output, compare_file=a.compare)
    if r.get("summary",{}).get("meets_target_pct",0) < 50: sys.exit(1)

if __name__ == "__main__": main()
