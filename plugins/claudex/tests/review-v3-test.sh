#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; PASS=0
ok(){ PASS=$((PASS+1)); printf 'ok %s - %s\n' "$PASS" "$1"; }
new(){ D=$(mktemp -d); cd "$D"; git init -q; printf '# Plan\n' > PLAN.md; export CLAUDE_PLUGIN_ROOT="$ROOT" CLAUDEX_STATE_DIR=.claude/claudex; }
stub(){ cat > codex <<'EOF'
#!/usr/bin/env python3
import json,os,pathlib,sys
p=sys.stdin.read(); persona=p.split('Persona ID: ')[1].splitlines()[0]; out=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]); sha=p.split('Snapshot SHA-256: ')[1].splitlines()[0]
f=[]
if os.environ.get('MODE')=='material' and persona=='security-data': f=[{'severity':'high','scope_anchor':'§1','underlying_risk':'lost authorization boundary','failure_scenario':'an unauthorized write succeeds','repository_evidence':['PLAN.md lacks an authorization step'],'proposed_remedy':'add an explicit authorization gate'}]
r={'persona_id':persona,'snapshot_sha256':sha,'classification':'material' if f else 'clean','findings':f}
if os.environ.get('MODE')=='id': r={'persona_id':persona,'snapshot_sha256':sha,'classification':'material','findings':[{'finding_id':'CX-9999','severity':'high','scope_anchor':'§1','underlying_risk':'risk','failure_scenario':'failure','repository_evidence':['evidence'],'proposed_remedy':'remedy'}]}
out.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
EOF
chmod +x codex; export CLAUDEX_CODEX_BIN="$D/codex"; }
run(){ bash "$ROOT/scripts/start-loop.sh" plan --engine review-v3 --rounds 1 --from-draft test >/dev/null; ID=$(basename .claude/claudex/*.state .state); bash ".claude/claudex/$ID-runner.sh"; }
new; stub; run; test $? -eq 0; test "$(grep -h '"valid": true' .claude/claudex/$ID/generations/1/*.result.json | wc -l | tr -d ' ')" -eq 5; ok 'five clean personas share one frozen hash'
new; stub; MODE=material run || test $? -eq 10; R=.claude/claudex/$ID/generations/1/findings-registry.json; grep -q 'CX-0001' "$R"; grep -q 'underlying_risk' "$R"; ok 'runner assigns deterministic IDs and preserves structured risk/remedy'
new; stub; MODE=id run && exit 1 || true; test ! -e .claude/claudex/$ID/generations/1/findings-registry.json; ok 'model-provided IDs degrade without registry'
new; stub; bash "$ROOT/scripts/start-loop.sh" plan --engine review-v3 --rounds 2 x >/dev/null 2>&1 && exit 1 || true; test ! -e .claude/claudex; ok 'one-round gate rejects before state'
new; stub; EVIL='quotes `touch PWNED1` new
line $(touch PWNED2) $HOME'; bash "$ROOT/scripts/start-loop.sh" plan --engine review-v3 --rounds 1 --from-draft "$EVIL" >/dev/null; test ! -e PWNED1; test ! -e PWNED2; ID=$(basename .claude/claudex/*.state .state); python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["topic"]==sys.argv[2]' ".claude/claudex/$ID/runner-config.json" "$EVIL"; ! grep -Fq "$EVIL" ".claude/claudex/$ID-runner.sh"; ok 'shell-injection topic remains inert and exact in config'
new; stub; UTF='réview 🔒'; bash "$ROOT/scripts/start-loop.sh" plan --engine review-v3 --rounds 1 --from-draft "$UTF" >/dev/null; ID=$(basename .claude/claudex/*.state .state); python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m["topic"]==sys.argv[2] and sys.argv[2].encode() in open(sys.argv[1],"rb").read()' ".claude/claudex/$ID/generations/1/manifest.json" "$UTF"; ok 'non-ASCII topic survives canonical manifest bytes'
CONTRACT_OUTPUT=$(python3 "$ROOT/tests/review-v3-contract-test.py")
printf '%s\n' "$CONTRACT_OUTPUT"
CONTRACT_TOTAL=$(python3 -c 'import re,sys; print(int(re.search(r"CONTRACT PASS: ([0-9]+)",sys.argv[1]).group(1)))' "$CONTRACT_OUTPUT")
TOTAL=$((PASS + CONTRACT_TOTAL))
printf 'PASS: %s FAIL: 0\n' "$TOTAL"
