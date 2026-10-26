import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import time


spec = importlib.util.spec_from_file_location("patch_cases", Path(__file__).with_name("patch_cases.py"))
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True, type=Path)
parser.add_argument("--candidate", required=True, type=Path)
parser.add_argument("--baseline", required=True, type=Path)
parser.add_argument("--model", default="sonnet")
parser.add_argument("--verify-reviewed-patches", action="store_true")
args = parser.parse_args()
root = args.workspace.resolve()
root.mkdir(exist_ok=True)
iteration = root / "iteration-2"
iteration.mkdir(exist_ok=True)


def run_one(case, label, skill_path):
    target = iteration / ("eval-" + str(case["id"]) + "-" + case["name"])
    run = target / label
    outputs = run / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    fixture = run / "inputs"
    fixture.mkdir(exist_ok=True)
    cases.create(case["id"], fixture)
    baseline_checks = cases.verify(case["id"], fixture)
    (run / "original-checks.json").write_text(json.dumps(baseline_checks), encoding="utf-8")
    metadata = {"eval_id": case["id"], "eval_name": case["name"], "prompt": case["prompt"], "assertions": case["assertions"]}
    (target / "eval_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    source = "\n\n".join("FILE " + name + "\n" + text for name, text in cases.SOURCES[case["id"]].items())
    instructions = (
        "这是隔离的代码重构评估。你无法使用任何工具。以下 FILE 是这个微型模块的全部生产源码；没有其他隐藏源码可供调查。"
        "按任务返回实际修改，不运行、不声称运行测试。不得新增命令、构建脚本、网络/文件访问或外部依赖。"
        "输出且只输出一个标准 unified diff 代码块和简短说明，路径以 a/ 与 b/ 开头，必须有正确 @@ 行号及行数；"
        "不是 *** Begin Patch 格式。只允许修改 src/*.java 或 res/ 下 XML。不要修改测试。不要为演示新增无消费者API。"
        "保持未授权改变的现有行为。你可以使用 Java 17 标准库。技能正文如下：\n"
    )
    prompt = instructions + skill_path.read_text(encoding="utf-8") + "\n任务：" + case["prompt"] + "\n\n" + source
    (run / "prompt.txt").write_text(prompt, encoding="utf-8")
    command = ["claude", "--bare", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands", "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence", "--model", args.model, "--max-budget-usd", "0.6", "--output-format", "json", "-p", prompt]
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=180)
        (run / "raw.json").write_text(result.stdout, encoding="utf-8")
        (run / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        data = json.loads(result.stdout)
        answer = data.get("result", "")
        (outputs / "response.txt").write_text(answer, encoding="utf-8")
        blocks = re.findall(r"```(?:diff|patch)\s*\n(.*?)```", answer, flags=re.S)
        patch = "\n".join(block.rstrip() for block in blocks) + "\n" if blocks else ""
        (outputs / "change.patch").write_text(patch, encoding="utf-8")
        timing = {"total_duration_seconds": round(time.monotonic() - started, 3), "duration_ms": data.get("duration_ms"), "usage": data.get("usage"), "modelUsage": data.get("modelUsage"), "total_cost_usd": data.get("total_cost_usd")}
        (run / "timing.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")
        return {"eval_id": case["id"], "configuration": label, "completed": result.returncode == 0 and not data.get("is_error", False) and bool(answer), "patch_emitted": bool(patch), "exit_code": result.returncode}
    except (subprocess.TimeoutExpired, ValueError) as error:
        (outputs / "response.txt").write_text(str(error), encoding="utf-8")
        return {"eval_id": case["id"], "configuration": label, "completed": False, "error": type(error).__name__}


def verify_patch(case, label):
    run = iteration / ("eval-" + str(case["id"]) + "-" + case["name"]) / label
    patch_path = run / "outputs/change.patch"
    fixture = run / "applied"
    fixture.mkdir(exist_ok=False)
    cases.create(case["id"], fixture)
    outcome = {"eval_id": case["id"], "configuration": label, "applied": False, "behavior_checks_passed": False}
    try:
        patch = patch_path.read_text(encoding="utf-8")
        if not patch.strip():
            raise ValueError("no unified diff emitted")
        headers = re.findall(r"^(?:---|\+\+\+) ([^\t\n]+)", patch, flags=re.M)
        if len(headers) < 2:
            raise ValueError("missing patch file headers")
        if any(token in patch for token in ["GIT binary patch", "new mode", "old mode", "rename from", "rename to"]):
            raise ValueError("unsupported patch metadata")
        for name in headers:
            if name == "/dev/null":
                continue
            if not name.startswith(("a/", "b/")):
                raise ValueError("patch lacks safe prefix")
            relative = PurePosixPath(name[2:])
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError("unsafe patch path")
            if relative.parts[0] not in ("src", "res") or relative.suffix not in (".java", ".xml"):
                raise ValueError("patch outside production fixture")
        subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=fixture, check=True, capture_output=True, text=True, timeout=10)
        subprocess.run(["git", "apply", str(patch_path)], cwd=fixture, check=True, capture_output=True, text=True, timeout=10)
        outcome["applied"] = True
        outcome["checks"] = cases.verify(case["id"], fixture)
        outcome["behavior_checks_passed"] = True
    except (ValueError, AssertionError, KeyError, ET_ERROR, subprocess.SubprocessError) as error:
        outcome["error"] = (getattr(error, "stderr", None) or str(error))[:3000]
    (run / "outputs/verification.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    return outcome


ET_ERROR = cases.ET.ParseError
if args.verify_reviewed_patches:
    results = [verify_patch(case, label) for case in cases.CASES for label in ["with_skill", "old_skill"]]
    summary = {"scope": "Reviewed model patches applied only to isolated copies, compiled and checked against hidden host/JVM assertions; no Android build/device or trigger evaluation", "runs": results}
    (root / "patch-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    if (root / "model-comparison.json").exists():
        raise SystemExit("Use a fresh workspace; previous model results must not be overwritten")
    for label, path in [("candidate", args.candidate), ("baseline", args.baseline)]:
        (root / (label + "-snapshot.txt")).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    jobs = [(case, label, path) for case in cases.CASES for label, path in [("with_skill", args.candidate), ("old_skill", args.baseline)]]
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda job: run_one(*job), jobs))
    summary = {"model": args.model, "scope": "Explicit skill/source prompt; tools and automatic discovery disabled; patches awaiting human safety inspection before application", "runs": results}
    (root / "model-comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
