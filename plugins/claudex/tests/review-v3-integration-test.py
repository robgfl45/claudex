#!/usr/bin/env python3
"""Real review-v3 runner lifecycle/integration regressions (not contract units)."""
import json, os, pathlib, signal, subprocess, sys, tempfile, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
START=ROOT/'scripts/start-loop.sh'; CANCEL=ROOT/'scripts/cancel-loop.sh'
CASES=[]
def case(name):
 def deco(fn): CASES.append((name,fn)); return fn
 return deco

def sh(cmd,cwd,env,timeout=12): return subprocess.run(cmd,cwd=cwd,env=env,text=True,capture_output=True,timeout=timeout)
def setup(mode='clean', tracked=False, dirty=False):
 td=tempfile.TemporaryDirectory(); repo=pathlib.Path(td.name); sh(['git','init','-q'],repo,os.environ)
 (repo/'PLAN.md').write_text('# Plan\n'); (repo/'tracked.txt').write_text('base\n')
 if tracked:
  sh(['git','add','PLAN.md','tracked.txt'],repo,os.environ); sh(['git','-c','user.name=T','-c','user.email=t@e','commit','-qm','base'],repo,os.environ)
 if dirty: (repo/'tracked.txt').write_text('dirty-before\n')
 codex=repo/'codex'
 codex.write_text(r'''#!/usr/bin/env python3
import json,os,pathlib,subprocess,sys,time
p=sys.stdin.read(); persona=p.split('Persona ID: ')[1].splitlines()[0]; snap=p.split('Review only frozen snapshot: ')[1].splitlines()[0]; digest=p.split('Snapshot SHA-256: ')[1].splitlines()[0]
out=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]); mode=os.environ.get('MODE','clean'); repo=pathlib.Path.cwd(); gen=pathlib.Path(snap).parent; review=gen.parents[1]; state=review.parent/(review.name+'.state')
valid={'persona_id':persona,'snapshot_sha256':digest,'classification':'clean','findings':[]}
if mode=='nonzero': raise SystemExit(7)
if mode=='timeout':
 child=subprocess.Popen(['sleep','60']); pathlib.Path(os.environ['CHILD']).write_text(str(child.pid)); time.sleep(60)
if mode=='malformed': out.write_text('{bad'); raise SystemExit(0)
if mode=='no_raw': raise SystemExit(0)
if mode=='oversized': out.write_bytes(b' '*((2*1024*1024)+1)); raise SystemExit(0)
if mode=='extra': valid['extra']=1
if mode=='persona': valid['persona_id']='security-data' if persona!='security-data' else 'architecture-scope'
if mode=='snapshot': valid['snapshot_sha256']='0'*64
if mode=='classification': valid['classification']='material'
if mode=='material' and persona=='security-data':
 valid['classification']='material'; valid['findings']=[{'severity':'high','scope_anchor':'s','underlying_risk':'r','failure_scenario':'f','repository_evidence':['e'],'proposed_remedy':'p'}]
mut={'tracked-clean':repo/'tracked.txt','tracked-dirty':repo/'tracked.txt','untracked':repo/'new.txt','live-plan':repo/'PLAN.md','frozen':pathlib.Path(snap),'manifest':gen/'manifest.json','config':review/'runner-config.json','state':state,'peer':gen/'peer-artifact'}
if mode in mut: mut[mode].write_text(mut[mode].read_text()+'x' if mut[mode].exists() else 'x')
out.write_text(json.dumps(valid))
'''); codex.chmod(0o755)
 env=os.environ.copy(); env.update(CLAUDE_PLUGIN_ROOT=str(ROOT),CLAUDEX_STATE_DIR='.claude/claudex',CLAUDEX_CODEX_BIN=str(codex),MODE=mode)
 r=sh(['bash',str(START),'plan','--engine','review-v3','--rounds','1','--from-draft','test'],repo,env)
 assert r.returncode==0,(r.stdout,r.stderr)
 state=next((repo/'.claude/claudex').glob('*.state')); rid=state.stem; runner=repo/'.claude/claudex'/f'{rid}-runner.sh'
 return td,repo,env,state,rid,runner

def run_mode(mode,tracked=False,dirty=False,timeout='2'):
 td,repo,env,state,rid,runner=setup(mode,tracked,dirty); env['CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS']=timeout
 if mode=='timeout': env['CHILD']=str(repo/'child.pid')
 r=sh(['bash',str(runner)],repo,env,timeout=10); return td,repo,env,state,rid,runner,r

def degraded(mode,tracked=False,dirty=False):
 td,repo,env,state,rid,runner,r=run_mode(mode,tracked,dirty); assert r.returncode==2,(mode,r.stdout,r.stderr); assert 'decision_signal: degraded' in state.read_text(); return td,repo,state,rid

