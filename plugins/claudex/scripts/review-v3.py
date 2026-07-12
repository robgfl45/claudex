#!/usr/bin/env python3
"""Frozen, technically read-only, structured five-persona review-v3 runner."""
from __future__ import annotations
import argparse, datetime as dt, fcntl, json, os, pathlib, signal, stat, subprocess, sys, tempfile, time
from review_v3_contract import PERSONAS, canonical, load_bounded_json, load_manifest, load_raw, registry, render, sha
FOCUS={"architecture-scope":"architecture, scope boundaries, dependencies, compatibility, and hidden design gaps","security-data":"authorization, input boundaries, secrets, privacy, concurrency, recovery, and data integrity","product-domain":"product behavior, domain rules, user journeys, acceptance criteria, and business edge cases","quality-accessibility-performance":"test strategy, accessibility, performance, resource bounds, and failure visibility","operations-deployment":"rollout, rollback, migrations, observability, ownership, version skew, and deployment failures"}
SCHEMA={"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","additionalProperties":False,"required":["persona_id","snapshot_sha256","classification","findings"],"properties":{"persona_id":{"type":"string","enum":PERSONAS},"snapshot_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"classification":{"enum":["clean","material"]},"findings":{"type":"array","maxItems":100,"items":{"type":"object","additionalProperties":False,"required":["severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"],"properties":{"severity":{"enum":["high","medium","low"]},"scope_anchor":{"type":"string","minLength":1,"maxLength":8000},"underlying_risk":{"type":"string","minLength":1,"maxLength":8000},"failure_scenario":{"type":"string","minLength":1,"maxLength":8000},"repository_evidence":{"type":"array","minItems":1,"maxItems":50,"items":{"type":"string","minLength":1,"maxLength":8000}},"proposed_remedy":{"type":"string","minLength":1,"maxLength":8000}}}}}}

def atomic(path,data):
 fd,tmp=tempfile.mkstemp(prefix=path.name+".tmp.",dir=path.parent)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as out: out.write(data); out.flush(); os.fsync(out.fileno())
  os.replace(tmp,path)
 finally:
  try: os.unlink(tmp)
  except FileNotFoundError: pass

def parse_state(path):
 result={}
 for line in path.read_text(encoding='utf-8').splitlines():
  if ':' in line: result[line.split(':',1)[0]]=line.split(':',1)[1].strip().strip('"')
 return result

def state_update(path,expected,updates):
 lock=path.with_name(path.name+".write-lock")
 with lock.open("a+",encoding="utf-8") as held:
  fcntl.flock(held,fcntl.LOCK_EX); current=parse_state(path)
  if current.get("phase")!=expected: return False
  lines=path.read_text().splitlines(); updates={**updates,"last_updated_at":dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")}; seen=set(); out=[]
  for line in lines:
   key=line.split(":",1)[0]
   if key in updates: out.append(f"{key}: {updates[key]}"); seen.add(key)
   else: out.append(line)
  out += [f"{k}: {v}" for k,v in updates.items() if k not in seen]; atomic(path,"\n".join(out)+"\n"); return True

def repo_snapshot(repo, excluded_root=None):
 names=subprocess.run(['git','ls-files','-c','-o','--exclude-standard','-z'],cwd=repo,capture_output=True,check=True).stdout.split(b'\0'); result={}
 for raw in names:
  if not raw: continue
  rel=os.fsdecode(raw); p=repo/rel
  if excluded_root is not None and (p == excluded_root or excluded_root in p.parents): continue
  st=os.lstat(p); mode=stat.S_IMODE(st.st_mode)
  if stat.S_ISLNK(st.st_mode): value=('symlink',mode,os.readlink(p))
  elif stat.S_ISREG(st.st_mode): value=('file',mode,sha(p))
  else: value=('other',mode,st.st_size)
  result[rel]=value
 return result

def evidence_snapshot(root, excluded):
 result={}
 for p in sorted(root.rglob('*')):
  if p in excluded: continue
  st=os.lstat(p); rel=str(p.relative_to(root)); mode=stat.S_IMODE(st.st_mode)
  result[rel]=('symlink',mode,os.readlink(p)) if stat.S_ISLNK(st.st_mode) else (('file',mode,sha(p)) if stat.S_ISREG(st.st_mode) else ('dir',mode))
 return result

def kill_group(proc):
 try: os.killpg(proc.pid,signal.SIGTERM)
 except ProcessLookupError: pass
 try: proc.wait(timeout=2); return
 except subprocess.TimeoutExpired: pass
 try: os.killpg(proc.pid,signal.SIGKILL)
 except ProcessLookupError: pass
 proc.wait()

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--config',type=pathlib.Path,required=True); ap.add_argument('--codex',required=True); ap.add_argument('--timeout',type=int,default=300); a=ap.parse_args()
 cfg=load_bounded_json(a.config); keys={'schema_version','review_id','state','review_dir','topic','repo','plugin_root'}
 if not isinstance(cfg,dict) or set(cfg)!=keys or cfg['schema_version']!=1 or a.config.read_bytes()!=canonical(cfg).encode(): return 2
 state=pathlib.Path(cfg['state']); review=pathlib.Path(cfg['review_dir']); rid=cfg['review_id']; topic=cfg['topic']; repo=pathlib.Path(cfg['repo']); gen=review/'generations'/'1'; snap=gen/'PLAN.md'; live=repo/'PLAN.md'; manifest=gen/'manifest.json'
 if state.stem!=rid or review.name!=rid or a.config!=review/'runner-config.json': return 2
 snapshot=sha(snap); load_manifest(manifest,rid,snapshot,topic,str(repo),str(live))
 state_obj=parse_state(state)
 if state_obj.get('snapshot_sha256')!=snapshot or state_obj.get('review_id')!=rid or state_obj.get('engine')!='review-v3': return 2
 if sha(live)!=snapshot: return 2
 schema=gen/'review-output.schema.json'
 if schema.exists(): return 2
 atomic(schema,canonical(SCHEMA)); raws=[]
 for persona in PERSONAS:
  raw=gen/f'{persona}.raw.json'; side=gen/f'{persona}.result.json'; prompt=gen/f'.{persona}.prompt.txt'; marker=state.parent/f'{rid}-active-pgid'
  if raw.exists() or side.exists() or marker.exists(): return 2
  atomic(prompt,f"Persona ID: {persona}\nReview focus: {FOCUS[persona]}.\nReview only frozen snapshot: {snap}\nSnapshot SHA-256: {snapshot}\nTopic: {topic}\nReturn only the schema-conforming JSON final response. Never assign finding IDs.\n")
  baseline_repo=repo_snapshot(repo,state.parent); excluded={raw,side,prompt}; baseline_evidence=evidence_snapshot(review,excluded); baseline_state=sha(state); rc=125; error=None; proc=None
  try:
   lock=state.with_name(state.name+'.write-lock')
   with lock.open('a+') as held, prompt.open('rb') as inp:
    fcntl.flock(held,fcntl.LOCK_EX)
    if parse_state(state).get('phase')!='reviewing': raise ValueError('review cancelled before spawn')
    proc=subprocess.Popen([a.codex,'exec','--sandbox','read-only','--ephemeral','--ignore-rules','--output-schema',str(schema),'--output-last-message',str(raw),'-'],stdin=inp,cwd=repo,start_new_session=True)
    hook=os.environ.get('CLAUDEX_REVIEW_V3_SPAWN_HOOK')
    if hook: pathlib.Path(hook+'.ready').write_text(str(proc.pid)); pathlib.Path(hook+'.release').read_text()
    atomic(marker,str(proc.pid)+"\n")
    if parse_state(state).get('phase')!='reviewing': kill_group(proc); raise ValueError('review cancelled during spawn')
   try: rc=proc.wait(timeout=a.timeout)
   except subprocess.TimeoutExpired: kill_group(proc); rc=124
   finally:
    try:
     if marker.read_text().strip()==str(proc.pid): marker.unlink()
    except OSError: pass
   if rc!=0: raise ValueError(f"codex exited {rc}")
   if repo_snapshot(repo,state.parent)!=baseline_repo: raise ValueError('repository byte/mode/symlink mutation detected')
   if sha(state)!=baseline_state: raise ValueError('state mutation detected')
   if evidence_snapshot(review,excluded)!=baseline_evidence: raise ValueError('protected evidence mutation detected')
   obj=json.loads(raw.read_bytes().decode()); atomic(raw,canonical(obj)); obj=load_raw(raw,persona,snapshot); raws.append(obj)
  except Exception as exc: error=str(exc)
  finally: prompt.unlink(missing_ok=True)
  side_obj={"schema_version":1,"generation":1,"persona_id":persona,"snapshot_sha256":snapshot,"raw_sha256":sha(raw) if raw.is_file() else None,"codex_exit_code":rc,"valid":error is None,"error":error,"completed_at":dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')}; atomic(side,canonical(side_obj))
  if error:
   state_update(state,"reviewing",{"decision_signal":"degraded","clean":"false","coverage_complete":"false","revision_required":"false","phase":"summarizing"}); return 2
 reg=registry(rid,snapshot,topic,str(repo),str(live),raws); registry_path=gen/'findings-registry.json'; consolidated=gen/'consolidated-findings.md'; atomic(registry_path,canonical(reg)); atomic(consolidated,render(reg)); material=bool(reg['findings'])
 updates={"coverage_complete":"true","clean":str(not material).lower(),"decision_signal":"findings-returned" if material else "converged","registry_sha256":sha(registry_path),"consolidated_sha256":sha(consolidated),"reviewed_live_sha256":sha(live),"revision_required":"false","phase":"summarizing"}
 if not state_update(state,"reviewing",updates): return 2
 return 10 if material else 0
if __name__=='__main__': sys.exit(main())
