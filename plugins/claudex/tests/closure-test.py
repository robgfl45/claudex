#!/usr/bin/env python3
"""Deterministic offline targeted-closure contract and lifecycle tests."""
import copy, hashlib, importlib.util, json, os, pathlib, shutil, signal, subprocess, tempfile, time, unittest
ROOT=pathlib.Path(__file__).resolve().parents[3]; CLI=ROOT/'bin/claudex-plan-closure'; SCRIPTS=ROOT/'plugins/claudex/scripts'
spec=importlib.util.spec_from_file_location('cc',SCRIPTS/'closure_contract.py'); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
FINDING=lambda fid='CX-0001',sev='high':{'finding_id':fid,'persona_id':'security-data','severity':sev,'scope_anchor':'Safety','underlying_risk':'race loses data','failure_scenario':'concurrent writers overwrite','repository_evidence':['src/store.py'],'proposed_remedy':'serialize writes'}
def canon(x): return json.dumps(x,indent=2,sort_keys=True,ensure_ascii=False)+'\n'
class Closure(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.d=pathlib.Path(self.t.name); self.repo=self.d/'repo'; self.repo.mkdir(); subprocess.run(['git','init','-q'],cwd=self.repo,check=True); (self.repo/'tracked').write_text('safe\n'); subprocess.run(['git','add','tracked'],cwd=self.repo,check=True)
  self.orig=self.d/'original.md'; self.final=self.d/'final.md'; self.orig.write_text('# Plan\nunsafe\n'); (self.repo/'PLAN.md').write_bytes(self.orig.read_bytes()); self.final.write_text('# Plan\nsafe serialization\n')
  self.reg=self.d/'registry.json'; self.man=self.d/'manifest.json'; self.codex=self.d/'codex'; self.log=self.d/'calls'
  self.findings=[FINDING()]; self.write_registry(); self.mode='closed'; self.write_codex()
 def tearDown(self): self.t.cleanup()
 def write_registry(self):
  reg={'schema_version':1,'generation':1,'review_id':'20260101-000000-abcdef','engine':'review-v3','snapshot_sha256':hashlib.sha256(self.orig.read_bytes()).hexdigest(),'topic':'migration safety','repo_root':str(self.repo.resolve()),'source_plan_path':str((self.repo/'PLAN.md').resolve()),'persona_order':['architecture-scope','security-data','product-domain','quality-accessibility-performance','operations-deployment'],'findings':self.findings}; self.reg.write_text(canon(reg)); return reg
 def row(self,fid='CX-0001',disp='accept-and-correct',sections=None,approval=None,just=None): return {'finding_id':fid,'disposition':disp,'rationale':'bounded disposition rationale','changed_sections':['Safety'] if sections is None and disp=='accept-and-correct' else (sections or []),'approval_reference':approval,'non_plan_blocking_justification':just}
 def write_manifest(self,rows=None,attempt=1,prior=None,prior_terminal=None):
  reg=json.loads(self.reg.read_text()); man={'schema_version':1,'review_id':reg['review_id'],'engine':'review-v3','repo_root':str(self.repo.resolve()),'topic':reg['topic'],'original_snapshot_sha256':hashlib.sha256(self.orig.read_bytes()).hexdigest(),'final_plan_sha256':hashlib.sha256(self.final.read_bytes()).hexdigest(),'registry_sha256':hashlib.sha256(self.reg.read_bytes()).hexdigest(),'attempt':attempt,'prior_result_sha256':prior,'prior_terminal_manifest_sha256':prior_terminal,'dispositions':rows if rows is not None else [self.row()]}; self.man.write_text(canon(man)); return man
 def write_codex(self):
  self.codex.write_text('''#!/usr/bin/env python3
import json,os,pathlib,signal,subprocess,sys,time
args=sys.argv; raw=pathlib.Path(args[args.index('--output-last-message')+1]); prompt=sys.stdin.read(); fid=prompt.split('"finding_id": "')[1].split('"')[0]; mode=os.environ.get('MODE','closed'); log=os.environ.get('CALL_LOG');
if log: pathlib.Path(log).open('a').write(fid+'\\n')
if mode=='nonzero': sys.exit(7)
if mode=='timeout':
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(os.environ['PID_LOG']).write_text(str(os.getpid())+' '+str(child.pid)); time.sleep(60)
if mode=='mutate':
 target=pathlib.Path(os.environ['MUTATE']); kind=os.environ.get('MUTATION_KIND','write')
 if kind=='mode': target.chmod(target.stat().st_mode ^ 0o100)
 elif kind=='mkdir': target.mkdir()
 elif kind=='rmdir': target.rmdir()
 elif kind=='dirmode': target.chmod(target.stat().st_mode ^ 0o100)
 elif kind=='symlink': target.unlink(); target.symlink_to('other-target')
 else: target.write_text(target.read_text()+'changed')
verdict={'closed':'closed','not_closed':'not_closed','architecture':'closure_requires_new_review','id_mismatch':'closed','empty_evidence':'closed'}.get(mode,'closed'); out={'finding_id':'CX-9999' if mode=='id_mismatch' else fid,'verdict':verdict,'evidence':[] if mode=='empty_evidence' else ['final plan Safety section'],'reason':'exact risk assessment'}
if mode=='extra_key': out['unexpected']=True
if mode=='malformed': raw.write_text('{')
elif mode=='oversized': raw.write_bytes(b' '*((2*1024*1024)+1))
elif mode=='noncanonical': raw.write_text('{ "reason" : "exact risk assessment", "evidence" : [ "final plan Safety section" ], "verdict" : "closed", "finding_id" : "'+fid+'" }')
else: raw.write_text(json.dumps(out,indent=2,sort_keys=True)+'\\n')
'''); self.codex.chmod(0o755)
 def run_cli(self,rows=None,mode=None,attempt=1,prior_path=None,extra=None,timeout=5,rewrite=True):
  prior_dir=prior_path.parent if prior_path else None; terminal_sha=hashlib.sha256((prior_dir/'terminal-manifest.json').read_bytes()).hexdigest() if prior_dir else None; prior_sha=hashlib.sha256(prior_path.read_bytes()).hexdigest() if prior_path else None
  if rewrite: self.write_manifest(rows,attempt,prior_sha,terminal_sha)
  out=self.d/f'out-{time.time_ns()}'; env=os.environ.copy(); env.update(MODE=mode or self.mode,CALL_LOG=str(self.log),MUTATE=str(self.repo/'tracked'),PID_LOG=str(self.d/'pids')); env.update(extra or {})
  cmd=[str(CLI),'--repo',str(self.repo.resolve()),'--original-plan',str(self.orig.resolve()),'--final-plan',str(self.final.resolve()),'--registry',str(self.reg.resolve()),'--manifest',str(self.man.resolve()),'--codex',str(self.codex.resolve()),'--output-dir',str(out),'--timeout',str(timeout)]
  if prior_path: cmd += ['--prior-evidence-dir',str(prior_dir.resolve()),'--prior-terminal-manifest-sha256',terminal_sha]
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
 def test_extra_key(self): self.assertOutcome('degraded',mode='extra_key')
 def test_noncanonical_provider_output_is_normalized_and_verified(self):
  p,r,o=self.assertOutcome('accepted_after_targeted_closure',mode='noncanonical'); raw=o/'verifiers/CX-0001.raw.json'
  self.assertEqual(raw.read_bytes(),canon(json.loads(raw.read_bytes())).encode('utf-8')); self.assertTrue(raw.read_bytes().endswith(b'\n'))
  verified,obj=self.verify(o,r['terminal_manifest_sha256']); self.assertEqual(verified.returncode,0); self.assertTrue(obj['verified'])
 def test_nonzero(self): self.assertOutcome('degraded',mode='nonzero')
 def test_timeout_and_descendant_cleanup(self):
  p,r,o=self.assertOutcome('timed_out',mode='timeout',timeout=.2); self.assertEqual(p.returncode,124); pids=[int(x) for x in (self.d/'pids').read_text().split()]
  for pid in pids:
   for _ in range(40):
    try: os.kill(pid,0); time.sleep(.025)
    except ProcessLookupError: break
   else: self.fail(f'process {pid} survived cancellation')
 def test_repo_mutation(self): self.assertOutcome('degraded',mode='mutate')
 def test_complete_repo_mutation_classes(self):
  (self.repo/'.gitignore').write_text('ignored\n'); subprocess.run(['git','add','.gitignore'],cwd=self.repo,check=True)
  cases=[]
  dirty=self.repo/'dirty'; dirty.write_text('already dirty\n'); subprocess.run(['git','add','dirty'],cwd=self.repo,check=True); dirty.write_text('dirty baseline\n'); cases.append((dirty,'write'))
  untracked=self.repo/'untracked'; untracked.write_text('u\n'); cases.append((untracked,'write'))
  ignored=self.repo/'ignored'; ignored.write_text('i\n'); cases.append((ignored,'write'))
  mode=self.repo/'mode'; mode.write_text('m\n'); cases.append((mode,'mode'))
  link=self.repo/'link'; link.symlink_to('tracked'); cases.append((link,'symlink'))
  cases.append((self.repo/'.git/config','write'))
  for target,kind in cases:
   with self.subTest(target=target.name,kind=kind): self.assertOutcome('degraded',mode='mutate',extra={'MUTATE':str(target),'MUTATION_KIND':kind})
 def test_empty_directory_create_delete_and_directory_mode_mutations(self):
  created=self.repo/'created-empty'
  deleted=self.repo/'deleted-empty'; deleted.mkdir()
  mode_dir=self.repo/'mode-dir'; mode_dir.mkdir()
  for target,kind in ((created,'mkdir'),(deleted,'rmdir'),(mode_dir,'dirmode')):
   with self.subTest(kind=kind):
    self.assertOutcome('degraded',mode='mutate',extra={'MUTATE':str(target),'MUTATION_KIND':kind})
    if kind=='mkdir': target.rmdir()
    elif kind=='rmdir': target.mkdir()
    else: target.chmod(target.stat().st_mode ^ 0o100)
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
 def test_final_hash_manifest_mismatch(self): self.write_manifest(); self.final.write_text('mutated before launch'); p,r,o,lines=self.run_cli(rewrite=False); self.assertEqual(r['outcome'],'degraded')
 def test_noncanonical_manifest(self):
  self.write_manifest(); self.man.write_text(json.dumps(json.loads(self.man.read_text()))); out=self.d/'badout'; p=subprocess.run([str(CLI),'--repo',str(self.repo.resolve()),'--original-plan',str(self.orig.resolve()),'--final-plan',str(self.final.resolve()),'--registry',str(self.reg.resolve()),'--manifest',str(self.man.resolve()),'--codex',str(self.codex.resolve()),'--output-dir',str(out)],text=True,capture_output=True); self.assertEqual(json.loads(p.stdout)['outcome'],'degraded')
 def test_prompt_is_narrow_and_forbids_generic_review(self):
  _,_,o=self.assertOutcome('accepted_after_targeted_closure'); text=(o/'verifiers/CX-0001.prompt.txt').read_text(); self.assertIn('Do not perform generic review',text); self.assertIn('Do not',text); self.assertNotIn('find anything else',text.lower())
 def verify(self,o,anchor):
  p=subprocess.run([str(CLI),'--verify-evidence',str(o),'--expected-terminal-sha256',anchor],text=True,capture_output=True); return p,json.loads(p.stdout)
 def test_terminal_evidence_verifier_and_mutations(self):
  _,r,o=self.assertOutcome('accepted_after_targeted_closure'); anchor=r['terminal_manifest_sha256']; p,v=self.verify(o,anchor); self.assertEqual(p.returncode,0); self.assertTrue(v['verified'])
  targets=['result.json','verifiers/CX-0001.raw.json','artifacts/registry.json','terminal-manifest.json']
  for target in targets:
   q=self.d/('tamper-'+target.replace('/','-')); shutil.copytree(o,q); (q/target).write_bytes((q/target).read_bytes()+b' '); self.assertNotEqual(self.verify(q,anchor)[0].returncode,0)
  q=self.d/'double-tamper'; shutil.copytree(o,q); (q/'artifacts/registry.json').write_text('{}\n'); tm=json.loads((q/'terminal-manifest.json').read_text()); row=next(x for x in tm['files'] if x['path']=='artifacts/registry.json'); row['bytes']=(q/'artifacts/registry.json').stat().st_size; row['sha256']=hashlib.sha256((q/'artifacts/registry.json').read_bytes()).hexdigest(); (q/'terminal-manifest.json').write_text(canon(tm)); self.assertNotEqual(self.verify(q,anchor)[0].returncode,0)
 def test_empty_verifier_evidence_rejected(self): self.assertOutcome('degraded',mode='empty_evidence')
 def test_fault_injection_exactly_one_json(self):
  for key in ('CLAUDEX_CLOSURE_FAIL_COPY','CLAUDEX_CLOSURE_FAIL_EVENT','CLAUDEX_CLOSURE_FAIL_RESULT','CLAUDEX_CLOSURE_FAIL_TERMINAL'):
   p,r,o,lines=self.run_cli(extra={key:'1'}); self.assertEqual(r['outcome'],'degraded'); self.assertEqual(len(lines),1); self.assertNotIn('Traceback',p.stderr)
 def test_exec_format_failure_exactly_one_json(self):
  self.codex.write_bytes(b'not executable format'); self.codex.chmod(0o755); p,r,o,lines=self.run_cli(); self.assertEqual(r['outcome'],'degraded'); self.assertEqual(len(lines),1); self.assertNotIn('Traceback',p.stderr)
 def test_canonical_source_cross_path_rejected(self):
  other=self.repo/'OTHER.md'; other.write_bytes(self.orig.read_bytes()); reg=json.loads(self.reg.read_text()); reg['source_plan_path']=str(other.resolve()); self.reg.write_text(canon(reg)); self.assertOutcome('degraded')
 def test_forged_prior_result_and_unanchored_manifest_rejected(self):
  _,r,o=self.assertOutcome('blocked',mode='not_closed'); q=self.d/'forged'; shutil.copytree(o,q); x=json.loads((q/'result.json').read_text()); x['review_id']='foreign'; (q/'result.json').write_text(canon(x)); tm=json.loads((q/'terminal-manifest.json').read_text()); row=next(z for z in tm['files'] if z['path']=='result.json'); row['bytes']=(q/'result.json').stat().st_size; row['sha256']=hashlib.sha256((q/'result.json').read_bytes()).hexdigest(); tm['result_sha256']=row['sha256']; (q/'terminal-manifest.json').write_text(canon(tm)); self.assertNotEqual(self.verify(q,r['terminal_manifest_sha256'])[0].returncode,0)
 def test_attempt2_ingestion_rejects_self_consistent_forged_prior_before_verifier(self):
  _,_,o=self.assertOutcome('blocked',mode='not_closed'); q=self.d/'forged-attempt2'; shutil.copytree(o,q)
  result=json.loads((q/'result.json').read_text()); result['review_id']='foreign'; (q/'result.json').write_text(canon(result))
  terminal=json.loads((q/'terminal-manifest.json').read_text()); terminal['review_id']='foreign'; row=next(z for z in terminal['files'] if z['path']=='result.json'); row['bytes']=(q/'result.json').stat().st_size; row['sha256']=hashlib.sha256((q/'result.json').read_bytes()).hexdigest(); terminal['result_sha256']=row['sha256']; (q/'terminal-manifest.json').write_text(canon(terminal))
  self.log.unlink(missing_ok=True)
  p,r,_,_=self.run_cli(rows=[self.row()],attempt=2,prior_path=q/'result.json')
  self.assertEqual(p.returncode,11); self.assertEqual(r['outcome'],'degraded'); self.assertIn('prior result review_id mismatch',r['error']); self.assertFalse(self.log.exists(),'attempt-2 ingestion launched a verifier')
if __name__=='__main__': unittest.main(verbosity=2)
