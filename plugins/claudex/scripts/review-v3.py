#!/usr/bin/env python3
"""Frozen, read-only, structured five-persona review-v3 runner."""
import argparse, datetime, hashlib, json, os, pathlib, signal, subprocess, sys
PERSONAS=["architecture-scope","security-data","product-domain","quality-accessibility-performance","operations-deployment"]
FOCUS={
"architecture-scope":"architecture, scope boundaries, dependencies, compatibility, and hidden design gaps",
"security-data":"authorization, input boundaries, secrets, privacy, concurrency, recovery, and data integrity",
"product-domain":"product behavior, domain rules, user journeys, acceptance criteria, and business edge cases",
"quality-accessibility-performance":"test strategy, accessibility, performance, resource bounds, and failure visibility",
"operations-deployment":"rollout, rollback, migrations, observability, ownership, version skew, and deployment failures"}
MAX_STRING=8000; MAX_EVIDENCE=50; MAX_FINDINGS=100

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic(path,data):
 p=path.with_name('.'+path.name+'.tmp.'+str(os.getpid())); p.write_text(data,encoding='utf-8'); os.replace(p,path)
def validate(raw,persona,sha):
 if not isinstance(raw,dict) or set(raw)!={"persona_id","snapshot_sha256","classification","findings"}: raise ValueError("result keys mismatch")
 if raw["persona_id"]!=persona or raw["snapshot_sha256"]!=sha: raise ValueError("persona/hash binding mismatch")
 if raw["classification"] not in {"clean","material"} or not isinstance(raw["findings"],list): raise ValueError("classification/findings type invalid")
 if len(raw["findings"])>MAX_FINDINGS: raise ValueError("too many findings")
 if (raw["classification"]=="clean") != (len(raw["findings"])==0): raise ValueError("classification/findings mismatch")
 req={"severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"}
 for f in raw["findings"]:
  if not isinstance(f,dict) or set(f)!=req: raise ValueError("finding keys mismatch (model IDs are forbidden)")
  if f["severity"] not in {"high","medium","low"}: raise ValueError("severity invalid")
  for k in ("scope_anchor","underlying_risk","failure_scenario","proposed_remedy"):
   if not isinstance(f[k],str) or not f[k].strip() or len(f[k])>MAX_STRING: raise ValueError(k+" invalid")
  ev=f["repository_evidence"]
  if not isinstance(ev,list) or not ev or len(ev)>MAX_EVIDENCE or any(not isinstance(x,str) or not x.strip() or len(x)>MAX_STRING for x in ev): raise ValueError("repository_evidence invalid")
 return raw

