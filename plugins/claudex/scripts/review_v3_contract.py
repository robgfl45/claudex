#!/usr/bin/env python3
"""Strict review-v3 evidence contract shared by runner and adapter."""
from __future__ import annotations
import datetime as dt, hashlib, json, pathlib, re
PERSONAS=["architecture-scope","security-data","product-domain","quality-accessibility-performance","operations-deployment"]
SEVERITIES=("high","medium","low")
SHA_RE=re.compile(r"[0-9a-f]{64}")
RID_RE=re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}")
MAX_STRING=8000; MAX_EVIDENCE=50; MAX_FINDINGS=100; MAX_RAW_BYTES=1_000_000

def canonical(obj): return json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+"\n"
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _text(value,name,allow_empty=False):
 if not isinstance(value,str) or (not allow_empty and not value.strip()) or len(value)>MAX_STRING: raise ValueError(f"{name} invalid")
 return value
def validate_raw(raw,persona,snapshot):
 if not isinstance(raw,dict) or set(raw)!={"persona_id","snapshot_sha256","classification","findings"}: raise ValueError("raw keys mismatch")
 if raw["persona_id"]!=persona or raw["snapshot_sha256"]!=snapshot: raise ValueError("persona/hash binding mismatch")
 if raw["classification"] not in {"clean","material"} or not isinstance(raw["findings"],list): raise ValueError("classification/findings invalid")
 if len(raw["findings"])>MAX_FINDINGS or (raw["classification"]=="clean")!=(len(raw["findings"])==0): raise ValueError("classification/findings mismatch")
 keys={"severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"}
 for finding in raw["findings"]:
  if not isinstance(finding,dict) or set(finding)!=keys: raise ValueError("finding keys mismatch (model IDs forbidden)")
  if finding["severity"] not in SEVERITIES: raise ValueError("severity invalid")
  for key in keys-{"severity","repository_evidence"}: _text(finding[key],key)
  evidence=finding["repository_evidence"]
  if not isinstance(evidence,list) or not evidence or len(evidence)>MAX_EVIDENCE: raise ValueError("repository_evidence invalid")
  for item in evidence: _text(item,"repository_evidence item")
 return raw

def load_raw(path,persona,snapshot):
 if not path.is_file() or path.stat().st_size==0 or path.stat().st_size>MAX_RAW_BYTES: raise ValueError("raw missing, empty, or oversized")
 obj=json.loads(path.read_text(encoding="utf-8")); validate_raw(obj,persona,snapshot)
 if path.read_bytes()!=canonical(obj).encode(): raise ValueError("raw JSON is not canonical")
 return obj

def registry(review_id,snapshot,topic,repo_root,source_plan,raws):
 findings=[]
 for raw in raws:
  for finding in raw["findings"]: findings.append({"finding_id":f"CX-{len(findings)+1:04d}","persona_id":raw["persona_id"],**finding})
 return {"schema_version":1,"generation":1,"review_id":review_id,"engine":"review-v3","snapshot_sha256":snapshot,"topic":topic,"repo_root":repo_root,"source_plan_path":source_plan,"persona_order":PERSONAS,"findings":findings}

def validate_registry(obj,expected):
 if not isinstance(obj,dict) or set(obj)!=set(expected) or obj!=expected: raise ValueError("registry does not exactly match reconstructed raw projection")
 for finding in obj["findings"]:
  if not isinstance(finding,dict) or set(finding)!={"finding_id","persona_id","severity","scope_anchor","underlying_risk","failure_scenario","repository_evidence","proposed_remedy"}: raise ValueError("registry finding schema invalid")
 return obj

def render(reg):
 out=["# Consolidated review-v3 findings\n",f"Review ID: `{reg['review_id']}`  ",f"Snapshot SHA-256: `{reg['snapshot_sha256']}`\n"]
 if not reg["findings"]: out.append("No substantive findings.\n")
 for f in reg["findings"]:
  out += [f"## {f['finding_id']} — {f['severity']}\n",f"**Persona:** `{f['persona_id']}`\n",f"**Scope anchor:** {f['scope_anchor']}\n",f"**Underlying risk:** {f['underlying_risk']}\n",f"**Failure scenario:** {f['failure_scenario']}\n","**Repository evidence:**",*[f"- {x}" for x in f['repository_evidence']],"",f"**Proposed remedy (not accepted by implication):** {f['proposed_remedy']}\n"]
 return "\n".join(out).rstrip()+"\n"

def validate_manifest(obj,review_id,snapshot,topic,repo_root,source_plan):
 expected={"schema_version":1,"review_id":review_id,"engine":"review-v3","generation":1,"snapshot_sha256":snapshot,"required_persona_ids":PERSONAS,"topic":topic,"repo_root":repo_root,"source_plan_path":source_plan}
 if not isinstance(obj,dict) or obj!=expected: raise ValueError("manifest identity/schema mismatch")
 return obj

def validate_sidecar(obj,persona,snapshot,raw_digest,exit_code=0):
 keys={"schema_version","generation","persona_id","snapshot_sha256","raw_sha256","codex_exit_code","valid","error","completed_at"}
 if not isinstance(obj,dict) or set(obj)!=keys: raise ValueError("sidecar keys mismatch")
 expected={"schema_version":1,"generation":1,"persona_id":persona,"snapshot_sha256":snapshot,"raw_sha256":raw_digest,"codex_exit_code":exit_code,"valid":True,"error":None}
 if any(obj.get(k)!=v for k,v in expected.items()): raise ValueError("sidecar values mismatch")
 if not isinstance(obj["completed_at"],str): raise ValueError("completed_at invalid")
 dt.datetime.fromisoformat(obj["completed_at"].replace("Z","+00:00"))
 return obj
