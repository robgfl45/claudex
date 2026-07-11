#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "bin" / "claudex-plan-review"
PLUGIN = ROOT / "plugins" / "claudex"


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
        self._write_executable(self.claude, """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time, uuid
if sys.argv[1:] == ['--version']:
    print('2.test'); raise SystemExit(0)
if sys.argv[1:] == ['auth', 'status']:
    print(json.dumps({'loggedIn': True, 'authMethod': 'test'})); raise SystemExit(0)
outcome = os.environ.get('FAKE_CLAUDE_OUTCOME', 'converged')
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
if outcome == 'max_reached':
    signal, findings, round_value = 'max-reached', '# Round 1 findings\\n\\n## High\\n- unsafe gap (fix it)\\n', '2'
elif outcome == 'degraded':
    signal, findings, round_value = 'no-material-findings', '# Round 1 findings\\n\\n## High\\n- contradiction (fix it)\\n', '1'
else:
    signal, findings, round_value = 'no-material-findings', '# Round 1 findings\\n\\nNo substantive findings.\\n', '1'
(review_dir / 'findings-round-1.md').write_text(findings)
state = state_dir / (rid + '.state')
state.write_text(f'''mode: plan\nphase: done\ntopic: test\nround: {round_value}\nmax_rounds: 1\nreview_id: {rid}\nrepo_root: {pathlib.Path.cwd().resolve()}\ndecision_signal: {signal}\n''')
print(json.dumps({'type': 'result', 'subtype': 'success', 'total_cost_usd': 0.01, 'session_id': 'fake-session'}))
""")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_executable(self, path, content):
        path.write_text(textwrap.dedent(content))
        path.chmod(0o755)

    def run_adapter(self, outcome="converged", timeout="5", extra_env=None):
        env = os.environ.copy()
        env["FAKE_CLAUDE_OUTCOME"] = outcome
        if extra_env:
            env.update(extra_env)
        command = [
            str(ADAPTER), "--repo", str(self.repo.resolve()), "--plan", str(self.plan.resolve()),
            "--topic", "review the grounded plan", "--rounds", "1", "--timeout", timeout,
            "--budget-usd", "1.25", "--plugin-root", str(PLUGIN.resolve()),
            "--claude", str(self.claude.resolve()), "--codex", str(self.codex.resolve()),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, env=env, timeout=10)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 1, completed.stdout)
        return completed, json.loads(lines[0])

    def test_converged_is_only_clean_success(self):
        completed, result = self.run_adapter("converged")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(result["outcome"], "converged")
        self.assertTrue(result["clean"])
        self.assertEqual(result["findings_status"], "none")
        self.assertTrue(Path(result["evidence_dir"], "result.json").is_file())

    def test_max_reached_is_honest_and_nonzero(self):
        completed, result = self.run_adapter("max_reached")
        self.assertEqual(completed.returncode, 10)
        self.assertEqual(result["outcome"], "max_reached")
        self.assertFalse(result["clean"])

    def test_prose_or_signal_cannot_override_material_findings(self):
        completed, result = self.run_adapter("degraded")
        self.assertEqual(completed.returncode, 11)
        self.assertEqual(result["outcome"], "degraded")
        self.assertFalse(result["clean"])
        self.assertEqual(result["findings_status"], "material")

    def test_nonzero_claude_is_failed(self):
        completed, result = self.run_adapter("failed")
        self.assertEqual(completed.returncode, 12)
        self.assertEqual(result["outcome"], "failed")
        self.assertFalse(result["clean"])

    def test_timeout_kills_and_reaps_process_group(self):
        marker = self.base / "child.pid"
        completed, result = self.run_adapter("timeout", timeout="0.5", extra_env={"FAKE_CHILD_PID_FILE": str(marker)})
        self.assertEqual(completed.returncode, 124)
        self.assertEqual(result["outcome"], "timed_out")
        self.assertFalse(result["clean"])
        pid = int(marker.read_text())
        probe = subprocess.run(["kill", "-0", str(pid)], capture_output=True)
        self.assertNotEqual(probe.returncode, 0, f"child process {pid} survived timeout")

    def test_second_consecutive_run_uses_new_state(self):
        first, result1 = self.run_adapter("converged")
        second, result2 = self.run_adapter("converged")
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertNotEqual(result1["review_id"], result2["review_id"])
        self.assertNotEqual(result1["state_file"], result2["state_file"])

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
