#!/usr/bin/env python3
"""Prepare and validate concise, context-aware bug descriptions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_FILE = Path.home() / ".claude" / "bug-context" / "context.json"
PRESETS_DIR = Path.home() / ".claude" / "bug-context" / "presets"
HEADINGS = ["背景", "前置状态", "复现步骤", "预期结果", "实际结果"]
# 内置兜底词表：仅在没有预置词文档时生效。项目生成预置词后按整类覆盖。
DEFAULT_OBJECTS: list[str] = []
DEFAULT_AMBIGUOUS_PHRASES = [
    "画面不一致",
    "显示不一致",
    "不一致",
    "不对",
    "不正常",
    "异常",
    "有变化",
    "有变动",
    "卡住",
    "卡死",
    "有问题",
    "没反应",
]
DEFAULT_CAUSE_MARKERS = ["原因是", "由于", "导致", "未同步", "状态丢失", "计算错误"]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"projects": {}, "common_terms": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取背景缓存 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"背景缓存格式错误：{path} 顶层必须是对象")
    data.setdefault("projects", {})
    data.setdefault("common_terms", {})
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


PRESET_DEFAULTS: dict[str, list[str]] = {
    "objects": DEFAULT_OBJECTS,
    "ambiguous_phrases": DEFAULT_AMBIGUOUS_PHRASES,
    "cause_markers": DEFAULT_CAUSE_MARKERS,
}


def presets_path(project: str | None) -> Path:
    if not project:
        raise SystemExit("未提供项目名，无法定位预置词文档")
    safe = re.sub(r"[^\w一-鿿-]", "_", project).strip("_") or "project"
    return PRESETS_DIR / f"{safe}.json"


def load_presets(project: str | None) -> dict[str, Any]:
    """读取项目预置词文档；未提供项目或文档缺失时回退到内置兜底词表。"""
    presets = {key: list(value) for key, value in PRESET_DEFAULTS.items()}
    if not project:
        return {"path": None, "exists": False, **presets}
    path = presets_path(project)
    if not path.exists():
        return {"path": str(path), "exists": False, **presets}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取预置词文档 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"预置词文档格式错误：{path} 顶层必须是对象")
    for key in ("objects", "ambiguous_phrases", "cause_markers"):
        value = data.get(key)
        if isinstance(value, list):
            presets[key] = [str(item) for item in value]
    return {"path": str(path), "exists": True, **presets}


def save_presets(project: str | None, data: dict[str, Any]) -> Path:
    path = presets_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {key: data[key] for key in ("objects", "ambiguous_phrases", "cause_markers") if key in data})
    return path


def objects_to_patterns(objects: list[str]) -> list[tuple[str, str]]:
    """对象词 → 相对指代正则，如 clip → “前面的clip”→clipA。"""
    patterns: list[tuple[str, str]] = []
    for obj in objects:
        escaped = re.escape(obj)
        for prefix, target in (
            ("前面(?:的)?", f"{obj}A"),
            ("后面(?:的)?", f"{obj}B"),
            ("前一个", f"{obj}A"),
            ("后一个", f"{obj}B"),
        ):
            patterns.append((rf"{prefix}\s*{escaped}", target))
    return patterns


def normalize_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).casefold()


def known_projects() -> list[str]:
    """已登记的项目名，来自预置词文档目录。"""
    if not PRESETS_DIR.exists():
        return []
    return sorted(path.stem for path in PRESETS_DIR.glob("*.json") if path.is_file())


def match_project(project: str, candidates: list[str]) -> str | None:
    """把项目名收敛到已登记的名字；大小写、分隔符与平台后缀差异视为同一个项目。"""
    key = normalize_key(project)
    if not key:
        return None
    for name in candidates:
        if normalize_key(name) == key:
            return name
    shorter = [name for name in candidates if normalize_key(name).startswith(key)]
    if len(shorter) == 1:
        return shorter[0]
    longer = [name for name in candidates if key.startswith(normalize_key(name))]
    if len(longer) == 1:
        return longer[0]
    return None


def detect_project_from_cwd() -> str | None:
    """按当前 Git 仓库根目录名推断项目；worktree 归到主仓库的名字。"""
    for options in (("--path-format=absolute", "--git-common-dir"), ("--show-toplevel",)):
        try:
            result = subprocess.run(
                ("git", "rev-parse", *options),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        root = result.stdout.strip()
        if result.returncode == 0 and root:
            path = Path(root)
            return (path.parent if path.name == ".git" else path).name or None
    return None


def resolve_project(project: str | None) -> dict[str, Any]:
    """确定本次要用的项目名。

    显式传入的名字先按已登记项目收敛，避免同一项目的不同写法分裂成多份文档；
    未传入时按当前仓库根目录名推断，省去每次手写。
    """
    if project:
        matched = match_project(project, known_projects())
        return {
            "name": matched or project,
            "alias_from": project if matched and matched != project else None,
            "auto": False,
        }
    detected = detect_project_from_cwd()
    if not detected:
        return {"name": None, "alias_from": None, "auto": False}
    return {
        "name": match_project(detected, known_projects()) or detected,
        "alias_from": None,
        "auto": True,
    }


def project_fields(args: argparse.Namespace) -> dict[str, Any]:
    """把项目名的收敛/推断结果带进输出，避免用错名字却看不出来。"""
    fields: dict[str, Any] = {}
    alias_from = getattr(args, "project_alias_from", None)
    if alias_from:
        fields["project_resolved_from"] = alias_from
    if getattr(args, "project_auto", False):
        fields["project_source"] = "auto"
    return fields


def extract_bug_id(text: str) -> str | None:
    match = re.search(r"#[0-9A-Za-z]+(?:_[0-9A-Za-z]+)*", text)
    return match.group(0) if match else None


def extract_feature(text: str, bug_id: str | None) -> str | None:
    body = text.replace(bug_id, "", 1).strip() if bug_id else text.strip()
    match = re.match(r"([^\-—–:：\n]{2,40})\s*[\-—–:：]", body)
    if match:
        return match.group(1).strip()
    return None


def find_relative_entities(text: str, objects: list[str]) -> list[dict[str, str]]:
    entities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pattern, suggested in objects_to_patterns(objects):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            item = (match.group(0), suggested)
            if item not in seen:
                seen.add(item)
                entities.append({"original": item[0], "suggested": item[1]})
    return entities


def find_ambiguities(text: str, phrases: list[str]) -> list[str]:
    found: list[str] = []
    for phrase in phrases:
        if phrase in text and not any(phrase in existing for existing in found):
            found.append(phrase)
    return found[:5]


def feature_context(
    data: dict[str, Any], project: str | None, feature: str | None
) -> dict[str, Any]:
    result: dict[str, Any] = {"background": [], "terms": {}}
    common_terms = data.get("common_terms", {})
    if isinstance(common_terms, dict):
        result["terms"].update(common_terms)
    if not project or not feature:
        return result

    projects = data.get("projects", {})
    project_data = next(
        (
            value
            for key, value in projects.items()
            if normalize_key(key) == normalize_key(project) and isinstance(value, dict)
        ),
        None,
    )
    if not project_data:
        return result

    features = project_data.get("features", {})
    for name, value in features.items():
        if not isinstance(value, dict):
            continue
        aliases = value.get("aliases", [])
        candidates = [name, *aliases] if isinstance(aliases, list) else [name]
        if not any(normalize_key(item) == normalize_key(feature) for item in candidates):
            continue
        backgrounds = value.get("background", [])
        if isinstance(backgrounds, list):
            result["background"] = [str(item) for item in backgrounds[:5]]
        terms = value.get("terms", {})
        if isinstance(terms, dict):
            result["terms"].update({str(k): str(v) for k, v in terms.items()})
        result["matched_feature"] = name
        break
    return result


def command_prepare(args: argparse.Namespace) -> int:
    text = args.text if args.text is not None else sys.stdin.read()
    text = text.strip()
    if not text:
        raise SystemExit("请通过 --text 或 stdin 提供原始 Bug 文案")

    bug_id = extract_bug_id(text)
    feature = args.feature or extract_feature(text, bug_id)
    context_file = Path(args.context_file).expanduser()
    context = feature_context(read_json(context_file), args.project, feature)
    context["terms"] = {
        source: target
        for source, target in context.get("terms", {}).items()
        if source.casefold() in text.casefold()
    }
    presets = load_presets(args.project)
    ambiguities = find_ambiguities(text, presets["ambiguous_phrases"])

    output = {
        "bug_id": bug_id,
        "feature": feature,
        "project": args.project,
        **project_fields(args),
        "presets": {
            "exists": presets["exists"],
            "path": presets["path"],
            "objects": presets["objects"],
        },
        "context": context,
        "relative_entities": find_relative_entities(text, presets["objects"]),
        "ambiguities": ambiguities,
        "status": "NEEDS_SEMANTIC_CHECK" if ambiguities else "READY_FOR_REWRITE",
        "guidance": (
            "对最影响实际结果或预期结果的歧义只问一个问题，不扩大搜索。"
            if ambiguities
            else "优先直接整理；不要为非关键背景继续搜索。"
        ),
    }
    if not presets["exists"]:
        output["presets"]["known_projects"] = known_projects()
    if output.get("project") and not output["presets"]["exists"]:
        output["project_warning"] = (
            f"未找到项目预置词文档 {presets['path']}；"
            f"已登记项目：{known_projects() or '（无）'}。"
            "名字不符时需要先确认项目名，不要沿用兜底词表直接整理。"
        )
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


def read_input_text(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).expanduser().read_text(encoding="utf-8")
    return sys.stdin.read()


def section_content(text: str, heading: str, next_heading: str | None) -> str:
    start = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE)
    if not start:
        return ""
    end = (
        re.search(
            rf"^##\s+{re.escape(next_heading)}\s*$",
            text[start.end() :],
            flags=re.MULTILINE,
        )
        if next_heading
        else None
    )
    end_index = start.end() + end.start() if end else len(text)
    return text[start.end() : end_index].strip()


def command_validate(args: argparse.Namespace) -> int:
    text = read_input_text(args)
    errors: list[str] = []
    warnings: list[str] = []

    positions: list[int] = []
    for heading in HEADINGS:
        match = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE)
        if not match:
            errors.append(f"缺少章节：{heading}")
        else:
            positions.append(match.start())
    if len(positions) == len(HEADINGS) and positions != sorted(positions):
        errors.append("章节顺序必须是：" + "、".join(HEADINGS))

    for index, heading in enumerate(HEADINGS):
        next_heading = HEADINGS[index + 1] if index + 1 < len(HEADINGS) else None
        if re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE):
            content = section_content(text, heading, next_heading)
            if not content:
                errors.append(f"章节内容为空：{heading}")

    if args.bug_id and args.bug_id not in text:
        errors.append(f"未原样保留 Bug 编号：{args.bug_id}")

    presets = load_presets(args.project)
    actual = section_content(text, "实际结果", None)
    for marker in presets["cause_markers"]:
        if marker in actual:
            warnings.append(f"实际结果可能混入根因推测：{marker}")
    for phrase in presets["ambiguous_phrases"]:
        if phrase in actual:
            warnings.append(f"实际结果仍包含模糊表达：{phrase}")
            break

    result = {"valid": not errors, "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if not errors else 1


def parse_terms(values: list[str]) -> dict[str, str]:
    terms: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"术语格式应为 原词=项目术语：{value}")
        source, target = value.split("=", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            raise SystemExit(f"术语格式应为 原词=项目术语：{value}")
        terms[source] = target
    return terms


def merge_words(existing: Any, additions: list[str]) -> list[str]:
    """按原有顺序合并词条，只追加没有的，避免一次 --objects 把整类冲掉。"""
    merged = [str(item) for item in existing] if isinstance(existing, list) else []
    keys = {normalize_key(item) for item in merged}
    for item in additions:
        text = item.strip()
        if text and normalize_key(text) not in keys:
            merged.append(text)
            keys.add(normalize_key(text))
    return merged


def command_context_set(args: argparse.Namespace) -> int:
    path = Path(args.context_file).expanduser()
    data = read_json(path)
    projects = data.setdefault("projects", {})
    matched_project = find_project(data, args.project)
    if matched_project:
        project_name, project = matched_project
    else:
        project_name = args.project
        project = projects.setdefault(project_name, {"features": {}})

    features = project.setdefault("features", {})
    matched_feature = find_feature(project, args.feature)
    if matched_feature:
        feature_name, feature = matched_feature
    else:
        feature_name = args.feature
        feature = features.setdefault(
            feature_name, {"aliases": [], "background": [], "terms": {}}
        )

    for value in args.alias:
        if value not in feature["aliases"]:
            feature["aliases"].append(value)
    for value in args.background:
        if value not in feature["background"]:
            feature["background"].append(value)
    feature["terms"].update(parse_terms(args.term))
    write_json(path, data)

    print(
        json.dumps(
            {
                "saved": True,
                "project": project_name,
                "feature": feature_name,
                "context_file": str(path),
                **project_fields(args),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_context_get(args: argparse.Namespace) -> int:
    path = Path(args.context_file).expanduser()
    context = feature_context(read_json(path), args.project, args.feature)
    print(json.dumps({**context, **project_fields(args)}, ensure_ascii=False, separators=(",", ":")))
    return 0


def find_project(data: dict[str, Any], project_name: str) -> tuple[str, dict[str, Any]] | None:
    projects = data.get("projects", {})
    for name, value in projects.items():
        if normalize_key(name) == normalize_key(project_name) and isinstance(value, dict):
            return name, value
    return None


def find_feature(project: dict[str, Any], feature_name: str) -> tuple[str, dict[str, Any]] | None:
    features = project.get("features", {})
    for name, value in features.items():
        if not isinstance(value, dict):
            continue
        aliases = value.get("aliases", [])
        candidates = [name, *aliases] if isinstance(aliases, list) else [name]
        if any(normalize_key(item) == normalize_key(feature_name) for item in candidates):
            return name, value
    return None


def command_context_list(args: argparse.Namespace) -> int:
    path = Path(args.context_file).expanduser()
    data = read_json(path)
    matched_project = find_project(data, args.project) if args.project else None
    if args.project and not matched_project:
        output: dict[str, Any] = {"project": args.project, "features": {}, **project_fields(args)}
    elif matched_project:
        name, project = matched_project
        output = {"project": name, "features": project.get("features", {})}
    else:
        output = {
            "projects": data.get("projects", {}),
            "common_terms": data.get("common_terms", {}),
        }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_context_remove(args: argparse.Namespace) -> int:
    path = Path(args.context_file).expanduser()
    data = read_json(path)
    matched_project = find_project(data, args.project)
    removed: dict[str, list[str]] = {"background": [], "terms": [], "aliases": []}
    if not matched_project:
        print(json.dumps({"removed": removed}, ensure_ascii=False, separators=(",", ":")))
        return 0

    project_name, project = matched_project
    matched_feature = find_feature(project, args.feature)
    if not matched_feature:
        print(json.dumps({"removed": removed}, ensure_ascii=False, separators=(",", ":")))
        return 0

    feature_name, feature = matched_feature
    for value in args.background:
        if value in feature.get("background", []):
            feature["background"].remove(value)
            removed["background"].append(value)
    for value in args.term:
        if value in feature.get("terms", {}):
            del feature["terms"][value]
            removed["terms"].append(value)
    for value in args.alias:
        if value in feature.get("aliases", []):
            feature["aliases"].remove(value)
            removed["aliases"].append(value)

    if not feature.get("aliases") and not feature.get("background") and not feature.get("terms"):
        project.get("features", {}).pop(feature_name, None)
    if not project.get("features"):
        data.get("projects", {}).pop(project_name, None)

    write_json(path, data)
    print(json.dumps({"removed": removed}, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_presets_set(args: argparse.Namespace) -> int:
    if not (args.objects or args.ambiguous or args.cause):
        raise SystemExit("至少提供一个预置词类别：--objects / --ambiguous / --cause")
    path = presets_path(args.project)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"无法读取预置词文档 {path}: {exc}") from exc
        if isinstance(existing, dict):
            data = existing
    fields = (
        ("objects", args.objects),
        ("ambiguous_phrases", args.ambiguous),
        ("cause_markers", args.cause),
    )
    merged_fields: list[str] = []
    for key, additions in fields:
        if not additions:
            continue
        before = len(data.get(key) or [])
        if args.replace:
            data[key] = [item.strip() for item in additions if item.strip()]
        else:
            data[key] = merge_words(data.get(key), additions)
        if len(data[key]) != before:
            merged_fields.append(key)
    path = save_presets(args.project, data)
    print(
        json.dumps(
            {
                "saved": True,
                "project": args.project,
                "presets_file": str(path),
                "merged": merged_fields,
                **project_fields(args),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_presets_get(args: argparse.Namespace) -> int:
    presets = load_presets(args.project)
    print(json.dumps({**presets, **project_fields(args)}, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_presets_list(args: argparse.Namespace) -> int:
    if not PRESETS_DIR.exists():
        print(json.dumps({"projects": []}, ensure_ascii=False, separators=(",", ":")))
        return 0
    projects = [path.stem for path in sorted(PRESETS_DIR.glob("*.json")) if path.is_file()]
    print(json.dumps({"projects": projects}, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_presets_remove(args: argparse.Namespace) -> int:
    path = presets_path(args.project)
    if not path.exists():
        raise SystemExit(f"预置词文档不存在：{path}")
    path.unlink()
    print(
        json.dumps(
            {
                "removed": True,
                "project": args.project,
                "presets_file": str(path),
                **project_fields(args),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="低成本准备和校验标准 Bug 描述")
    parser.add_argument(
        "--context-file", default=str(DEFAULT_CONTEXT_FILE), help="轻量背景缓存 JSON"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="解析原始 Bug 并读取匹配背景")
    prepare.add_argument("--text", help="原始 Bug；省略时从 stdin 读取")
    prepare.add_argument("--project", help="项目名")
    prepare.add_argument("--feature", help="功能名；省略时从标题推断")
    prepare.set_defaults(handler=command_prepare)

    validate = subparsers.add_parser("validate", help="校验五段标准格式")
    validate.add_argument("--file", help="待校验 Markdown；省略时从 stdin 读取")
    validate.add_argument("--bug-id", help="必须原样保留的 Bug 编号")
    validate.add_argument("--project", help="项目名，用于读取项目预置词")
    validate.set_defaults(handler=command_validate)

    context_set = subparsers.add_parser("context-set", help="保存经确认的稳定功能背景")
    context_set.add_argument("--project", required=True)
    context_set.add_argument("--feature", required=True)
    context_set.add_argument("--alias", action="append", default=[])
    context_set.add_argument("--background", action="append", default=[])
    context_set.add_argument("--term", action="append", default=[])
    context_set.set_defaults(handler=command_context_set)

    context_get = subparsers.add_parser("context-get", help="读取一个功能的轻量背景")
    context_get.add_argument("--project", required=True)
    context_get.add_argument("--feature", required=True)
    context_get.set_defaults(handler=command_context_get)

    context_list = subparsers.add_parser("context-list", help="查看已沉淀的背景知识")
    context_list.add_argument("--project", help="项目名；省略时查看全部")
    context_list.set_defaults(handler=command_context_list)

    context_remove = subparsers.add_parser("context-remove", help="删除错误或过时的背景知识")
    context_remove.add_argument("--project", required=True)
    context_remove.add_argument("--feature", required=True)
    context_remove.add_argument("--alias", action="append", default=[])
    context_remove.add_argument("--background", action="append", default=[])
    context_remove.add_argument("--term", action="append", default=[])
    context_remove.set_defaults(handler=command_context_remove)

    presets_set = subparsers.add_parser("presets-set", help="为项目写入预置词文档")
    presets_set.add_argument("--project", required=True)
    presets_set.add_argument("--objects", action="append", help="对象词，如 clip；可多个")
    presets_set.add_argument("--ambiguous", action="append", help="项目模糊词，可多个")
    presets_set.add_argument("--cause", action="append", help="项目根因标记词，可多个")
    presets_set.add_argument(
        "--replace", action="store_true", help="整类替换而不是追加（默认按类合并）"
    )
    presets_set.set_defaults(handler=command_presets_set)

    presets_get = subparsers.add_parser("presets-get", help="读取项目生效的预置词")
    presets_get.add_argument("--project", required=True)
    presets_get.set_defaults(handler=command_presets_get)

    presets_list = subparsers.add_parser("presets-list", help="列出已有预置词文档的项目")
    presets_list.set_defaults(handler=command_presets_list)

    presets_remove = subparsers.add_parser("presets-remove", help="删除项目的预置词文档")
    presets_remove.add_argument("--project", required=True)
    presets_remove.set_defaults(handler=command_presets_remove)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "project"):
        resolved = resolve_project(args.project)
        args.project = resolved["name"]
        args.project_alias_from = resolved["alias_from"]
        args.project_auto = resolved["auto"]
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
