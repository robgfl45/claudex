#!/usr/bin/env python3
"""Deterministic adversarial unit matrix for the review-v3 shared contract."""
import copy, hashlib, importlib.util, json, pathlib, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]/'scripts'; spec=importlib.util.spec_from_file_location('c',ROOT/'review_v3_contract.py'); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
sha='a'*64
clean={'persona_id':c.PERSONAS[0],'snapshot_sha256':sha,'classification':'clean','findings':[]}
finding={'severity':'high','scope_anchor':'a','underlying_risk':'r','failure_scenario':'f','repository_evidence':['e'],'proposed_remedy':'p'}
CASES=[]
def case(name,fn): CASES.append((name,fn))
def rejects(mut):
 def f():
  try: c.validate_raw(mut,c.PERSONAS[0],sha)
  except Exception: return
  raise AssertionError('accepted invalid raw')
 return f
case('clean raw canonical parity',lambda: c.validate_raw(copy.deepcopy(clean),c.PERSONAS[0],sha))
for name,mut in [
 ('malformed JSON shape',[]),('extra raw key',{**clean,'x':1}),('empty persona field',{**clean,'persona_id':''}),('persona mismatch',{**clean,'persona_id':c.PERSONAS[1]}),('snapshot mismatch',{**clean,'snapshot_sha256':'b'*64}),('classification findings mismatch',{**clean,'classification':'material'}),('model finding ID rejection',{**clean,'classification':'material','findings':[{**finding,'finding_id':'CX-9'}]}),('empty finding field',{**clean,'classification':'material','findings':[{**finding,'scope_anchor':''}]}),('empty repository evidence',{**clean,'classification':'material','findings':[{**finding,'repository_evidence':[]}]}),('invalid severity',{**clean,'classification':'material','findings':[{**finding,'severity':'critical'}]})]: case(name,rejects(mut))
def filecase(name,data,accept=False):
 def f():
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'x'; p.write_bytes(data)
   try: c.load_raw(p,c.PERSONAS[0],sha)
   except Exception:
    if accept: raise
    return
   if not accept: raise AssertionError('accepted invalid bytes')
 case(name,f)
filecase('missing raw',b'',False); filecase('oversized raw bytes',b' '*((2*1024*1024)+1),False); filecase('deep raw JSON',('['*40+'0'+']'*40).encode(),False); filecase('noncanonical raw bytes',json.dumps(clean).encode(),False); filecase('canonical raw bytes',c.canonical(clean).encode(),True)
def registry_order():
 raws=[]
 for p in c.PERSONAS:
  r={'persona_id':p,'snapshot_sha256':sha,'classification':'material','findings':[finding]}; raws.append(r)
 reg=c.registry('20260101-000000-abcdef',sha,'réview 🔒','/r','/r/PLAN.md',raws)
 assert [x['finding_id'] for x in reg['findings']]==[f'CX-{i:04d}' for i in range(1,6)] and [x['persona_id'] for x in reg['findings']]==c.PERSONAS
case('deterministic multi-persona IDs and order',registry_order)
def regtamper():
 expected=c.registry('20260101-000000-abcdef',sha,'t','/r','/r/P',[]); bad=copy.deepcopy(expected); bad['topic']='x'
 try:c.validate_registry(bad,expected)
 except Exception:return
 raise AssertionError
case('registry tamper rejection',regtamper)
def unicode_manifest():
 obj={'schema_version':1,'review_id':'20260101-000000-abcdef','engine':'review-v3','generation':1,'snapshot_sha256':sha,'required_persona_ids':c.PERSONAS,'topic':'réview 🔒','repo_root':'/r','source_plan_path':'/r/PLAN.md'}
 with tempfile.TemporaryDirectory() as d:
  p=pathlib.Path(d)/'m'; p.write_bytes(c.canonical(obj).encode()); assert c.load_manifest(p,obj['review_id'],sha,obj['topic'],'/r','/r/PLAN.md')==obj; assert b'\xf0\x9f' in p.read_bytes()
case('non-ASCII canonical manifest',unicode_manifest)
def manifest_tamper():
 obj={'schema_version':1,'review_id':'20260101-000000-abcdef','engine':'review-v3','generation':1,'snapshot_sha256':sha,'required_persona_ids':c.PERSONAS,'topic':'t','repo_root':'/r','source_plan_path':'/r/P'}; obj['generation']=2
 try:c.validate_manifest(obj,obj['review_id'],sha,'t','/r','/r/P')
 except Exception:return
 raise AssertionError
case('manifest identity tamper rejection',manifest_tamper)
def rendering():
 reg=c.registry('20260101-000000-abcdef',sha,'t','/r','/r/P',[{**clean,'classification':'material','findings':[finding]}]); assert c.render(reg).count('CX-0001')==1 and c.render(reg).endswith('\n')
case('registry render parity',rendering)
def sidecar_tamper():
 obj={'schema_version':1,'generation':1,'persona_id':c.PERSONAS[0],'snapshot_sha256':sha,'raw_sha256':sha,'codex_exit_code':0,'valid':True,'error':None,'completed_at':'2026-01-01T00:00:00Z'}; c.validate_sidecar(obj,c.PERSONAS[0],sha,sha); obj['valid']=False
 try:c.validate_sidecar(obj,c.PERSONAS[0],sha,sha)
 except Exception:return
 raise AssertionError
case('sidecar value tamper rejection',sidecar_tamper)
failed=0
for i,(name,fn) in enumerate(CASES,1):
 try: fn(); print(f'ok {i} - {name}')
 except Exception as e: failed+=1; print(f'not ok {i} - {name}: {e}')
print(f'CONTRACT PASS: {len(CASES)-failed} FAIL: {failed}')
raise SystemExit(bool(failed))
