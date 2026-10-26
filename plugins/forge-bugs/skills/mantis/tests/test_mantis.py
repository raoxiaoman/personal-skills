import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
config = sys.stdin.read()
assert args[:2] == ["--config", "-"]
assert "fake-secret" in config
assert not any("fake-secret" in arg or "Authorization:" in arg for arg in args)
log = pathlib.Path(os.environ["FAKE_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps(args) + "\n")
method = args[args.index("-X") + 1]
query = [args[i + 1] for i, arg in enumerate(args) if arg == "--data-urlencode"]
params = dict(item.split("=", 1) for item in query)
scenario = os.environ.get("SCENARIO", "pages")
status = "200"
issue = lambda n: {"id": n, "summary": "#1216C_" + str(n) + " title | detail", "priority": {"label": "低"}, "status": {"id": 50, "label": "已分配"}, "handler": {"id": 298}}
if method == "PATCH":
    status = "500" if scenario == "status-fail" else "200"
    body = {}
elif method == "POST":
    status = "500" if scenario == "note-fail" else "201"
    body = {"message": "note failed"} if status == "500" else {}
elif "id" in params:
    status = "500" if scenario == "read-fail" else "200"
    body = {"issues": [{"id": 7, "status": {"id": 80}}]}
else:
    page = int(params.get("page", "1"))
    if scenario == "page-fail" and page == 2:
        status, body = "500", {"message": "page failed"}
    elif scenario == "invalid":
        body = {"message": "missing issues"}
    elif scenario == "duplicate":
        body = {"issues": [issue(1)]}
    elif scenario == "empty":
        body = {"issues": []}
    else:
        body = {"issues": [issue(page)] if page <= 2 else []}
pathlib.Path(args[args.index("-o") + 1]).write_text(json.dumps(body))
sys.stdout.write(status)
'''


class MantisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        curl = self.root / "curl"
        curl.write_text(FAKE_CURL)
        curl.chmod(0o700)
        self.token = self.root / "token"
        self.token.write_text('fake-secret\\"quoted\n')
        self.log = self.root / "requests.jsonl"
        self.env = dict(os.environ, HOME=str(self.root), PATH=f"{self.root}:{os.environ['PATH']}",
                        MANTIS_TOKEN_FILE=str(self.token), MANTIS_BASE_URL="https://fake.invalid/api",
                        MANTIS_FILTER_FETCH_SIZE="1", MANTIS_MAX_PAGES="5", FAKE_LOG=str(self.log))

    def run_cli(self, *args, scenario="pages"):
        return subprocess.run(["/bin/bash", str(ROOT / "scripts" / "mantis.sh"), *args],
                              env=dict(self.env, SCENARIO=scenario), capture_output=True, text=True)

    def requests(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_all_pages_json(self):
        result = self.run_cli("list", "--assignee", "298", "--all", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["pagination"]["complete"])
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["pagination"]["all"])
        self.assertEqual(payload["issues"][0]["summary"], "#1216C_1 title | detail")
        self.assertEqual(len(self.requests()), 3)
        self.assertNotIn("fake-secret", result.stdout + result.stderr + self.log.read_text())

    def test_filtered_display_pagination_keeps_full_total(self):
        result = self.run_cli("list", "--assignee", "298", "--page", "2", "--page-size", "1", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual([issue["id"] for issue in payload["issues"]], [2])
        self.assertEqual(payload["pagination"]["total"], 2)
        self.assertFalse(payload["pagination"]["all"])

    def test_human_six_columns_still_work(self):
        result = self.run_cli("list", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("低 | - | - | 已分配 | #1216C_1", result.stdout)
        self.assertIn("完整筛选结果共 2", result.stderr)

    def test_page_failure_never_returns_partial_list(self):
        result = self.run_cli("list", "--all", "--json", scenario="page-fail")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertNotIn("issues", payload)

    def test_duplicate_page_fails_without_loop(self):
        result = self.run_cli("list", "--all", "--json", scenario="duplicate")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertEqual(len(self.requests()), 2)

    def test_page_limit_fails_instead_of_truncating(self):
        self.env["MANTIS_MAX_PAGES"] = "1"
        result = self.run_cli("list", "--all", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_empty_and_invalid_response(self):
        empty = self.run_cli("list", "--all", "--json", scenario="empty")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        payload = json.loads(empty.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issues"], [])
        self.assertTrue(payload["pagination"]["complete"])
        invalid = self.run_cli("list", "--all", "--json", scenario="invalid")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(json.loads(invalid.stdout)["ok"])

    def test_partial_update_reports_completed_status_without_retry(self):
        result = self.run_cli("update", "7", "--status", "80", "--note", "fixed", "--json", scenario="note-fail")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["steps"], {"status": "completed", "note": "unknown"})
        methods = [args[args.index("-X") + 1] for args in self.requests()]
        self.assertEqual(methods, ["PATCH", "GET", "POST"])

    def test_status_failure_or_read_failure_never_posts_note(self):
        for scenario, step in (("status-fail", "unknown"), ("read-fail", "unverified")):
            result = self.run_cli("update", "7", "--status", "80", "--note", "fixed", "--json", scenario=scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["steps"], {"status": step, "note": "not_attempted"})
        self.assertFalse(any(args[args.index("-X") + 1] == "POST" for args in self.requests()))

    def test_successful_update_and_standalone_note(self):
        result = self.run_cli("update", "7", "--status", "80", "--note", "fixed", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["steps"], {"status": "completed", "note": "completed"})
        note = self.run_cli("note", "7", "fixed", "--json")
        self.assertTrue(json.loads(note.stdout)["ok"])

    def test_multiline_token_rejected_before_request(self):
        self.token.write_text("fake-secret\nsecond-line\n")
        result = self.run_cli("list", "--all", "--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests(), [])
        self.assertNotIn("fake-secret", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
