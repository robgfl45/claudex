#!/usr/bin/env python3
"""Executable offline benchmark derived only from transcript/artifact fixtures."""
import hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).with_name('fixtures')/'closure-benchmarks'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def events(path):
 rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
 return rows
def measure(d):
 old=events(d/'old-events.jsonl'); new=events(d/'new-events.jsonl'); pre=events(d/'preflight-events.jsonl')
 launches=lambda xs:sum(x.get('event')=='provider_launch' for x in xs)
 elapsed=lambda xs:(max(x['at_ms'] for x in xs)-min(x['at_ms'] for x in xs)) if xs else 0
 before=(d/'plan-before.md').read_bytes(); after=(d/'plan-after.md').read_bytes(); reviewed=(d/'reviewed-plan.md').read_bytes()
 reg=json.loads((d/'registry.json').read_text()); result=json.loads((d/'result.json').read_text()); ids=[x['finding_id'] for x in reg['findings']]
 duplicate=len(ids)-len(set(ids)); stable=ids==[f'CX-{i:04d}' for i in range(1,len(ids)+1)]
 verdicts=[x['verdict'] for x in result['verifications']]; recomputed='closure_requires_new_review' if 'closure_requires_new_review' in verdicts else ('blocked' if 'not_closed' in verdicts else 'accepted_after_targeted_closure')
 evidence=all(isinstance(x.get('evidence'),list) and x['evidence'] and all(isinstance(y,str) and y for y in x['evidence']) for x in result['verifications'])
 old_calls=launches(old); new_calls=launches(new); ratio=new_calls/old_calls if old_calls else 999
 item={'name':d.name,'old_provider_calls':old_calls,'new_provider_calls':new_calls,'provider_call_ratio':round(ratio,4),'old_elapsed_ms':elapsed(old),'new_elapsed_ms':elapsed(new),'broad_review_plan_mutation_bytes':0 if reviewed==before else abs(len(reviewed)-len(before)) or 1,'final_plan_byte_growth':len(after)-len(before),'stable_ids':stable,'duplicate_ids':duplicate,'honest_outcome':result.get('outcome')==recomputed,'evidence_valid':evidence,'preflight_failure_provider_calls':launches(pre)}
 item['passed']=ratio<=.5 and item['broad_review_plan_mutation_bytes']==0 and stable and duplicate==0 and item['honest_outcome'] and evidence and item['preflight_failure_provider_calls']==0
 return item
def run(root=ROOT):
 out=[measure(x) for x in sorted(root.iterdir()) if x.is_dir()]; return {'schema_version':1,'fixtures':out,'release_threshold':'new provider launches <= 50% of old launches','passed':bool(out) and all(x['passed'] for x in out),'failed_fixtures':[x['name'] for x in out if not x['passed']]}
if __name__=='__main__':
 summary=run(); print(json.dumps(summary,sort_keys=True,separators=(',',':'))); sys.exit(0 if summary['passed'] else 1)
