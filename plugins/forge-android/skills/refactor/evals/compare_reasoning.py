import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time


parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True, type=Path)
parser.add_argument("--candidate", required=True, type=Path)
parser.add_argument("--baseline", required=True, type=Path)
parser.add_argument("--model", required=True)
args = parser.parse_args()
root = args.workspace.resolve()
fixture_dirs = sorted(root.glob("runtime-*"))
if not fixture_dirs:
    raise SystemExit("Run check_fixtures.py first")
fixtures = fixture_dirs[-1]
evals = json.loads((args.candidate.parent / "evals/evals.json").read_text(encoding="utf-8"))["evals"]
iteration = root / "iteration-1"
iteration.mkdir(exist_ok=True)


def run_one(case, label, skill_path):
    target = iteration / ("eval-" + str(case["id"]))
    output = target / label
    (output / "outputs").mkdir(parents=True, exist_ok=True)
    metadata = {"eval_id": case["id"], "eval_name": "scenario-" + str(case["id"]), "prompt": case["prompt"], "assertions": case["assertions"]}
    (target / "eval_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    source = "\n\n".join("FILE " + item + "\n" + (fixtures / item).read_text(encoding="utf-8") for item in case["files"])
    prompt = "这是隔离的只读重构评估。工具不可用，不执行命令、不修改文件、不委派。仅根据所给规则与源码返回简洁方案、必要代码和验证说明。不得声称已执行。以下是需要遵循的技能规则：\n" + skill_path.read_text(encoding="utf-8") + "\n\n任务：" + case["prompt"] + "\n\n" + source
    started = time.monotonic()
    command = ["claude", "--bare", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence", "--model", args.model, "--max-budget-usd", "0.6", "--output-format", "json", "-p", prompt]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=110)
        (output / "raw.json").write_text(result.stdout, encoding="utf-8")
        (output / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        data = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        answer = data.get("result", result.stdout)
        success = result.returncode == 0 and bool(answer) and not data.get("is_error", False)
        (output / "outputs/response.txt").write_text(answer, encoding="utf-8")
        timing = {"total_duration_seconds": round(time.monotonic() - started, 3), "duration_ms": data.get("duration_ms"), "usage": data.get("usage"), "total_cost_usd": data.get("total_cost_usd")}
        (output / "timing.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")
        return {"eval_id": case["id"], "configuration": label, "completed": success, "exit_code": result.returncode}
    except subprocess.TimeoutExpired as error:
        (output / "outputs/response.txt").write_text("Model call exceeded 110 second limit; no evaluation result.", encoding="utf-8")
        return {"eval_id": case["id"], "configuration": label, "completed": False, "error": "timeout"}


jobs = [(case, label, path) for case in evals for label, path in [("with_skill", args.candidate), ("old_skill", args.baseline)]]
with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(run_one, *job) for job in jobs]
    results = [future.result() for future in futures]
summary = {"model": args.model, "scope": "Prompt-only reasoning comparison with tools disabled, not agent implementation or trigger accuracy evaluation; ungraded outputs need human review", "runs": results}
(root / "model-comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(item["completed"] for item in results) else 1)
