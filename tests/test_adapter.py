#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "bin" / "claudex-plan-review"
PLUGIN = ROOT / "plugins" / "claudex"
PERSONAS = [
    "architecture-scope",
    "security-data",
    "product-domain",
    "quality-accessibility-performance",
    "operations-deployment",
]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.plan = self.repo / "PLAN.md"
        self.plan.write_text("# Plan\n\n1. Do the thing safely.\n")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.claude = self.bin / "claude"
        self.codex = self.bin / "codex"
        self._write_executable(self.codex, """#!/bin/sh
case "$1 $2" in
  "login status") echo 'Logged in using ChatGPT'; exit 0 ;;
esac
echo 'codex-cli 0.test'
""")
        self._write_executable(self.claude, r"""#!/usr/bin/env python3
import datetime, hashlib, json, os, pathlib, re, subprocess, sys, time, uuid
if sys.argv[1:] == ['--version']:
    print('2.test'); raise SystemExit(0)
if sys.argv[1:] == ['auth', 'status']:
    print(json.dumps({'loggedIn': True, 'authMethod': 'test'})); raise SystemExit(0)
outcome = os.environ.get('FAKE_CLAUDE_OUTCOME', 'sweep_clean')
prompt = sys.argv[-1]
marker = os.environ.get('FAKE_PROMPT_FILE')
if marker: pathlib.Path(marker).write_text(prompt)
if outcome == 'failed':
    print('forced failure', file=sys.stderr); raise SystemExit(7)
if outcome == 'timeout':
    child = subprocess.Popen(['sleep', '60'])
    marker = os.environ.get('FAKE_CHILD_PID_FILE')
    if marker: pathlib.Path(marker).write_text(str(child.pid))
    time.sleep(60); raise SystemExit(0)
state_dir = pathlib.Path.cwd() / '.claude' / 'claudex'
state_dir.mkdir(parents=True, exist_ok=True)
rid = '20990101-000000-' + uuid.uuid4().hex[:6]
review_dir = state_dir / rid
review_dir.mkdir()
state_path = state_dir / (rid + '.state')
if outcome.startswith('legacy_'):
    if outcome == 'legacy_max':
        signal, findings, round_value = 'max-reached', '# Round 1 findings\n\n## High\n- unsafe gap (fix it)\n', '1'
    elif outcome == 'legacy_degraded':
        signal, findings, round_value = 'no-material-findings', '# Round 1 findings\n\n## High\n- contradiction (fix it)\n', '1'
    else:
        signal, findings, round_value = 'no-material-findings', '# Round 1 findings\n\nNo substantive findings.\n', '1'
    (review_dir / 'findings-round-1.md').write_text(findings)
    state_path.write_text(f'''mode: plan\nphase: done\ntopic: test\nround: {round_value}\nmax_rounds: 1\nreview_id: {rid}\nrepo_root: {pathlib.Path.cwd().resolve()}\ndecision_signal: {signal}\n''')
else:
    personas = ['architecture-scope','security-data','product-domain','quality-accessibility-performance','operations-deployment']
    match = re.search(r'--rounds (\d+)', prompt)
    maximum = int(match.group(1)) if match else 5
    generation = 5 if outcome == 'sweep_max' else (2 if outcome == 'sweep_broken_chain' else 1)
    generation_dir = review_dir / 'generations' / str(generation)
    generation_dir.mkdir(parents=True)
    snapshot = generation_dir / 'PLAN.md'
    snapshot.write_bytes((pathlib.Path.cwd() / 'PLAN.md').read_bytes())
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    previous_hash = None
    if generation > 1:
        for previous_generation in range(1, generation):
            previous_dir = review_dir / 'generations' / str(previous_generation)
            previous_dir.mkdir(parents=True)
            previous_snapshot = previous_dir / 'PLAN.md'
            previous_snapshot.write_text(f'# Prior plan generation {previous_generation}\n')
            current_previous_hash = hashlib.sha256(previous_snapshot.read_bytes()).hexdigest()
            previous_manifest = {
                'generation': previous_generation,
                'snapshot_sha256': current_previous_hash,
                'required_persona_ids': personas,
                'topic': 'review the grounded plan',
                'source_plan_path': str(pathlib.Path.cwd().resolve() / 'PLAN.md'),
                'previous_generation_sha256': previous_hash,
            }
            (previous_dir / 'manifest.json').write_text(json.dumps(previous_manifest, indent=2, sort_keys=True) + '\n')
            previous_hash = current_previous_hash
    manifest_topic = 'different topic' if outcome == 'sweep_topic_mismatch' else 'review the grounded plan'
    manifest = {
        'generation': generation, 'snapshot_sha256': snapshot_hash,
        'required_persona_ids': personas, 'topic': manifest_topic,
        'source_plan_path': str(pathlib.Path.cwd().resolve() / 'PLAN.md'),
        'previous_generation_sha256': ('0' * 64 if outcome == 'sweep_broken_chain' else previous_hash),
    }
    (generation_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    if outcome == 'sweep_empty_manifest':
        (generation_dir / 'manifest.json').write_text('{}\n')
    elif outcome == 'sweep_missing_manifest':
        (generation_dir / 'manifest.json').unlink()
    elif outcome == 'sweep_wrong_type_manifest':
        (generation_dir / 'manifest.json').write_text('[]\n')
    elif outcome == 'sweep_malformed_manifest':
        (generation_dir / 'manifest.json').write_text('{not-json\n')
    elif outcome == 'sweep_schema_manifest':
        manifest['unexpected'] = True
        (generation_dir / 'manifest.json').write_text(json.dumps(manifest) + '\n')
    chunks = [f'# Consolidated findings — generation {generation}\n\n', f'Snapshot SHA-256: `{snapshot_hash}`\n\n']
    evidence = hashlib.sha256()
    for persona in personas:
        findings = generation_dir / f'{persona}.findings.md'
        sidecar = generation_dir / f'{persona}.result.json'
        material = outcome == 'sweep_max' and persona == 'security-data'
        if material:
            text = '## High\n- Scope: material generation-five gap (fix it).\n## Medium\n## Low\n'
            classification = 'material'
        else:
            text = 'No substantive findings.\n'
            classification = 'clean'
        if outcome == 'sweep_malformed' and persona == 'product-domain':
            text = 'not valid findings\n'
        findings.write_text(text)
        findings_hash = hashlib.sha256(findings.read_bytes()).hexdigest()
        expected = '0' * 64 if outcome == 'sweep_hash_mismatch' and persona == 'security-data' else snapshot_hash
        findings_path_value = str(findings) if outcome == 'sweep_absolute_findings_path' else str(findings.relative_to(pathlib.Path.cwd()))
        if outcome == 'sweep_wrong_findings_path' and persona == 'security-data':
            findings_path_value = '../outside.findings.md'
        data = {
            'persona_id': persona, 'expected_snapshot_sha256': expected,
            'actual_snapshot_sha256_before': snapshot_hash,
            'actual_snapshot_sha256_after': snapshot_hash, 'codex_exit_code': (1 if outcome == 'sweep_nonzero_sidecar' and persona == 'security-data' else 0),
            'findings_path': findings_path_value, 'findings_sha256': findings_hash,
            'findings_classification': classification,
            'completed_at': '2099-01-01T00:00:00Z',
        }
        sidecar.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
        chunks.append(f'## {persona}\n\n')
        if material:
            chunks.append(f'## High\n- [{persona}-high-1] Scope: material generation-five gap (fix it).\n## Medium\n## Low\n\n\n')
        else:
            chunks.append('No substantive findings.\n\n\n')
        for artifact in (findings, sidecar):
            evidence.update(artifact.name.encode() + b'\0')
            evidence.update(artifact.read_bytes())
            evidence.update(b'\0')
    if outcome == 'sweep_findings_mutated':
        target = generation_dir / 'architecture-scope.findings.md'
        target.write_text(target.read_text() + 'mutated after sidecar\n')
    if outcome == 'sweep_missing':
        (generation_dir / 'operations-deployment.result.json').unlink()
    consolidated = generation_dir / 'consolidated-findings.md'
    consolidated.write_text(''.join(chunks))
    if outcome == 'sweep_mutated_consolidated':
        consolidated.write_text(consolidated.read_text() + 'Claude says this is still clean.\n')
    if outcome == 'sweep_live_plan_mutated':
        (pathlib.Path.cwd() / 'PLAN.md').write_text('# Mutated live plan\n')
    signal = 'max-reached' if outcome == 'sweep_max' else ('cancelled' if outcome == 'sweep_cancelled' else ('degraded' if outcome == 'sweep_degraded' else 'converged'))
    phase = 'cancelled' if outcome == 'sweep_cancelled' else 'done'
    clean = 'false' if outcome in {'sweep_max', 'sweep_cancelled', 'sweep_degraded'} else 'true'
    converged_hash = '' if outcome in {'sweep_max', 'sweep_cancelled', 'sweep_degraded'} else snapshot_hash
    state_review_id = '20990101-000000-deadbe' if outcome == 'sweep_review_id_mismatch' else rid
    state_mode = 'review' if outcome == 'sweep_mode_mismatch' else 'plan'
    state_topic = 'different requested topic' if outcome == 'sweep_state_topic_mismatch' else 'review the grounded plan'
    state_repo_root = str(pathlib.Path.cwd().resolve() / 'other') if outcome == 'sweep_repo_mismatch' else str(pathlib.Path.cwd().resolve())
    state_evidence_hash = '0' * 64 if outcome == 'sweep_evidence_digest_mismatch' else evidence.hexdigest()
    state_path.write_text(f'''mode: {state_mode}\nphase: {phase}\ntopic: "{state_topic}"\nround: {generation}\nmax_rounds: {maximum}\nreview_id: {state_review_id}\nrepo_root: {state_repo_root}\ndecision_signal: {signal}\nengine: sweep-v2\ngeneration: {generation}\nmax_generations: {maximum}\nsnapshot_sha256: {snapshot_hash}\ncoverage_complete: true\nclean: {clean}\nrevision_required: false\nreviewed_live_sha256: {snapshot_hash}\nevidence_sha256: {state_evidence_hash}\nconsolidated_sha256: {hashlib.sha256(consolidated.read_bytes()).hexdigest()}\nconverged_snapshot_sha256: {converged_hash}\n''')
    if outcome in {'timeout_partial', 'timeout_partial_detached'}:
        for persona in personas[1:]:
            (generation_dir / f'{persona}.findings.md').unlink()
            (generation_dir / f'{persona}.result.json').unlink()
        consolidated.unlink()
        state_path.write_text(f'''mode: plan\nphase: reviewing\ntopic: "review the grounded plan"\nround: {generation}\nmax_rounds: {maximum}\nreview_id: {rid}\nrepo_root: {pathlib.Path.cwd().resolve()}\ndecision_signal: none\nengine: sweep-v2\ngeneration: {generation}\nmax_generations: {maximum}\nsnapshot_sha256: {snapshot_hash}\ncoverage_complete: false\nclean: false\nrevision_required: false\nreviewed_live_sha256: {snapshot_hash}\nevidence_sha256:\nconsolidated_sha256:\nconverged_snapshot_sha256:\n''')
        child = subprocess.Popen(['sleep', '60'], start_new_session=(outcome == 'timeout_partial_detached'))
        if outcome == 'timeout_partial_detached':
            (state_dir / f'{rid}-active-pgid').write_text(str(child.pid))
        marker = os.environ.get('FAKE_CHILD_PID_FILE')
        if marker: pathlib.Path(marker).write_text(str(child.pid))
        time.sleep(60)
print(json.dumps({'type': 'result', 'subtype': 'success', 'total_cost_usd': 0.01, 'session_id': 'fake-session'}))
""")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_executable(self, path, content):
        path.write_text(textwrap.dedent(content))
        path.chmod(0o755)

    def run_adapter(self, outcome="sweep_clean", timeout="5", extra_env=None, engine="sweep-v2", rounds="1", plan=None, resume_id=None, topic="review the grounded plan"):
        env = os.environ.copy()
        env["FAKE_CLAUDE_OUTCOME"] = outcome
        if extra_env:
            env.update(extra_env)
        plan_path = Path(plan) if plan is not None else self.plan
        command = [
            str(ADAPTER), "--repo", str(self.repo.resolve()), "--plan", str(plan_path.resolve()),
            "--topic", topic, "--rounds", rounds, "--timeout", timeout,
            "--budget-usd", "1.25", "--plugin-root", str(PLUGIN.resolve()),
            "--claude", str(self.claude.resolve()), "--codex", str(self.codex.resolve()),
            "--engine", engine,
        ]
        if resume_id is not None:
            command.extend(["--resume-review-id", resume_id])
        completed = subprocess.run(command, text=True, capture_output=True, env=env, timeout=10)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 1, completed.stdout)
        return completed, json.loads(lines[0])

    def test_source_runbook_uses_standard_timeout_and_resume_first_recovery(self):
        runbook = (ROOT / "skills" / "project-plan-review" / "references" / "runbook.md").read_text()
        skill = (ROOT / "skills" / "project-plan-review" / "SKILL.md").read_text()
        self.assertIn("TIMEOUT_SECONDS=3600", runbook)
        self.assertIn("BUDGET_USD=10", runbook)
        self.assertIn("TIMEOUT_SECONDS + 300", runbook)
        self.assertIn("child_timeout_seconds >= 4200", runbook)
        self.assertIn("--resume-review-id <REVIEW_ID>", runbook)
        self.assertIn("outer child timeout of at least 4,200 seconds", skill)
        self.assertIn("resume first", skill.lower())
        self.assertIn("subscription-backed", runbook)

    def test_sweep_clean_requires_exact_same_snapshot_five_persona_coverage(self):
        marker = self.base / "prompt.txt"
        completed, result = self.run_adapter(extra_env={"FAKE_PROMPT_FILE": str(marker)})
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(result["outcome"], "converged")
        self.assertTrue(result["clean"])
        self.assertEqual(result["engine"], "sweep-v2")
        self.assertEqual((result["generation"], result["max_generations"]), (1, 1))
        self.assertEqual(len(result["persona_coverage"]), 5)
        self.assertEqual([item["persona_id"] for item in result["persona_coverage"]], PERSONAS)
        self.assertEqual({item["snapshot_sha256"] for item in result["persona_coverage"]}, {result["snapshot_sha256"]})
        self.assertIn("/claudex:plan --engine sweep-v2 --from-draft --skip-interview --rounds 1", marker.read_text())
        for key in ("evidence_state_file", "generation_manifest", "generation_evidence_dir", "consolidated_findings"):
            self.assertTrue(Path(result[key]).exists(), key)
            self.assertTrue(str(Path(result[key])).startswith(result["evidence_dir"]))
        self.assertEqual(Path(result["source_state_file"]).read_bytes(), Path(result["evidence_state_file"]).read_bytes())
        source_generation = self.repo / ".claude" / "claudex" / result["review_id"] / "generations" / str(result["generation"])
        copied_generation = Path(result["generation_evidence_dir"])
        for artifact in ["PLAN.md", "manifest.json", "consolidated-findings.md"] + [f"{persona}.{suffix}" for persona in PERSONAS for suffix in ("findings.md", "result.json")]:
            self.assertEqual((source_generation / artifact).read_bytes(), (copied_generation / artifact).read_bytes(), artifact)

    def test_absolute_sidecar_findings_paths_remain_compatible(self):
        completed, result = self.run_adapter("sweep_absolute_findings_path")
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(result["clean"])

    def test_wrong_sidecar_findings_path_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_wrong_findings_path")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("security-data evidence", result["reason"])

    def test_generation_five_material_findings_are_max_reached(self):
        completed, result = self.run_adapter("sweep_max", rounds="5")
        self.assertEqual(completed.returncode, 10)
        self.assertEqual(result["outcome"], "max_reached")
        self.assertFalse(result["clean"])
        self.assertEqual((result["generation"], result["max_generations"]), (5, 5))
        self.assertEqual(result["findings_status"], "material")

    def test_missing_persona_evidence_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_missing")
        self.assertEqual(completed.returncode, 11)
        self.assertEqual(result["outcome"], "degraded")
        self.assertFalse(result["clean"])

    def test_malformed_findings_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_malformed")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertEqual(result["findings_status"], "malformed")

    def test_hash_mismatch_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_hash_mismatch")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("hash-mismatched", result["reason"])

    def test_additional_evidence_integrity_failures_cannot_be_clean(self):
        fixtures = (
            "sweep_findings_mutated",
            "sweep_nonzero_sidecar",
            "sweep_evidence_digest_mismatch",
            "sweep_live_plan_mutated",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                completed, result = self.run_adapter(fixture)
                self.assertEqual(completed.returncode, 11)
                self.assertFalse(result["clean"])

    def test_state_filename_and_review_id_must_match(self):
        completed, result = self.run_adapter("sweep_review_id_mismatch")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("filename and review_id", result["reason"])

    def test_state_scope_identity_must_match_request(self):
        for fixture in ("sweep_mode_mismatch", "sweep_repo_mismatch", "sweep_state_topic_mismatch"):
            with self.subTest(fixture=fixture):
                completed, result = self.run_adapter(fixture)
                self.assertEqual(completed.returncode, 11)
                self.assertFalse(result["clean"])

    def test_manifest_topic_must_match_state(self):
        completed, result = self.run_adapter("sweep_topic_mismatch")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("manifest topic does not match state", result["reason"])

    def test_invalid_manifest_shapes_cannot_be_clean(self):
        fixtures = (
            "sweep_empty_manifest",
            "sweep_missing_manifest",
            "sweep_wrong_type_manifest",
            "sweep_malformed_manifest",
            "sweep_schema_manifest",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                completed, result = self.run_adapter(fixture)
                self.assertEqual(completed.returncode, 11)
                self.assertFalse(result["clean"])
                self.assertIn("manifest", result["reason"])

    def test_broken_generation_chain_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_broken_chain", rounds="2")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("manifest/snapshot chain is invalid", result["reason"])

    def test_mutated_consolidated_findings_cannot_be_clean(self):
        completed, result = self.run_adapter("sweep_mutated_consolidated")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])
        self.assertIn("consolidated findings", result["reason"])

    def test_degraded_and_cancelled_state_are_never_clean(self):
        for fixture in ("sweep_degraded", "sweep_cancelled"):
            with self.subTest(fixture=fixture):
                completed, result = self.run_adapter(fixture)
                self.assertEqual(completed.returncode, 11)
                self.assertEqual(result["outcome"], "degraded")
                self.assertFalse(result["clean"])

    def test_legacy_engine_remains_compatible(self):
        completed, result = self.run_adapter("legacy_clean", engine="legacy")
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(result["clean"])
        self.assertEqual(result["engine"], "legacy")
        self.assertEqual((result["round"], result["max_rounds"]), (1, 1))
        self.assertIsNone(result["generation"])
        self.assertTrue(Path(result["final_findings"]).is_file())

    def test_legacy_signal_cannot_override_material_findings(self):
        completed, result = self.run_adapter("legacy_degraded", engine="legacy")
        self.assertEqual(completed.returncode, 11)
        self.assertFalse(result["clean"])

    def test_legacy_max_reached_remains_compatible(self):
        completed, result = self.run_adapter("legacy_max", engine="legacy")
        self.assertEqual(completed.returncode, 10)
        self.assertEqual(result["outcome"], "max_reached")
        self.assertFalse(result["clean"])

    def test_nonzero_claude_is_failed(self):
        completed, result = self.run_adapter("failed")
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["outcome"], "failed")
        self.assertFalse(result["clean"])

    def create_interrupted_sweep(self):
        completed, result = self.run_adapter("timeout_partial", timeout="0.5")
        self.assertEqual(completed.returncode, 124)
        return result

    def test_resume_identity_mismatches_are_rejected_before_provider_launch(self):
        interrupted = self.create_interrupted_sweep()
        marker = self.base / "resume-provider-prompt"
        cases = (
            {"resume_id": interrupted["review_id"], "topic": "different topic"},
            {"resume_id": interrupted["review_id"], "rounds": "2"},
            {"resume_id": "20990101-000000-deadbe"},
        )
        for index, kwargs in enumerate(cases):
            with self.subTest(index=index):
                marker.unlink(missing_ok=True)
                completed, result = self.run_adapter(extra_env={"FAKE_PROMPT_FILE": str(marker)}, **kwargs)
                self.assertEqual(completed.returncode, 12)
                self.assertEqual(result["error"]["kind"], "resume_validation")
                self.assertFalse(marker.exists())

    def test_resume_rejects_noncanonical_plan_and_terminal_state_before_provider(self):
        interrupted = self.create_interrupted_sweep()
        marker = self.base / "resume-provider-prompt"
        external = self.base / "external.md"
        external.write_text(self.plan.read_text())
        completed, result = self.run_adapter(plan=external, resume_id=interrupted["review_id"], extra_env={"FAKE_PROMPT_FILE": str(marker)})
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["error"]["kind"], "resume_validation")
        self.assertFalse(marker.exists())
        state = Path(interrupted["source_state_file"])
        state.write_text(state.read_text().replace("phase: reviewing", "phase: cancelled"))
        completed, result = self.run_adapter(resume_id=interrupted["review_id"], extra_env={"FAKE_PROMPT_FILE": str(marker)})
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["error"]["kind"], "resume_validation")
        self.assertFalse(marker.exists())

    def test_resume_rejects_active_lock_but_accepts_stale_inode(self):
        interrupted = self.create_interrupted_sweep()
        review_id = interrupted["review_id"]
        state_dir = self.repo / ".claude" / "claudex"
        marker = self.base / "resume-provider-prompt"
        lock = state_dir / f"{review_id}.lock"
        lock.write_text(f"{os.getpid()}\n")
        completed, result = self.run_adapter(resume_id=review_id, extra_env={"FAKE_PROMPT_FILE": str(marker)})
        self.assertEqual(result["error"]["kind"], "resume_validation")
        self.assertFalse(marker.exists())
        lock.write_text("999999\n")
        completed, result = self.run_adapter("failed", resume_id=review_id, extra_env={"FAKE_PROMPT_FILE": str(marker)})
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["outcome"], "failed")
        self.assertTrue(marker.is_file())
        self.assertIn(f"--resume-review-id {review_id}", marker.read_text())

    def test_timeout_kills_and_reaps_process_group(self):
        marker = self.base / "child.pid"
        completed, result = self.run_adapter("timeout", timeout="0.5", extra_env={"FAKE_CHILD_PID_FILE": str(marker)})
        self.assertEqual(completed.returncode, 124)
        self.assertEqual(result["outcome"], "timed_out")
        pid = int(marker.read_text())
        probe = subprocess.run(["kill", "-0", str(pid)], capture_output=True)
        self.assertNotEqual(probe.returncode, 0, f"child process {pid} survived timeout")

    def test_timeout_kills_detached_recorded_reviewer_group(self):
        marker = self.base / "detached-reviewer.pid"
        completed, result = self.run_adapter(
            "timeout_partial_detached", timeout="0.5", extra_env={"FAKE_CHILD_PID_FILE": str(marker)}
        )
        self.assertEqual(completed.returncode, 124)
        self.assertEqual(result["outcome"], "timed_out")
        reviewer_pid = marker.read_text().strip()
        probe = subprocess.run(["kill", "-0", reviewer_pid], capture_output=True)
        self.assertNotEqual(probe.returncode, 0, f"detached reviewer group {reviewer_pid} survived timeout")
        active_marker = Path(result["source_state_file"]).parent / f"{result['review_id']}-active-pgid"
        self.assertFalse(active_marker.exists())

    def test_external_sigterm_kills_child_group_and_emits_one_json_result(self):
        marker = self.base / "signal-child.pid"
        env = os.environ.copy()
        env.update({"FAKE_CLAUDE_OUTCOME": "timeout", "FAKE_CHILD_PID_FILE": str(marker)})
        command = [
            str(ADAPTER), "--repo", str(self.repo.resolve()), "--plan", str(self.plan.resolve()),
            "--topic", "review the grounded plan", "--rounds", "1", "--timeout", "30",
            "--budget-usd", "1.25", "--plugin-root", str(PLUGIN.resolve()),
            "--claude", str(self.claude.resolve()), "--codex", str(self.codex.resolve()),
            "--engine", "sweep-v2",
        ]
        process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        deadline = time.monotonic() + 5
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(marker.is_file(), "fake Claude child did not start")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 124, stderr)
        self.assertEqual(len(stdout.splitlines()), 1, stdout)
        result = json.loads(stdout)
        self.assertEqual(result["outcome"], "timed_out")
        self.assertFalse(result["clean"])
        self.assertIn("SIGTERM", result["reason"])
        self.assertTrue(Path(result["evidence_dir"], "result.json").is_file())
        probe = subprocess.run(["kill", "-0", marker.read_text().strip()], capture_output=True)
        self.assertNotEqual(probe.returncode, 0, "Claude descendant survived adapter SIGTERM")

    def test_timeout_reports_validated_partial_sweep_progress_and_copies_evidence(self):
        marker = self.base / "partial-child.pid"
        completed, result = self.run_adapter("timeout_partial", timeout="0.5", extra_env={"FAKE_CHILD_PID_FILE": str(marker)})
        self.assertEqual(completed.returncode, 124)
        self.assertEqual(result["outcome"], "timed_out")
        self.assertFalse(result["clean"])
        self.assertEqual((result["generation"], result["max_generations"]), (1, 1))
        self.assertEqual(result["phase"], "reviewing")
        self.assertEqual(result["snapshot_sha256"], result["persona_coverage"][0]["snapshot_sha256"])
        self.assertTrue(result["persona_coverage"][0]["valid"])
        self.assertFalse(any(item["valid"] for item in result["persona_coverage"][1:]))
        self.assertTrue(Path(result["generation_manifest"]).is_file())
        self.assertTrue(Path(result["generation_evidence_dir"]).is_dir())
        self.assertIsNone(result["consolidated_findings"])
        source = self.repo / ".claude" / "claudex" / result["review_id"] / "generations" / "1" / "architecture-scope.result.json"
        copied = Path(result["generation_evidence_dir"]) / source.name
        self.assertEqual(source.read_bytes(), copied.read_bytes())
        probe = subprocess.run(["kill", "-0", marker.read_text().strip()], capture_output=True)
        self.assertNotEqual(probe.returncode, 0)

    def test_external_plan_is_staged_and_repository_plan_is_restored(self):
        original_repo_plan = "# Repository plan\n\nKeep this intact.\n"
        external_content = "# External plan\n\nReview this safely.\n"
        self.plan.write_text(original_repo_plan)
        external_plan = self.base / "external-PLAN.md"
        external_plan.write_text(external_content)
        completed, result = self.run_adapter(plan=external_plan)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(result["clean"])
        self.assertEqual(self.plan.read_text(), original_repo_plan)
        self.assertEqual(external_plan.read_text(), external_content)

    def test_second_consecutive_run_uses_new_state(self):
        first, result1 = self.run_adapter()
        second, result2 = self.run_adapter()
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertNotEqual(result1["review_id"], result2["review_id"])
        self.assertNotEqual(result1["state_file"], result2["state_file"])

    def test_sweep_generation_cap_is_rejected_before_launch(self):
        completed, result = self.run_adapter(rounds="6")
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["error"]["kind"], "validation")
        self.assertIn("1..5", result["error"]["message"])

    def test_unexpected_io_failure_still_emits_one_json_document(self):
        output_dir = Path("/dev/null/claudex-evidence")
        completed = subprocess.run([
            str(ADAPTER), "--repo", str(self.repo.resolve()), "--plan", str(self.plan.resolve()),
            "--topic", "x", "--rounds", "1", "--timeout", "1", "--budget-usd", "1",
            "--plugin-root", str(PLUGIN.resolve()), "--claude", str(self.claude.resolve()),
            "--codex", str(self.codex.resolve()), "--output-dir", str(output_dir),
        ], text=True, capture_output=True)
        self.assertEqual(len(completed.stdout.splitlines()), 1, completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["error"]["kind"], "internal")

    def test_relative_repo_is_rejected_as_json(self):
        completed = subprocess.run([
            str(ADAPTER), "--repo", "relative", "--plan", str(self.plan.resolve()), "--topic", "x",
            "--rounds", "1", "--timeout", "1", "--budget-usd", "1",
            "--plugin-root", str(PLUGIN.resolve()), "--claude", str(self.claude.resolve()),
            "--codex", str(self.codex.resolve()),
        ], text=True, capture_output=True)
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["error"]["kind"], "validation")


if __name__ == "__main__":
    unittest.main()
