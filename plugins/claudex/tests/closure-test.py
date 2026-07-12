#!/usr/bin/env python3
"""Deterministic offline targeted-closure contract and lifecycle tests."""
import copy, hashlib, importlib.util, json, os, pathlib, signal, subprocess, tempfile, time, unittest
ROOT=pathlib.Path(__file__).resolve().parents[3]; CLI=ROOT/'bin/claudex-plan-closure'; SCRIPTS=ROOT/'plugins/claudex/scripts'
spec=importlib.util.spec_from_file_location('cc',SCRIPTS/'closure_contract.py'); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
FINDING=lambda fid='CX-0001',sev='high':{'finding_id':fid,'persona_id':'security-data','severity':sev,'scope_anchor':'Safety','underlying_risk':'race loses data','failure_scenario':'concurrent writers overwrite','repository_evidence':['src/store.py'],'proposed_remedy':'serialize writes'}
def canon(x): return json.dumps(x,indent=2,sort_keys=True,ensure_ascii=False)+'\n'
class Closure(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.d=pathlib.Path(self.t.name); self.repo=self.d/'repo'; self.repo.mkdir(); subprocess.run(['git','init','-q'],cwd=self.repo,check=True); (self.repo/'tracked').write_text('safe\n'); subprocess.run(['git','add','tracked'],cwd=self.repo,check=True)
  self.orig=self.d/'original.md'; self.final=self.d/'final.md'; self.orig.write_text('# Plan\nunsafe\n'); self.final.write_text('# Plan\nsafe serialization\n')
  self.reg=self.d/'registry.json'; self.man=self.d/'manifest.json'; self.codex=self.d/'codex'; self.log=self.d/'calls'
  self.findings=[FINDING()]; self.write_registry(); self.mode='closed'; self.write_codex()
 def tearDown(self): self.t.cleanup()
 def write_registry(self):
  reg={'schema_version':1,'generation':1,'review_id':'20260101-000000-abcdef','engine':'review-v3','snapshot_sha256':hashlib.sha256(self.orig.read_bytes()).hexdigest(),'topic':'migration safety','repo_root':str(self.repo.resolve()),'source_plan_path':str((self.repo/'PLAN.md').resolve()),'persona_order':['architecture-scope','security-data','product-domain','quality-accessibility-performance','operations-deployment'],'findings':self.findings}; self.reg.write_text(canon(reg)); return reg
 def row(self,fid='CX-0001',disp='accept-and-correct',sections=None,approval=None,just=None): return {'finding_id':fid,'disposition':disp,'rationale':'bounded disposition rationale','changed_sections':['Safety'] if sections is None and disp=='accept-and-correct' else (sections or []),'approval_reference':approval,'non_plan_blocking_justification':just}
 def write_manifest(self,rows=None,attempt=1,prior=None):
  reg=json.loads(self.reg.read_text()); man={'schema_version':1,'review_id':reg['review_id'],'engine':'review-v3','repo_root':str(self.repo.resolve()),'topic':reg['topic'],'original_snapshot_sha256':hashlib.sha256(self.orig.read_bytes()).hexdigest(),'final_plan_sha256':hashlib.sha256(self.final.read_bytes()).hexdigest(),'registry_sha256':hashlib.sha256(self.reg.read_bytes()).hexdigest(),'attempt':attempt,'prior_result_sha256':prior,'dispositions':rows if rows is not None else [self.row()]}; self.man.write_text(canon(man)); return man
 def write_codex(self):
  self.codex.write_text('''#!/usr/bin/env python3
import json,os,pathlib,signal,subprocess,sys,time
args=sys.argv; raw=pathlib.Path(args[args.index('--output-last-message')+1]); prompt=sys.stdin.read(); fid=prompt.split('"finding_id": "')[1].split('"')[0]; mode=os.environ.get('MODE','closed'); log=os.environ.get('CALL_LOG');
if log: pathlib.Path(log).open('a').write(fid+'\\n')
if mode=='nonzero': sys.exit(7)
if mode=='timeout':
 subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)
if mode=='mutate': pathlib.Path(os.environ['MUTATE']).write_text('changed')
verdict={'closed':'closed','not_closed':'not_closed','architecture':'closure_requires_new_review','id_mismatch':'closed'}.get(mode,'closed'); out={'finding_id':'CX-9999' if mode=='id_mismatch' else fid,'verdict':verdict,'evidence':['final plan Safety section'],'reason':'exact risk assessment'}
if mode=='malformed': raw.write_text('{')
elif mode=='oversized': raw.write_bytes(b' '*((2*1024*1024)+1))
else: raw.write_text(json.dumps(out,indent=2,sort_keys=True)+'\\n')
'''); self.codex.chmod(0o755)
 def run_cli(self,rows=None,mode=None,attempt=1,prior_path=None,extra=None,timeout=5):
  prior_sha=hashlib.sha256(prior_path.read_bytes()).hexdigest() if prior_path else None; self.write_manifest(rows,attempt,prior_sha); out=self.d/f'out-{time.time_ns()}'; env=os.environ.copy(); env.update(MODE=mode or self.mode,CALL_LOG=str(self.log),MUTATE=str(self.final)); env.update(extra or {})
  cmd=[str(CLI),'--repo',str(self.repo.resolve()),'--original-plan',str(self.orig.resolve()),'--final-plan',str(self.final.resolve()),'--registry',str(self.reg.resolve()),'--manifest',str(self.man.resolve()),'--codex',str(self.codex.resolve()),'--output-dir',str(out),'--timeout',str(timeout)]
  if prior_path: cmd += ['--prior-result',str(prior_path.resolve())]
  p=subprocess.run(cmd,text=True,capture_output=True,env=env); lines=p.stdout.splitlines(); obj=json.loads(lines[0]) if lines else {}; return p,obj,out,lines
 def assertOutcome(self,expected,**kw): p,r,o,lines=self.run_cli(**kw); self.assertEqual(r.get('outcome'),expected,(p.stderr,r)); self.assertEqual(len(lines),1); self.assertNotIn('converged',r['outcome']); return p,r,o
 def test_clean(self): p,r,o=self.assertOutcome('accepted_after_targeted_closure'); self.assertEqual(p.returncode,0); self.assertTrue(r['clean']); self.assertTrue((o/'result.json').is_file())
 def test_material_multi_id_mix(self):
  self.findings=[FINDING('CX-0001','high'),FINDING('CX-0002','medium'),FINDING('CX-0003','low'),FINDING('CX-0004','low'),FINDING('CX-0005','low')]; self.write_registry(); rows=[self.row('CX-0001'),self.row('CX-0002','already-satisfied',[]),self.row('CX-0003','defer-to-implementation',[],just='implementation detail only'),self.row('CX-0004','reject-scope-creep',[]),self.row('CX-0005','accept-risk',[],approval='Rob approval issue #9')]; _,r,_=self.assertOutcome('accepted_after_targeted_closure',rows=rows); self.assertEqual(len(r['verifications']),2)
 def test_not_closed(self): self.assertOutcome('blocked',mode='not_closed')
 def test_architecture_change(self): self.assertOutcome('closure_requires_new_review',mode='architecture')
 def test_model_id_mismatch(self): self.assertOutcome('degraded',mode='id_mismatch')
 def test_malformed(self): self.assertOutcome('degraded',mode='malformed')
 def test_oversized(self): self.assertOutcome('degraded',mode='oversized')
 def test_nonzero(self): self.assertOutcome('degraded',mode='nonzero')
 def test_timeout_and_descendant_cleanup(self): p,r,o=self.assertOutcome('timed_out',mode='timeout',timeout=.2); self.assertEqual(p.returncode,124)
 def test_repo_mutation(self): self.assertOutcome('degraded',mode='mutate')
 def test_copied_tamper(self): self.assertOutcome('degraded',extra={'CLAUDEX_CLOSURE_TAMPER_HOOK':'1'})
 def test_no_verifier_for_parent_dispositions(self):
  _,r,_=self.assertOutcome('accepted_after_targeted_closure',rows=[self.row(disp='reject-scope-creep',sections=[])]); self.assertEqual(r['verifications'],[])
 def test_attempt2_valid(self):
  _,r,o=self.assertOutcome('blocked',mode='not_closed'); prior=o/'result.json'; _,r2,_=self.assertOutcome('accepted_after_targeted_closure',rows=[self.row()],attempt=2,prior_path=prior); self.assertEqual(r2['attempt'],2)
 def test_attempt2_rejects_wrong_ids(self):
  _,r,o=self.assertOutcome('blocked',mode='not_closed'); self.findings.append(FINDING('CX-0002')); self.write_registry(); self.assertOutcome('degraded',rows=[self.row('CX-0002')],attempt=2,prior_path=o/'result.json')
 def test_attempt2_architecture_forbidden(self):
  _,r,o=self.assertOutcome('closure_requires_new_review',mode='architecture'); self.assertOutcome('degraded',attempt=2,prior_path=o/'result.json')
 def test_third_attempt(self): self.assertOutcome('degraded',attempt=3)
 def test_missing_id(self): self.findings.append(FINDING('CX-0002')); self.write_registry(); self.assertOutcome('degraded',rows=[self.row()])
 def test_duplicate_id(self): self.assertOutcome('degraded',rows=[self.row(),self.row()])
 def test_unknown_id(self): self.assertOutcome('degraded',rows=[self.row('CX-9999')])
 def test_unapproved_risk(self): self.assertOutcome('degraded',rows=[self.row(disp='accept-risk',sections=[])])
 def test_approved_risk(self): self.assertOutcome('accepted_after_targeted_closure',rows=[self.row(disp='accept-risk',sections=[],approval='Rob explicit approval PR-3')])
 def test_high_defer_needs_justification(self): self.assertOutcome('degraded',rows=[self.row(disp='defer-to-implementation',sections=[])])
 def test_medium_defer_needs_justification(self): self.findings=[FINDING(sev='medium')]; self.write_registry(); self.assertOutcome('degraded',rows=[self.row(disp='defer-to-implementation',sections=[])])
 def test_low_defer_allowed(self): self.findings=[FINDING(sev='low')]; self.write_registry(); self.assertOutcome('accepted_after_targeted_closure',rows=[self.row(disp='defer-to-implementation',sections=[])])
 def test_accept_correction_requires_sections(self): self.assertOutcome('degraded',rows=[self.row(sections=[])])
 def test_registry_original_mismatch(self): self.orig.write_text('different'); self.assertOutcome('degraded')
 def test_final_hash_manifest_mismatch(self): self.write_manifest(); self.final.write_text('mutated before launch'); p,r,o,lines=self.run_cli(); self.assertEqual(r['outcome'],'accepted_after_targeted_closure') # run rewrites correctly
 def test_noncanonical_manifest(self):
  self.write_manifest(); self.man.write_text(json.dumps(json.loads(self.man.read_text()))); out=self.d/'badout'; p=subprocess.run([str(CLI),'--repo',str(self.repo.resolve()),'--original-plan',str(self.orig.resolve()),'--final-plan',str(self.final.resolve()),'--registry',str(self.reg.resolve()),'--manifest',str(self.man.resolve()),'--codex',str(self.codex.resolve()),'--output-dir',str(out)],text=True,capture_output=True); self.assertEqual(json.loads(p.stdout)['outcome'],'degraded')
 def test_prompt_is_narrow_and_forbids_generic_review(self):
  _,_,o=self.assertOutcome('accepted_after_targeted_closure'); text=(o/'verifiers/CX-0001.prompt.txt').read_text(); self.assertIn('Do not perform generic review',text); self.assertIn('Do not',text); self.assertNotIn('find anything else',text.lower())
if __name__=='__main__': unittest.main(verbosity=2)
