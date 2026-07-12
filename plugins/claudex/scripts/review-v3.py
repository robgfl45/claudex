#!/usr/bin/env python3
"""Frozen, technically read-only, structured five-persona review-v3 runner."""
from __future__ import annotations
import argparse, datetime as dt, fcntl, json, os, pathlib, signal, subprocess, sys, tempfile, time
from review_v3_contract import PERSONAS, canonical, load_raw, registry, render, sha
FOCUS={
"architecture-scope":"architecture, scope boundaries, dependencies, compatibility, and hidden design gaps",
"security-data":"authorization, input boundaries, secrets, privacy, concurrency, recovery, and data integrity",
"product-domain":"product behavior, domain rules, user journeys, acceptance criteria, and business edge cases",
"quality-accessibility-performance":"test strategy, accessibility, performance, resource bounds, and failure visibility",
"operations-deployment":"rollout, rollback, migrations, observability, ownership, version skew, and deployment failures"}
SCHEMA={"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":False,"required":["persona_id","snapshot_sha256","classification","findings"],"properties":{"persona_id":{"type":"string","enum":PERSONAS},"snapshot_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"classification":{"enum":["clean","material"]},"findings":{"type":"array","maxItems":100,"items":{"type":"object","additionalProperties":False,"required":["severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"],"properties":{"severity":{"enum":["high","medium","low"]},"scope_anchor":{"type":"string","minLength":1,"maxLength":8000},"underlying_risk":{"type":"string","minLength":1,"maxLength":8000},"failure_scenario":{"type":"string","minLength":1,"maxLength":8000},"repository_evidence":{"type":"array","minItems":1,"maxItems":50,"items":{"type":"string","minLength":1,"maxLength":8000}},"proposed_remedy":{"type":"string","minLength":1,"maxLength":8000}}}}}}

def atomic(path,data):
 fd,tmp=tempfile.mkstemp(prefix=path.name+".tmp.",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as out: out.write(data); out.flush(); os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  try: os.unlink(tmp)
  except FileNotFoundError: pass

def state_update(path,expected,updates):
 lock=path.with_name(path.name+".write-lock")
 with lock.open("a+",encoding="utf-8") as held:
  fcntl.flock(held,fcntl.LOCK_EX); lines=path.read_text().splitlines(); current={}
  for line in lines:
   if ":" in line: current.setdefault(*[x.strip() for x in line.split(":",1)])
  if current.get("phase")!=expected: return False
  updates={**updates,"last_updated_at":dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}; seen=set(); out=[]
  for line in lines:
   key=line.split(":",1)[0]
   if key in updates: out.append(f"{key}: {updates[key]}"); seen.add(key)
   else: out.append(line)
  out += [f"{k}: {v}" for k,v in updates.items() if k not in seen]; atomic(path,"\n".join(out)+"\n"); return True

def tree(root):
 result={}
 for path in sorted(root.rglob("*")):
  if path.is_file(): result[str(path.relative_to(root))]=sha(path)
 return result

def porcelain(repo, allowed=None):
 output=subprocess.run(["git","status","--porcelain=v1","--untracked-files=all"],cwd=repo,text=True,capture_output=True,check=True).stdout
 if allowed is None: return output
 relative=os.path.relpath(allowed.resolve(),repo.resolve())
 return "\n".join(line for line in output.splitlines() if not relative or line[3:]!=relative)+("\n" if output and any(not relative or line[3:]!=relative for line in output.splitlines()) else "")

def kill_group(proc):
 try: os.killpg(proc.pid,signal.SIGTERM)
 except ProcessLookupError: pass
 try: proc.wait(timeout=5); return
 except subprocess.TimeoutExpired: pass
 try: os.killpg(proc.pid,signal.SIGKILL)
 except ProcessLookupError: pass
 proc.wait()

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--state',type=pathlib.Path,required=True); ap.add_argument('--review-dir',type=pathlib.Path,required=True); ap.add_argument('--review-id',required=True); ap.add_argument('--topic',required=True); ap.add_argument('--repo',type=pathlib.Path,required=True); ap.add_argument('--codex',required=True); ap.add_argument('--timeout',type=int,default=300); a=ap.parse_args()
 gen=a.review_dir/'generations'/'1'; snap=gen/'PLAN.md'; live=a.repo/'PLAN.md'; manifest=gen/'manifest.json'; snapshot=sha(snap)
 if sha(live)!=snapshot: return 2
 schema=gen/'review-output.schema.json'
 if schema.exists(): return 2
 atomic(schema,canonical(SCHEMA)); raws=[]
 for persona in PERSONAS:
  raw=gen/f'{persona}.raw.json'; side=gen/f'{persona}.result.json'; prompt=gen/f'.{persona}.prompt.txt'; marker=a.state.parent/f'{a.review_id}-active-pgid'
  if raw.exists() or side.exists() or marker.exists(): return 2
  atomic(prompt,f"Persona ID: {persona}\nReview focus: {FOCUS[persona]}.\nReview only frozen snapshot: {snap}\nSnapshot SHA-256: {snapshot}\nTopic: {a.topic}\nReturn only the schema-conforming JSON final response. Never assign finding IDs. Critique the frozen plan; do not propose edits outside proposed_remedy.\n")
  baseline_git=porcelain(a.repo); baseline_tree=tree(a.review_dir); rc=125; error=None; proc=None
  try:
   with prompt.open('rb') as inp:
    proc=subprocess.Popen([a.codex,'exec','--sandbox','read-only','--ephemeral','--ignore-rules','--output-schema',str(schema),'--output-last-message',str(raw),'-'],stdin=inp,cwd=a.repo,start_new_session=True)
    atomic(marker,str(proc.pid)+"\n")
    try: rc=proc.wait(timeout=a.timeout)
    except subprocess.TimeoutExpired: kill_group(proc); rc=124
    finally:
     # Remove only after the owned group has been reaped, and never remove a replacement marker.
     try:
      if marker.read_text().strip()==str(proc.pid): marker.unlink()
     except OSError: pass
   after_tree=tree(a.review_dir); allowed=dict(baseline_tree)
   allowed[str(raw.relative_to(a.review_dir))]=after_tree.get(str(raw.relative_to(a.review_dir)),"")
   if rc!=0: raise ValueError(f"codex exited {rc}")
   if porcelain(a.repo,raw)!=baseline_git: raise ValueError("git worktree mutation detected")
   if after_tree!=allowed: raise ValueError("protected evidence mutation detected")
   obj=json.loads(raw.read_text()); atomic(raw,canonical(obj)); obj=load_raw(raw,persona,snapshot); raws.append(obj)
  except Exception as exc: error=str(exc)
  finally: prompt.unlink(missing_ok=True)
  side_obj={"schema_version":1,"generation":1,"persona_id":persona,"snapshot_sha256":snapshot,"raw_sha256":sha(raw) if raw.is_file() else None,"codex_exit_code":rc,"valid":error is None,"error":error,"completed_at":dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')}
  atomic(side,canonical(side_obj))
  if error:
   state_update(a.state,"reviewing",{"decision_signal":"degraded","clean":"false","coverage_complete":"false","revision_required":"false","phase":"summarizing"}); return 2
 reg=registry(a.review_id,snapshot,a.topic,str(a.repo),str(live),raws); registry_path=gen/'findings-registry.json'; consolidated=gen/'consolidated-findings.md'
 atomic(registry_path,canonical(reg)); atomic(consolidated,render(reg)); material=bool(reg['findings'])
 updates={"coverage_complete":"true","clean":str(not material).lower(),"decision_signal":"findings-returned" if material else "converged","registry_sha256":sha(registry_path),"consolidated_sha256":sha(consolidated),"reviewed_live_sha256":sha(live),"revision_required":"false","phase":"summarizing"}
 if not state_update(a.state,"reviewing",updates): return 2
 return 10 if material else 0
if __name__=='__main__': sys.exit(main())
