#!/usr/bin/env python3
"""Strict contracts shared by Drake's targeted-closure runner and tests."""
from __future__ import annotations
import hashlib,json,pathlib,re,importlib.util
DISPOSITIONS={"accept-and-correct","already-satisfied","defer-to-implementation","reject-scope-creep","accept-risk"}
VERIFY_DISPOSITIONS={"accept-and-correct","already-satisfied"}; VERDICTS={"closed","not_closed","closure_requires_new_review"}
OUTCOMES={"accepted_after_targeted_closure","blocked","closure_requires_new_review","degraded","timed_out"}
SHA_RE=re.compile(r"[0-9a-f]{64}"); FINDING_RE=re.compile(r"CX-[0-9]{4}")
MAX_JSON_BYTES=2*1024*1024; MAX_DEPTH=32; MAX_STRING=8000; MAX_ITEMS=50; MAX_CHANGED_SECTIONS=20
_here=pathlib.Path(__file__).resolve(); _spec=importlib.util.spec_from_file_location("review_v3_contract",_here.with_name("review_v3_contract.py")); rv3=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rv3)
def canonical(obj): return json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+"\n"
def digest_bytes(data): return hashlib.sha256(data).hexdigest()
def sha(path): return digest_bytes(path.read_bytes())
def _text(value,name,empty=False):
 if not isinstance(value,str) or len(value)>MAX_STRING or (not empty and not value.strip()): raise ValueError(f"{name} invalid")
 return value
def load_json(path,ceiling=MAX_JSON_BYTES,require_canonical=True):
 if not path.is_file(): raise ValueError(f"missing JSON: {path}")
 data=path.read_bytes()
 if not data or len(data)>ceiling: raise ValueError("JSON empty or oversized")
 obj=json.loads(data.decode("utf-8"))
 def walk(v,d=0):
  if d>MAX_DEPTH: raise ValueError("JSON nesting exceeds depth bound")
  if isinstance(v,dict):
   for k,x in v.items(): walk(k,d+1); walk(x,d+1)
  elif isinstance(v,list):
   for x in v: walk(x,d+1)
 walk(obj)
 if require_canonical and data!=canonical(obj).encode(): raise ValueError("JSON is not strict canonical JSON")
 return obj
def validate_registry(reg,*,repo_root,original_sha):
 keys={"schema_version","generation","review_id","engine","snapshot_sha256","topic","repo_root","source_plan_path","persona_order","findings"}
 if not isinstance(reg,dict) or set(reg)!=keys or reg["schema_version"]!=1 or reg["generation"]!=1 or reg["engine"]!="review-v3": raise ValueError("registry schema/engine mismatch")
 source=str((pathlib.Path(repo_root)/"PLAN.md").resolve())
 if reg["repo_root"]!=repo_root or reg["source_plan_path"]!=source or reg["snapshot_sha256"]!=original_sha: raise ValueError("registry repository/source/original snapshot identity mismatch")
 if not pathlib.Path(source).is_file() or sha(pathlib.Path(source))!=original_sha: raise ValueError("canonical PLAN.md does not match original snapshot")
 _text(reg["review_id"],"review_id"); _text(reg["topic"],"topic")
 if reg["persona_order"]!=rv3.PERSONAS or not isinstance(reg["findings"],list) or len(reg["findings"])>rv3.MAX_FINDINGS: raise ValueError("registry persona order/findings invalid")
 ids=[]; expected_num=1; last_persona=-1
 for f in reg["findings"]:
  expected={"finding_id","persona_id","severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"}
  if not isinstance(f,dict) or set(f)!=expected or f["finding_id"]!=f"CX-{expected_num:04d}" or f["persona_id"] not in rv3.PERSONAS or f["severity"] not in rv3.SEVERITIES: raise ValueError("registry finding schema/order invalid")
  persona_index=rv3.PERSONAS.index(f["persona_id"])
  if persona_index<last_persona: raise ValueError("registry finding persona order invalid")
  last_persona=persona_index; expected_num+=1; ids.append(f["finding_id"])
  for k in {"scope_anchor","underlying_risk","failure_scenario","proposed_remedy"}: _text(f[k],k)
  ev=f["repository_evidence"]
  if not isinstance(ev,list) or not ev or len(ev)>rv3.MAX_EVIDENCE: raise ValueError("repository_evidence invalid")
  for x in ev: _text(x,"repository evidence")
 if len(ids)!=len(set(ids)): raise ValueError("registry contains duplicate finding IDs")
 return reg
