#!/usr/bin/env python3
"""离线发版检查；可显式离线解析依赖，不上传或操作设备。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_common import load_project, digest, git, worktree_inputs, commit_inputs, registry_text, tool_digest, verify_identity, repo_root, new_output, graph_safe
import release_config_check as config_check
import release_draft_check as draft_check
import release_purchase_check as purchase_check

def lexical(text, strings=False):
    # 保持长度和行号；字符串先匹配，避免把 URL 的 // 当注释。
    pattern = r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    def replace(match):
        value = match.group()
        if not strings and not value.startswith(('//', '/*')):
            return value
        return ''.join('\n' if ch == '\n' else ' ' for ch in value)
    return re.sub(pattern, replace, text)


def item(name, status, evidence):
    return dict(name=name, status=status, evidence=evidence)


def version(text):
    text = lexical(text.replace('\r\n', '\n'))
    # 只接受完整行的字面量声明，不能把表达式前缀当成最终构建值。
    code = re.findall(r'^[ \t]*versionCode\s*=[ \t]*(\d+)[ \t]*;?[ \t]*$', text, re.M)
    names = re.findall(r"^[ \t]*versionName\s*=[ \t]*(['\"])([^'\"\n]+)\1[ \t]*;?[ \t]*$", text, re.M)
    declarations = re.findall(r'\bversion(?:Code|Name)\s*=', lexical(text, True))
    if len(code) != 1 or len(names) != 1 or len(declarations) != 2:
        return None
    quote, name = names[0]
    if '\\' in name or (quote == '"' and '$' in name):
        return None
    return int(code[0]), name


def check_version(old, new, guru):
    before, after = version(old), version(new)
    if not before or not after:
        return item('版本', '待确认', ['版本声明不是唯一静态常量'])
    detail = [f'基线：{before[1]} / {before[0]}；目标：{after[1]} / {after[0]}']
    if after[0] <= before[0] or after[1] == before[1]:
        return item('版本', '异常', detail)
    if not re.search(r'versionCode\s+rootProject\.ext\.versionCode', lexical(guru, True)) or not re.search(r'versionName\s+rootProject\.ext\.versionName', lexical(guru, True)):
        return item('版本', '待确认', detail + ['主模块版本引用结构需人工核对'])
    return item('版本', '通过', detail)


def check_auth(guru, auth):
    code = lexical(guru)
    plain = lexical(guru, True)
    applied = next((m for m in re.finditer(r'apply\s+from\s*:.*serverauth\.gradle', code) if plain[m.start():m.start()+5] == 'apply'), None)
    linked = re.search(r'preBuild\s*\.\s*dependsOn\s*(?:\(\s*)?uploadServerAuthTask\b', plain)
    auth_code, auth_plain = lexical(auth), lexical(auth, True)
    defined = next((m for m in re.finditer(r'''\b(?:task\s+uploadServerAuthTask\b|register\s*\(\s*['"]uploadServerAuthTask['"])''', auth_code) if auth_plain[m.start():m.start()+1].strip()), None)
    if not all((applied, linked, defined)):
        return item('鉴权挂接', '异常', ['apply、任务定义或 preBuild 挂接缺失；未执行上传'])
    # 轻量检查不能证明任意 Groovy 控制流，条件结构保守交人工。
    status = '待确认' if re.search(r'\bif\s*\(', code[max(0, linked.start()-300):linked.start()]) else '通过'
    return item('鉴权挂接', status, ['主模块构建脚本：有效 preBuild 挂接；未执行上传'])


def check_di(text, release_version, debug, util, project=None):
    rules = (project or load_project("videoguru"))["di"]
    code = lexical(text)
    plain = lexical(text, True)
    hook = re.search(r'override\s+fun\s+hookBuildUrl\b', plain)
    prefix = code[:hook.start()] if hook else code
    bad = re.findall(r'domain\s*=\s*"https://(?:' + '|'.join(re.escape(d) for d in rules['test_domains']) + r')/?"|UtCloudStorageConfig\s*\(\s*(?:isTestMode\s*=\s*)?true\s*\)', prefix)
    if bad:
        return item('DI 测试环境', '异常', ['接口配置直接开启测试域名或测试模式'])
    detail = ['仅检查源码，不检查 RemoteConfig 实际值或设备开关']
    hook_code = ''
    if hook:
        start = plain.find('{', hook.end())
        if start >= 0 and re.search(r'\bfun\b|=', plain[hook.end():start]):
            start = -1
        depth = 1
        pos = start + 1
        while start >= 0 and pos < len(plain) and depth:
            depth += (plain[pos] == '{') - (plain[pos] == '}')
            pos += 1
        if start >= 0 and depth == 0:
            hook_code = plain[start:pos]
    expected = rules['gates']
    configs = re.findall(r'config\s*=\s*UtCloudStorageConfig\s*\(([^)]*)\)', prefix)
    gates = all(s in hook_code for s in expected)
    known = rules['known_debug'] in lexical(debug, True) and rules['known_util'] in lexical(util, True)
    if not configs or any(c.strip() != 'false' for c in configs) or not gates or not known:
        return item('DI 测试环境', '待确认', detail + ['动态配置或调试门控结构需核对'])
    if release_version and re.search(re.escape(str(release_version[0])) + r'[A-Za-z]', release_version[1]):
        return item('DI 测试环境', '通过', detail + ['接口静态参数为 false；双调试门控存在', '提示：版本 Code 后紧跟字母，仍可能启用调试路径；不代表开关已经打开'])
    return item('DI 测试环境', '通过', detail + ['接口静态参数为 false；双调试门控存在；运行时状态不在本项检查范围'])


def source(path, project=None):
    p = project or load_project("videoguru")
    return any(path.startswith(f'{p["module"]}/src/{part}/') for part in p["sources"]) and path.endswith(('.kt', '.java'))


def calls(text):
    clean = lexical(text, True)
    result = []
    for match in re.finditer(r'\.\s*getOrThrow\s*\(', clean):
        line = clean.count('\n', 0, match.start()) + 1
        start = max(clean.rfind(';', 0, match.start()), clean.rfind('{', 0, match.start()), clean.rfind('}', 0, match.start())) + 1
        context = re.sub(r'\s+', '', clean[start:match.end()])[-250:]
        result.append((line, context))
    return result


def class_parents(files):
    parents = {}
    for text in files.values():
        clean = lexical(text, True)
        for m in re.finditer(r'\bclass\s+(\w+)[^{\n]*?(?:extends\s+|:\s*)([\w.]+)', clean):
            parents.setdefault(m[1], set()).add(m[2].split('.')[-1])
    return parents


def ui_class(text, parents):
    names = re.findall(r'\bclass\s+(\w+)', lexical(text, True))
    def follows(name, seen):
        if name in ('ViewModel', 'AndroidViewModel', 'Fragment', 'DialogFragment', 'BottomSheetDialogFragment'):
            return True
        if name in seen:
            return False
        return any(follows(p, seen | {name}) for p in parents.get(name, ()))
    return any(follows(n, set()) for n in names)


def implicit_calls(text):
    clean = lexical(text, True)
    result = []
    for match in re.finditer(r'\bgetOrThrow\s*\(', clean):
        prefix = clean[:match.start()].rstrip()
        if prefix.endswith('.') or re.search(r'\bfun(?:\s+<[^>]*>)?$', prefix):
            continue
        # 无限定名也可能是项目自定义函数，仅作为待确认候选。
        start = max(prefix.rfind(';'), prefix.rfind('{'), prefix.rfind('}')) + 1
        context = re.sub(r'\s+', '', clean[start:match.end()])
        result.append((clean.count('\n', 0, match.start()) + 1, context))
    return result


def check_calls(old, new):
    parents = class_parents(new)
    # 全局计数仅用于识别潜在移动；跨文件复制不自动当作存量。
    inventory = Counter(ctx for text in old.values() for _, ctx in calls(text))
    findings = []
    uncertain = []
    for path, text in new.items():
        remaining = Counter(ctx for _, ctx in calls(old.get(path, '')))
        for line, ctx in calls(text):
            if remaining[ctx]:
                remaining[ctx] -= 1
                continue
            location = f'{path}:{line}'
            if inventory[ctx]:
                uncertain.append(location + '：可能移动、重命名或复制')
            elif ui_class(text, parents):
                findings.append(location)
            else:
                uncertain.append(location + '：类继承或新增调用归属需核对')
    for path, text in new.items():
        previous = Counter(ctx for _, ctx in implicit_calls(old.get(path, '')))
        for line, ctx in implicit_calls(text):
            if previous[ctx]:
                previous[ctx] -= 1
            else:
                uncertain.append(f'{path}:{line}：无显式接收者的getOrThrow候选，需核对方法归属')
    status = '异常' if findings else '待确认' if uncertain else '通过'
    return item('新增 getOrThrow', status, findings + uncertain or ['目标快照未发现新增调用；注释和字符串已排除'])


def check_dependencies(text, trusted=False):
    if text is None:
        return item('YUV SNAPSHOT', '未执行', ['未提供依赖报告；未启动 Gradle'])
    heading = re.search(r'^googlePlayReleaseRuntimeClasspath[^\n]*$', text, re.M)
    if not heading or 'BUILD SUCCESSFUL' not in text or re.search(r'FAILED|unresolved|BUILD FAILED', text, re.I):
        return item('YUV SNAPSHOT', '待确认', ['报告变体、完整性或解析结果不满足要求'])
    section = text[heading.end():]
    section = re.split(r'\n(?:[\w]+Classpath|\(c\) -|A web-based|BUILD SUCCESSFUL)', section)[0]
    selected = set()
    unknown = False
    for line in section.splitlines():
        if 'com.yuvcraft' not in line:
            continue
        m = re.search(r'\b(com\.yuvcraft(?:\.[\w.-]+)?):([\w.-]+):', line)
        if not m or 'project ' in line:
            unknown = True
            continue
        tail = line[m.end():].strip()
        # rich constraint内可能有空格；只有箭头右侧才是最终选中版本。
        resolved = tail.rsplit(' -> ', 1)[-1].split()[0] if tail else ''
        version = resolved.rsplit(':', 1)[-1]
        if (not version or re.search(r'[{}\[\](),+]', version)
                or version.startswith('latest.') or version in ('strictly', 'prefer', 'reject')):
            unknown = True
            continue
        selected.add(resolved if ':' in resolved else f'{m[1]}:{m[2]}:{resolved}')
    bad = sorted(s for s in selected if 'SNAPSHOT' in s.upper())
    if bad:
        return item('YUV SNAPSHOT', '异常', bad)
    if not selected or unknown:
        return item('YUV SNAPSHOT', '待确认', ['没有可验证的完整 YUV 组件集合或出现未知替换'])
    return item('YUV SNAPSHOT', '通过' if trusted else '待确认',
                [f'最终选中 {len(selected)} 个不同 YUV 坐标，无 SNAPSHOT',
                 '本轮现场离线解析' if trusted else '外部报告来源需人工确认'])


def resolve_dependencies(root, timeout, project=None):
    p = project or load_project('videoguru')
    command = ['./gradlew', '--offline', '--console=plain', p['gradle']['dependency_task'], '--configuration', p['gradle']['configuration']]
    try:
        dry = subprocess.run(command + ['--dry-run'], cwd=root, capture_output=True, text=True, timeout=timeout)
        if dry.returncode:
            return dry.stdout + dry.stderr, -1
        graph_safe(dry.stdout + dry.stderr, p, p['gradle']['dependency_task'])
        process = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
        return process.stdout + process.stderr, process.returncode
    except (subprocess.TimeoutExpired, ValueError):
        return 'BUILD FAILED: dependency report timeout or unsafe task graph', -1


def baseline_static(inputs, p):
    profiles = []
    for name in p['baseline']['files']:
        path = p['baseline']['profile_dir'] + '/' + name
        data = inputs.get(path)
        profiles.append(dict(path=path, sha256=hashlib.sha256(data).hexdigest() if data else None, lines=len(data.splitlines()) if data else 0))
    return dict(name='Baseline Profile', status='待确认', evidence=['仅源码Profile盘点，未运行生成器，旧产物不代表本轮生成或冷启动性能验证'], profiles=profiles)


def run(root, base, target='HEAD', dependency=None, worktree=False, resolve=False, timeout=180, configs=False, drafts=False, draft_tests=False, purchase=False, purchase_tests=False, project=None, enforce_identity=False):
    p = project or load_project('videoguru'); root = Path(root).resolve()
    if worktree and target != 'HEAD':
        raise ValueError('--worktree不接受历史目标提交')
    if (resolve or draft_tests or purchase_tests) and not worktree:
        raise ValueError('Gradle执行必须使用--worktree，不能混用提交快照')
    if draft_tests and not drafts or purchase_tests and not purchase:
        raise ValueError('测试执行需同时启用对应静态检查')
    if resolve and dependency is not None:
        raise ValueError('不能同时导入和生成依赖报告')
    base_commit = git(root, 'rev-parse', '--verify', 'refs/tags/' + base + '^{commit}').strip()
    target_commit = git(root, 'rev-parse', '--verify', target + '^{commit}').strip()
    git(root, 'merge-base', '--is-ancestor', base_commit, target_commit)
    initial_head = git(root, 'rev-parse', 'HEAD').strip()
    contract_digest = tool_digest(p)
    if p != load_project(p['id']):
        raise ValueError('项目配置在加载后发生变化，拒绝混用')
    before = commit_inputs(root, base_commit)
    after = worktree_inputs(root) if worktree else commit_inputs(root, target_commit)
    initial_digest = digest(after)
    if enforce_identity:
        verify_identity(root, p, after)
    def text(inputs, path):
        return inputs.get(path, b'').decode('utf-8', errors='replace')
    def selected(inputs, predicate):
        return {name: value.decode('utf-8', errors='replace') for name,value in inputs.items() if predicate(name)}
    def enabled(key):
        return p['capabilities'][key] == 'supported'
    def unavailable(name, key):
        return item(name, '未执行', [f'{p["id"]}能力={p["capabilities"][key]}，尚未验证项目适配，不能套用其他项目规则'])
    old_version = text(before, p['version_path']); new_version = text(after, p['version_path'])
    checks = [check_version(old_version, new_version, text(after, p['identity']['module_build'])) if enabled('version') else unavailable('版本','version'),
              check_auth(text(after, p['identity']['module_build']), text(after, p['auth_path'])) if enabled('auth') else unavailable('鉴权挂接','auth'),
              check_di(text(after, p['di']['path']), version(new_version), text(after, p['di']['debug']), text(after, p['di']['util']), p) if enabled('di') else unavailable('DI 测试环境','di'),
              check_calls(selected(before, lambda name: source(name, p)), selected(after, lambda name: source(name, p))) if enabled('calls') else unavailable('新增 getOrThrow','calls'),
              check_dependencies(dependency) if enabled('dependencies') else unavailable('YUV SNAPSHOT','dependencies')]
    raw_dependency = draft_log = purchase_log = None
    if resolve and enabled('dependencies'):
        raw_dependency, code = resolve_dependencies(root, timeout, p)
        checks[4] = check_dependencies(raw_dependency, trusted=True) if code == 0 else item('YUV SNAPSHOT','未执行',['依赖解析失败、任务图不安全或超时；见本轮日志'])
    if purchase:
        if enabled('purchase'):
            result = purchase_check.check(selected(before, lambda n:source(n,p) or any(n.startswith(prefix) for prefix in p['purchase']['source_roots']) or n in (p['identity']['module_build'],p['identity']['settings'])), selected(after, lambda n:source(n,p) or any(n.startswith(prefix) for prefix in p['purchase']['source_roots']) or n in (p['identity']['module_build'],p['identity']['settings'])), registry_text(p,'purchase'), lexical, p)
            checks.append(result)
            if purchase_tests:
                test_result, purchase_log = purchase_check.contract_tests.run_tests(root, result['selectors'], timeout, '购买契约测试', p)
                checks.append(test_result)
        else:
            checks.append(unavailable('购买 label 契约','purchase'))
    if drafts:
        if enabled('draft'):
            result = draft_check.check(selected(before, lambda n:draft_check.source(n,p)), selected(after, lambda n:draft_check.source(n,p)), registry_text(p,'draft'), lexical, p)
            checks.append(result)
            if draft_tests:
                test_result, draft_log = draft_check.run_tests(root, result['selectors'], timeout, p); checks.append(test_result)
        else:
            checks.append(unavailable('草稿属性兼容','draft'))
    snapshots = {}
    if configs:
        if enabled('configs'):
            result, snapshots = config_check.check(lambda path:text(after,path), project=p); checks.append(result)
        else:
            checks.append(unavailable('包内 JSON','configs'))
    stable = contract_digest == tool_digest(p) and initial_head == git(root,'rev-parse','HEAD').strip() and (not worktree or initial_digest == digest(worktree_inputs(root)))
    if not stable:
        for check in checks:
            check['status']='待确认'; check['evidence'].append('源码/HEAD或工具契约并发变化，本轮已过期')
    return dict(schema_version=1, project=p['id'], base=base, base_commit=base_commit, base_identity_verified=False, base_identity_notice='显式指定的候选tag；本工具未验证真实上一发布身份，需用户确认', target=target_commit, head_at_start=initial_head, variant=p['variant'], dirty=bool(git(root,'status','--porcelain')), scope='当前工作区（含未提交源码）' if worktree else '提交端点快照（不混入未提交源码）', timestamp=datetime.now(timezone.utc).isoformat(), input_digest=initial_digest, base_digest=digest(before), tool_config_digest=contract_digest, contract_scope='使用当前外置工具与项目契约审查目标快照，不声称契约属于历史提交', stable=stable, capabilities=p['capabilities'], checks=checks, baseline_inventory=baseline_static(after,p), dependency_log=raw_dependency, draft_log=draft_log, purchase_log=purchase_log, config_snapshots=snapshots)


CHECKLIST = [
    ('channel','频道发送 AAR、mapping、版本信息',None),
    ('archive','发布存档与下一开发版本',None),
    ('tracking','新增埋点、本地日志',None),
    ('auth','鉴权挂接','鉴权挂接'),
    ('draft','草稿属性兼容','草稿属性兼容'),
    ('version','版本','版本'),
    ('di','DI 测试环境','DI 测试环境'),
    ('ai','AI 任务访问标识',None),
    ('calls','新增 getOrThrow','新增 getOrThrow'),
    ('purchase','购买 label 契约','购买 label 契约'),
    ('baseline','Baseline Profile',None),
    ('dependencies','YUV SNAPSHOT','YUV SNAPSHOT'),
    ('remote_config','RemoteConfig 默认值',None),
    ('configs','包内 JSON','包内 JSON'),
    ('apk','新旧 APK 包体','新旧 APK 包体'),
]


def finalize(report, p, apk=None, deferred=None):
    deferred = {**{int(k):v for k,v in p.get('deferred_checks',{}).items()}, **(deferred or {})}
    found = {c['name']:c for c in report['checks']}
    if apk:
        found[apk['name']] = apk
    rows = []
    for number,(key,name,lookup) in enumerate(CHECKLIST,1):
        capability=p['capabilities'][key]
        result=dict(found.get(lookup, item(name,'未执行', ['能力尚未适配' if capability=='pending' else '人工核对未完成' if capability=='manual' else '未授权或未提供本轮输入'])))
        result['evidence']=list(result['evidence'])
        result.update(number=number, capability=capability, evidence_level='脚本结果' if lookup in found else '人工待核对' if capability=='manual' else '未执行')
        if number in deferred:
            if result['status'] != '未执行':
                raise ValueError('已执行项不能改写为用户暂缓')
            result.update(evidence_level='用户暂缓', deferred_by_user=True, evidence=['用户明确暂缓：'+deferred[number]]+result['evidence'])
        if key=='baseline':
            result['inventory']=report['baseline_inventory']
        if key=='configs' and p['configs'].get('exceptions'):
            result['registered_exceptions']=p['configs']['exceptions']
            result['evidence'] += ['登记例外：'+e['reason'] for e in p['configs']['exceptions']]
        if not report['stable']:
            result['status']='待确认'; result['evidence'].append('本轮输入变化，结果过期')
        rows.append(result)
    report['checklist']=rows
    report['release_approved']=False
    report['notice']='脚本结果不等于全量发版放行；未执行、暂缓、人工项不得算通过'
    return report


def markdown(report):
    lines=['# Android 发版检查报告','',f"项目：{report['project']}；变体：{report['variant']}",f"基线：{report['base']} ({report['base_commit']})",f"目标：{report['target']}",report['base_identity_notice'],report['scope'],report['contract_scope'],f"源码摘要：{report['input_digest']}",f"工具/项目契约摘要：{report['tool_config_digest']}；稳定：{report['stable']}",report['notice'],'']
    for c in report['checklist']:
        lines += [f"## {c['number']}. {c['name']}：{c['status']}",f"能力：{c['capability']}；证据：{c['evidence_level']}"] + ['- '+e for e in c['evidence']] + ['']
    lines += ['## 契约测试（独立证据）']
    for c in report['checks']:
        if '契约测试' in c['name']:
            lines += [c['name']+'：'+c['status']] + ['- '+e for e in c['evidence']]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,help='默认当前Git根，不以脚本位置推断')
    parser.add_argument('--project',required=True,help='显式项目id，与构建指纹交叉验证')
    parser.add_argument('--base',required=True,help='必须显式上一发布tag；不猜测')
    parser.add_argument('--target',default='HEAD')
    parser.add_argument('--worktree',action='store_true')
    parser.add_argument('--output-dir',type=Path,help='仓库外全新目录')
    parser.add_argument('--format',choices=['markdown','json'],default='markdown')
    parser.add_argument('--dependency-report',type=Path)
    parser.add_argument('--resolve-dependencies',action='store_true',help='授权离线Gradle配置/缓存写入，仅依赖解析')
    parser.add_argument('--check-drafts',action='store_true',default=True,help='默认静态检查支持的草稿模型')
    parser.add_argument('--check-purchase-labels',action='store_true',default=True,help='默认静态购买契约盘点，不调用支付')
    parser.add_argument('--run-draft-tests',action='store_true')
    parser.add_argument('--run-purchase-tests',action='store_true')
    parser.add_argument('--check-configs',action='store_true',help='显式授权只读HTTPS GET，保存本轮配置快照')
    parser.add_argument('--analyze-apk',action='store_true',help='仅调用同包analyze-apk-size，不构建/安装')
    parser.add_argument('--old-apk',type=Path);parser.add_argument('--new-apk',type=Path)
    parser.add_argument('--apk-context',type=Path,help='用户确认的old/new可比性声明JSON，不据文件名猜测')
    parser.add_argument('--defer',action='append',default=[],metavar='编号=原因',help='仅登记用户明确暂缓的未执行项，不转为通过')
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    try:
        if args.timeout<=0:
            raise ValueError('超时必须大于0')
        if args.worktree and args.target!='HEAD':
            raise ValueError('--worktree不接受历史目标提交')
        if (args.run_draft_tests or args.run_purchase_tests or args.resolve_dependencies) and not args.worktree:
            raise ValueError('Gradle执行需--worktree')
        if (args.run_draft_tests or args.run_purchase_tests or args.resolve_dependencies or args.check_configs or args.analyze_apk) and not args.output_dir:
            raise ValueError('执行阶段需--output-dir保存本轮证据')
        if bool(args.old_apk)!=bool(args.new_apk):
            raise ValueError('--old-apk与--new-apk必须成对')
        if bool(args.old_apk)!=args.analyze_apk or args.apk_context and not args.analyze_apk:
            raise ValueError('APK输入与--analyze-apk必须一起显式提供')
        if args.dependency_report and args.resolve_dependencies:
            raise ValueError('不能同时导入和生成依赖报告')
        deferred={}
        for entry in args.defer:
            number,separator,reason=entry.partition('=')
            if not separator or not number.isdigit() or not 1<=int(number)<=15 or not reason.strip() or int(number) in deferred:
                raise ValueError('--defer需唯一的1..15编号=明确原因')
            deferred[int(number)]=reason.strip()
        executing = {5: args.run_draft_tests, 10: args.run_purchase_tests, 12: args.resolve_dependencies, 14: args.check_configs, 15: args.analyze_apk}
        if any(enabled and number in deferred for number, enabled in executing.items()):
            raise ValueError('不能同时执行和暂缓同一阶段')
        root=repo_root(args.repo);p=load_project(args.project);verify_identity(root,p)
        output=new_output(args.output_dir,root) if args.output_dir else None
        if output:
            output.mkdir(parents=True,exist_ok=False)
        dependency_bytes = args.dependency_report.read_bytes() if args.dependency_report else None
        report=run(root,args.base,args.target,dependency_bytes.decode('utf-8') if dependency_bytes is not None else None,args.worktree,args.resolve_dependencies,args.timeout,args.check_configs,args.check_drafts,args.run_draft_tests,args.check_purchase_labels,args.run_purchase_tests,p,True)
        apk=None
        if args.analyze_apk:
            from release_apk_check import analyze
            apk=analyze(args.old_apk,args.new_apk,output/'apk-analysis',args.timeout,json.loads(args.apk_context.read_text()) if args.apk_context else None)
        report=finalize(report,p,apk,deferred)
        # 外部APK阶段可能较长，在最终写报告前再次核对本轮源码/工具身份。
        if report['tool_config_digest']!=tool_digest(p) or report['head_at_start']!=git(root,'rev-parse','HEAD').strip() or args.worktree and report['input_digest']!=digest(worktree_inputs(root)):
            report['stable']=False
            for c in report['checks']+report['checklist']:
                c['status']='待确认';c['evidence'].append('最终复核发现输入变化，本轮过期')
        logs={k:report.pop(k) for k in ('dependency_log','draft_log','purchase_log')}
        snapshots=report.pop('config_snapshots')
        if args.dependency_report:
            report['dependency_report_provenance']={'path':str(args.dependency_report.resolve()),'sha256':hashlib.sha256(dependency_bytes).hexdigest(),'trusted':False}
        if output:
            for key,value in logs.items():
                if value is not None:(output/(key+'.txt')).write_text(value)
            for path,record in snapshots.items():
                from release_common import inside
                dst=inside(output/'configs',path);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(record['content'])
            if snapshots:
                (output/'configs/manifest.json').write_text(json.dumps({k:{n:v for n,v in r.items() if n!='content'} for k,r in snapshots.items()},ensure_ascii=False,indent=2))
            (output/'report.md').write_text(markdown(report))
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(str(output/('report.json' if args.format=='json' else 'report.md')))
        else:
            print(json.dumps(report,ensure_ascii=False,indent=2) if args.format=='json' else markdown(report))
        statuses=[c['status'] for c in report['checks']+report['checklist']]
        return 1 if '异常' in statuses else 2 if any(s in ('待确认','未执行') for s in statuses) else 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(str(error),file=sys.stderr);return 2


if __name__=='__main__':
    sys.exit(main())