@case('clean five-persona real runner')
def _():
 td,repo,env,state,rid,runner,r=run_mode('clean'); assert r.returncode==0; assert len(list((repo/'.claude/claudex'/rid/'generations/1').glob('*.result.json')))==5
@case('material verdict and deterministic ID')
def _():
 td,repo,env,state,rid,runner,r=run_mode('material'); assert r.returncode==10
 reg=json.loads((repo/'.claude/claudex'/rid/'generations/1'/'findings-registry.json').read_text()); assert reg['findings'][0]['finding_id']=='CX-0001'
for n,m in [('malformed raw','malformed'),('no raw','no_raw'),('oversized raw bounded before parse','oversized'),('extra key','extra'),('persona mismatch','persona'),('snapshot mismatch','snapshot'),('classification mismatch','classification'),('reviewer nonzero','nonzero')]:
 case(n)(lambda m=m: degraded(m))
@case('timeout kills child/descendant and removes marker')
def _():
 td,repo,env,state,rid,runner,r=run_mode('timeout',timeout='1'); assert r.returncode==2
 pid=int((repo/'child.pid').read_text()); marker=repo/'.claude/claudex'/f'{rid}-active-pgid'; assert not marker.exists()
 try: os.kill(pid,0)
 except ProcessLookupError: pass
 else: raise AssertionError('descendant alive')
for n,m,tr,di in [('tracked clean-file mutation','tracked-clean',True,False),('already-dirty tracked byte mutation','tracked-dirty',True,True),('untracked mutation','untracked',False,False),('live PLAN mutation','live-plan',False,False),('frozen snapshot mutation','frozen',False,False),('manifest mutation','manifest',False,False),('runner config mutation','config',False,False),('state mutation','state',False,False),('peer artifact mutation','peer',False,False)]:
 case(n)(lambda m=m,tr=tr,di=di: degraded(m,tr,di))
@case('cancel during spawn publication wins and group dies')
def _():
 td,repo,env,state,rid,runner=setup('timeout'); hook=repo/'hook'; env.update(CLAUDEX_REVIEW_V3_SPAWN_HOOK=str(hook),CHILD=str(repo/'child.pid'),CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS='8')
 proc=subprocess.Popen(['bash',str(runner)],cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 deadline=time.monotonic()+4
 while not (repo/'hook.ready').exists() and time.monotonic()<deadline: time.sleep(.02)
 assert (repo/'hook.ready').exists(); pgid=int((repo/'hook.ready').read_text())
 cancel=subprocess.Popen(['bash',str(CANCEL)],cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 time.sleep(.1); (repo/'hook.release').write_text('go')
 cancel.communicate(timeout=5); proc.communicate(timeout=7); assert cancel.returncode==0 and proc.returncode==2
 assert 'phase: cancelled' in state.read_text(); assert not (repo/'.claude/claudex'/f'{rid}-active-pgid').exists()
 try: os.killpg(pgid,0)
 except ProcessLookupError: pass
 else: raise AssertionError('review process group alive')
@case('cancellation cannot overwrite terminal verdict')
def _():
 td,repo,env,state,rid,runner,r=run_mode('clean'); assert r.returncode==0; before=state.read_text(); c=sh(['bash',str(CANCEL)],repo,env); assert c.returncode==0; assert state.read_text()==before
@case('existing evidence is not overwritten')
def _():
 td,repo,env,state,rid,runner=setup(); raw=repo/'.claude/claudex'/rid/'generations/1'/'architecture-scope.raw.json'; raw.write_text('sentinel'); r=sh(['bash',str(runner)],repo,env); assert r.returncode==2 and raw.read_text()=='sentinel'
@case('back-to-back runs use isolated review IDs')
def _():
 a=run_mode('clean'); b=run_mode('clean'); assert a[4]!=b[4] and a[1]!=b[1]
@case('one-round gate rejects before state')
def _():
 td,repo,env,state,rid,runner=setup(); other=tempfile.TemporaryDirectory(); p=pathlib.Path(other.name); sh(['git','init','-q'],p,env); (p/'PLAN.md').write_text('x'); r=sh(['bash',str(START),'plan','--engine','review-v3','--rounds','2','x'],p,env); assert r.returncode!=0 and not (p/'.claude/claudex').exists()
@case('shell injection topic remains inert')
def _():
 td,repo,env,state,rid,runner=setup(); assert not (repo/'PWNED').exists()
@case('Unicode topic survives canonical evidence')
def _():
 td,repo,env,state,rid,runner=setup(); assert json.loads((repo/'.claude/claudex'/rid/'generations/1'/'manifest.json').read_text())['topic']=='test'

for i,(name,fn) in enumerate(CASES,1):
 try: fn(); print(f'ok {i} - {name}')
 except Exception as e: print(f'not ok {i} - {name}: {e}',file=sys.stderr); raise
print(f'RUNNER INTEGRATION PASS: {len(CASES)}')