def validate_manifest(man,reg,*,repo_root,original_sha,final_sha,registry_sha,prior_result_sha=None,prior_terminal_sha=None,recheck_ids=None):
 keys={"schema_version","review_id","engine","repo_root","topic","original_snapshot_sha256","final_plan_sha256","registry_sha256","attempt","prior_result_sha256","prior_terminal_manifest_sha256","dispositions"}
 if not isinstance(man,dict) or set(man)!=keys or man["schema_version"]!=1 or man["engine"]!="review-v3": raise ValueError("closure manifest schema/engine mismatch")
 expected={"review_id":reg["review_id"],"repo_root":repo_root,"topic":reg["topic"],"original_snapshot_sha256":original_sha,"final_plan_sha256":final_sha,"registry_sha256":registry_sha}
 for k,v in expected.items():
  if man[k]!=v: raise ValueError(f"closure manifest {k} identity mismatch")
 attempt=man["attempt"]
 if attempt not in {1,2}: raise ValueError("attempt must be 1 or 2; no third attempt")
 if attempt==1:
  if man["prior_result_sha256"] is not None or man["prior_terminal_manifest_sha256"] is not None or prior_result_sha is not None: raise ValueError("attempt 1 cannot bind prior evidence")
 else:
  if man["prior_result_sha256"]!=prior_result_sha or man["prior_terminal_manifest_sha256"]!=prior_terminal_sha or not SHA_RE.fullmatch(prior_terminal_sha or ""): raise ValueError("attempt 2 must bind exact prior evidence")
 rows=man["dispositions"]
 if not isinstance(rows,list) or len(rows)>500: raise ValueError("dispositions invalid")
 row_keys={"finding_id","disposition","rationale","changed_sections","approval_reference","non_plan_blocking_justification"}; byid={}; registry_byid={x["finding_id"]:x for x in reg["findings"]}
 for row in rows:
  if not isinstance(row,dict) or set(row)!=row_keys: raise ValueError("disposition row schema mismatch")
  fid=row["finding_id"]
  if fid in byid or fid not in registry_byid: raise ValueError("duplicate/unknown disposition finding ID")
  if row["disposition"] not in DISPOSITIONS: raise ValueError("invalid disposition")
  _text(row["rationale"],"rationale"); sections=row["changed_sections"]
  if not isinstance(sections,list) or len(sections)>MAX_CHANGED_SECTIONS: raise ValueError("changed_sections invalid")
  for section in sections: _text(section,"changed section")
  if row["disposition"]=="accept-and-correct" and not sections: raise ValueError("accept-and-correct requires changed_sections")
  if row["disposition"] not in VERIFY_DISPOSITIONS and sections: raise ValueError("parent-owned disposition changed_sections must be empty")
  for optional in ("approval_reference","non_plan_blocking_justification"):
   if row[optional] is not None: _text(row[optional],optional)
  if row["disposition"]=="accept-risk" and not row["approval_reference"]: raise ValueError("accept-risk requires explicit approval_reference")
  if row["disposition"]=="defer-to-implementation" and registry_byid[fid]["severity"] in {"high","medium"} and not row["non_plan_blocking_justification"]: raise ValueError("high/medium defer requires justification")
  byid[fid]=row
 expected_ids=set(registry_byid) if attempt==1 else set(recheck_ids or ())
 if attempt==2 and (not expected_ids or any(x["disposition"] not in VERIFY_DISPOSITIONS for x in byid.values())): raise ValueError("attempt 2 must narrowly recheck prior not_closed rows")
 if set(byid)!=expected_ids: raise ValueError("missing, extra, or invalid disposition finding IDs")
 return byid
def validate_verifier(obj,expected_id):
 if not isinstance(obj,dict) or set(obj)!={"finding_id","verdict","evidence","reason"} or obj.get("finding_id")!=expected_id or obj.get("verdict") not in VERDICTS: raise ValueError("verifier schema/ID/verdict mismatch")
 evidence=obj["evidence"]
 if not isinstance(evidence,list) or not evidence or len(evidence)>MAX_ITEMS: raise ValueError("verifier evidence must be non-empty")
 for item in evidence: _text(item,"verifier evidence")
 _text(obj["reason"],"verifier reason"); return obj
