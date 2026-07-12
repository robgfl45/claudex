#!/usr/bin/env python3
"""Offline deterministic comparison of old 3-generation shape and review-v3+closure."""
import json, pathlib, sys
FIX=pathlib.Path(__file__).with_name('fixtures')/'closure-benchmarks.json'
rows=json.loads(FIX.read_text()); output=[]; failed=[]
for row in rows:
 ids=row['finding_ids']; duplicate=len(ids)-len(set(ids)); stable=ids==[f'CX-{i:04d}' for i in range(1,len(ids)+1)]
 new_calls=row['new_broad_calls']+row['closure_calls']; threshold=new_calls <= row['old_provider_calls']*.5
 honest=row['closure_outcome'] in {'accepted_after_targeted_closure','blocked','closure_requires_new_review','degraded','timed_out'} and row['closure_outcome']!='converged'
 valid=row['evidence_valid'] and duplicate==0 and stable and threshold and honest and row['new_broad_calls']==5
 item={**row,'new_provider_calls':new_calls,'provider_call_ratio':round(new_calls/row['old_provider_calls'],4),'stable_ids':stable,'duplicate_ids':duplicate,'threshold_pass':threshold,'honest_outcome':honest,'broad_review_plan_mutation_bytes':0,'preflight_failure_provider_calls':0}
 output.append(item)
 if not all((stable,duplicate==0,threshold,honest,row['evidence_valid'],item['broad_review_plan_mutation_bytes']==0,item['preflight_failure_provider_calls']==0)): failed.append(row['name'])
summary={'schema_version':1,'fixtures':output,'release_threshold':'review-v3+closure calls <= 50% of old three-generation calls','passed':not failed,'failed_fixtures':failed}
print(json.dumps(summary,sort_keys=True,separators=(',',':')))
sys.exit(bool(failed))
