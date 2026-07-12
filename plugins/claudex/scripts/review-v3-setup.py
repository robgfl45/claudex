#!/usr/bin/env python3
"""Create canonical review-v3 evidence/config and a static, injection-safe runner."""
import argparse, hashlib, os, pathlib, tempfile
from review_v3_contract import PERSONAS, canonical

def atomic(path, data, mode=0o600):
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.tmp.',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--state-dir',type=pathlib.Path,required=True); p.add_argument('--plugin-root',type=pathlib.Path,required=True)
    p.add_argument('--review-id',required=True); p.add_argument('--topic',required=True); p.add_argument('--repo',type=pathlib.Path,required=True)
    a=p.parse_args(); a.state_dir=a.state_dir.resolve(); a.plugin_root=a.plugin_root.resolve(); a.repo=a.repo.resolve(); source=a.repo/'PLAN.md'; review=a.state_dir/a.review_id; gen=review/'generations'/'1'; gen.mkdir(parents=True,exist_ok=False)
    snapshot=gen/'PLAN.md'; atomic(snapshot,source.read_bytes()); digest=hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest={'schema_version':1,'review_id':a.review_id,'engine':'review-v3','generation':1,'snapshot_sha256':digest,'required_persona_ids':PERSONAS,'topic':a.topic,'repo_root':str(a.repo),'source_plan_path':str(source)}
    atomic(gen/'manifest.json',canonical(manifest).encode())
    config={'schema_version':1,'review_id':a.review_id,'state':str(a.state_dir/f'{a.review_id}.state'),'review_dir':str(review),'topic':a.topic,'repo':str(a.repo),'plugin_root':str(a.plugin_root)}
    atomic(review/'runner-config.json',canonical(config).encode())
    runner=a.state_dir/f'{a.review_id}-runner.sh'
    static=b'''#!/usr/bin/env bash\nset -eu\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)\nID=$(basename -- "$0" -runner.sh)\nCONFIG="$HERE/$ID/runner-config.json"\nSCRIPT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["plugin_root"]+"/scripts/review-v3.py")' "$CONFIG")\nexec python3 "$SCRIPT" --config "$CONFIG" --codex "${CLAUDEX_CODEX_BIN:-codex}" --timeout "${CLAUDEX_SWEEP_PERSONA_TIMEOUT_SECONDS:-300}"\n'''
    atomic(runner,static,0o700); print(digest)
if __name__=='__main__': main()