def render(reg):
 out=["# Consolidated review-v3 findings\n",f"Review ID: `{reg['review_id']}`  ",f"Snapshot SHA-256: `{reg['snapshot_sha256']}`\n"]
 if not reg['findings']: out.append("No substantive findings.\n")
 for f in reg['findings']:
  out += [f"## {f['finding_id']} — {f['severity']}\n",f"**Persona:** `{f['persona_id']}`\n",f"**Scope anchor:** {f['scope_anchor']}\n",f"**Underlying risk:** {f['underlying_risk']}\n",f"**Failure scenario:** {f['failure_scenario']}\n","**Repository evidence:**",*[f"- {x}" for x in f['repository_evidence']],"",f"**Proposed remedy (not accepted by implication):** {f['proposed_remedy']}\n"]
 return '\n'.join(out).rstrip()+"\n"
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--state',type=pathlib.Path,required=True); ap.add_argument('--review-dir',type=pathlib.Path,required=True); ap.add_argument('--review-id',required=True); ap.add_argument('--topic',required=True); ap.add_argument('--repo',type=pathlib.Path,required=True); ap.add_argument('--codex',required=True); ap.add_argument('--timeout',type=int,default=300); a=ap.parse_args()
 gen=a.review_dir/'generations'/'1'; snap=gen/'PLAN.md'; manifest=gen/'manifest.json'; sha=digest(snap); live=a.repo/'PLAN.md'; live_sha=digest(live)
 if sha!=live_sha: return 2
 raw_paths=[]; results=[]
 for persona in PERSONAS:
  raw=gen/f'{persona}.raw.json'; side=gen/f'{persona}.result.json'; prompt=gen/f'.{persona}.prompt.txt'
  if raw.exists() or side.exists(): return 2
  prompt.write_text(f'''Persona ID: {persona}\nReview focus: {FOCUS[persona]}.\nReview only frozen snapshot: {snap}\nSnapshot SHA-256: {sha}\nTopic: {a.topic}\n\nREAD-ONLY CRITIC CONTRACT: Do not edit the live or frozen plan, repository files, state, manifests, or any other persona artifact. Critique only. Separate underlying_risk from proposed_remedy; identifying/accepting a risk never accepts a remedy.\nWrite ONLY JSON to {raw}\nExact top-level keys: persona_id, snapshot_sha256, classification (clean|material), findings. A material finding has exactly severity (high|medium|low), scope_anchor, underlying_risk, failure_scenario, repository_evidence (non-empty string array), proposed_remedy. Clean has no findings. Never emit a finding ID.\n''')
  before=(digest(snap),digest(live)); rc=125
  try:
   with prompt.open('rb') as inp:
    proc=subprocess.Popen([a.codex,'exec','--dangerously-bypass-approvals-and-sandbox'],stdin=inp,cwd=a.repo,start_new_session=True)
    try: rc=proc.wait(timeout=a.timeout)
    except subprocess.TimeoutExpired:
     try: os.killpg(proc.pid,signal.SIGTERM)
     except ProcessLookupError: pass
     try: proc.wait(timeout=5)
     except subprocess.TimeoutExpired:
      try: os.killpg(proc.pid,signal.SIGKILL)
      except ProcessLookupError: pass
      proc.wait()
     rc=124
  except OSError: rc=125
  after=(digest(snap),digest(live)); err=None; obj=None
  try:
   if rc!=0 or before!=(sha,live_sha) or after!=(sha,live_sha): raise ValueError('nonzero, timeout, or plan mutation')
   obj=validate(json.loads(raw.read_text()),persona,sha)
  except Exception as e: err=str(e)
  side_obj={"persona_id":persona,"snapshot_sha256":sha,"raw_path":str(raw),"raw_sha256":digest(raw) if raw.is_file() else None,"codex_exit_code":rc,"valid":err is None,"error":err,"completed_at":datetime.datetime.now(datetime.timezone.utc).isoformat()}
  atomic(side,json.dumps(side_obj,indent=2,sort_keys=True)+'\n'); prompt.unlink(missing_ok=True)
  if err: return 2
  raw_paths.append(raw); results.append(obj)
 findings=[]; n=1
 for obj in results:
  for f in obj['findings']:
   findings.append({"finding_id":f"CX-{n:04d}","persona_id":obj['persona_id'],**f}); n+=1
 reg={"schema_version":1,"review_id":a.review_id,"engine":"review-v3","snapshot_sha256":sha,"topic":a.topic,"repo_root":str(a.repo),"source_plan_path":str(live),"persona_order":PERSONAS,"findings":findings}
 registry=gen/'findings-registry.json'; consolidated=gen/'consolidated-findings.md'; atomic(registry,json.dumps(reg,indent=2,sort_keys=True)+'\n'); atomic(consolidated,render(reg))
 decision='findings-returned' if findings else 'converged'; clean='false' if findings else 'true'
 updates={"coverage_complete":"true","clean":clean,"decision_signal":decision,"registry_sha256":digest(registry),"consolidated_sha256":digest(consolidated),"reviewed_live_sha256":digest(live),"phase":"summarizing"}
 lines=[]; seen=set()
 for line in a.state.read_text().splitlines():
  key=line.split(':',1)[0]
  if key in updates: lines.append(f"{key}: {updates[key]}"); seen.add(key)
  else: lines.append(line)
 for key,value in updates.items():
  if key not in seen: lines.append(f"{key}: {value}")
 atomic(a.state,"\n".join(lines)+"\n"); return 10 if findings else 0
if __name__=='__main__': sys.exit(main())
