"""共享项目数据、路径边界和证据摘要；导入时不读取业务仓库。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

SKILL = Path(__file__).resolve().parents[1]


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON重复key：' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('JSON不接受非标准数值')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def digest(inputs):
    h = hashlib.sha256()
    for path, content in sorted(inputs.items()):
        h.update(path.encode()); h.update(b'\0'); h.update(content); h.update(b'\0')
    return h.hexdigest()


def inside(root, name):
    root = Path(root).resolve()
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in str(name) or not path.parts:
        raise ValueError('资源路径必须在所属目录内：' + str(name))
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('拒绝符号链接路径逃逸：' + str(name))
    return resolved


def load_project(project):
    if not re.fullmatch(r'[a-z][a-z0-9-]*', project):
        raise ValueError('项目id格式无效')
    folder = inside(SKILL / 'projects', project)
    p = strict_json((folder / 'project.json').read_text())
    if not isinstance(p, dict):
        raise ValueError('项目配置根必须是对象')
    if p.get('schema_version') != 1 or p.get('id') != project:
        raise ValueError('项目schema_version或id不匹配')
    required = {'module', 'variant', 'sources', 'modules', 'identity', 'version_path', 'auth_path', 'di', 'draft', 'purchase', 'gradle', 'baseline', 'capabilities', 'configs'}
    if not required <= p.keys():
        raise ValueError('项目配置缺少必要字段')
    sections = {
        'identity': ('settings', 'module_build', 'application_id'),
        'di': ('path', 'debug', 'util', 'test_domains', 'hook_end', 'gates', 'known_debug', 'known_util'),
        'draft': ('roots', 'registry'),
        'purchase': ('registry', 'user', 'normalization', 'source_roots'),
        'gradle': ('dependency_task', 'test_task', 'configuration', 'exclude', 'danger_patterns'),
        'baseline': ('task', 'connected_task', 'collect_task', 'test', 'files', 'generation', 'profile_dir', 'results_dir'),
        'configs': ('hosts', 'raw', 'assets', 'indexes'),
    }
    for section, keys in sections.items():
        if not isinstance(p[section], dict) or not set(keys) <= p[section].keys():
            raise ValueError('项目配置对象缺少字段：' + section)
    if not isinstance(p['capabilities'], dict):
        raise ValueError('能力配置必须为对象')
    for key in ('sources', 'modules'):
        if not isinstance(p[key], list) or not p[key] or not all(isinstance(v, str) and v for v in p[key]):
            raise ValueError('扫描范围必须为非空字符串列表：' + key)
    for section, key in [('di','test_domains'), ('di','gates'), ('draft','roots'), ('purchase','normalization'), ('purchase','source_roots'), ('gradle','exclude'), ('gradle','danger_patterns'), ('baseline','files'), ('configs','hosts')]:
        values = p[section][key]
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError('配置必须为字符串列表：' + section + '.' + key)
    for pattern in p['gradle']['danger_patterns']:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError('危险任务规则不是有效正则') from error
    config = p['configs']
    if any(not isinstance(config[key], list) for key in ('raw','assets','indexes')):
        raise ValueError('配置正文及索引清单必须为列表')
    if config['raw'] or config['assets']:
        if not config['hosts'] or len(config['indexes']) != 2:
            raise ValueError('配置正文比较需要正式来源及raw/assets两个索引')
    for row in config['raw'] + config['assets']:
        if not isinstance(row, list) or len(row) != 4 or not all(isinstance(v,str) and v.strip() for v in row):
            raise ValueError('配置正文登记必须为四项非空字符串')
    root_keys = config.get('root_version_keys', [])
    if not isinstance(root_keys, list) or not all(isinstance(k, str) and k in {r[3] for r in config['raw']} for k in root_keys):
        raise ValueError('根版本键必须来自本项目raw清单')
    for row in config['indexes']:
        if not isinstance(row, list) or len(row) != 2 or not all(isinstance(v,str) and v.strip() for v in row):
            raise ValueError('配置索引登记必须为两项非空字符串')
    if not isinstance(config.get('exceptions', []), list) or any(not isinstance(e,dict) for e in config.get('exceptions', [])):
        raise ValueError('配置例外必须为对象列表')
    if not isinstance(p.get('deferred_checks', {}), dict):
        raise ValueError('暂缓登记必须为对象')
    for name in [p['module'], *p['modules'], *p['sources'], p['variant']]:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
            raise ValueError('模块/源码集/变体标识无效')
    for name in [p['version_path'], p['auth_path'], p['identity']['settings'], p['identity']['module_build'], *[p['di'][k] for k in ('path', 'debug', 'util')], p['purchase']['user'], p['baseline']['profile_dir'], p['baseline']['results_dir']]:
        inside(Path('/placeholder'), name)
    for prefix in p['purchase']['source_roots']:
        inside(Path('/placeholder'), prefix)
    for key in ('draft', 'purchase'):
        rows = strict_json(inside(folder, p[key]['registry']).read_text())
        if not isinstance(rows, list):
            raise ValueError('契约登记必须为数组')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('契约条目必须为对象')
            for name in row.get('entries', []) + row.get('evidence', []) + ([row['policy']] if 'policy' in row else []):
                inside(Path('/placeholder'), name)
    expected_capabilities = {'version','auth','di','calls','dependencies','draft','purchase','configs','baseline','apk','tracking','ai','remote_config','channel','archive'}
    if set(p['capabilities']) != expected_capabilities:
        raise ValueError('必须登记全部15项能力')
    if p['variant'] != 'googlePlayRelease' or p['module'] not in p['modules']:
        raise ValueError('变体未适配或主模块未纳入范围')
    if any(v not in ('supported', 'manual', 'pending') for v in p['capabilities'].values()):
        raise ValueError('能力必须显式为supported/manual/pending')
    module = p['module']; g = p['gradle']; b = p['baseline']
    expected = {'dependency_task': f':{module}:dependencies', 'test_task': f':{module}:testGooglePlayDebugUnitTest', 'configuration': 'googlePlayReleaseRuntimeClasspath'}
    if any(g[k] != value for k, value in expected.items()) or g['exclude'] != [f':{module}:uploadServerAuthTask']:
        raise ValueError('Gradle入口不在固定白名单')
    if b['task'] != f':{module}:mergeGooglePlayReleaseBaselineProfile' or b['connected_task'] != ':BaselineProfile:connectedGooglePlayNonMinifiedReleaseAndroidTest' or b['collect_task'] != ':BaselineProfile:collectGooglePlayNonMinifiedReleaseBaselineProfile':
        raise ValueError('Baseline任务不在固定白名单')
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', b['test']):
        raise ValueError('生成器必须是完整类名')
    if set(b['files']) != {'baseline-prof.txt','startup-prof.txt'} or len(b['files']) != 2 or b['generation'] not in ('supported','pending'):
        raise ValueError('Profile产物或生成能力登记不完整')
    for name in b['files']:
        if name not in ('baseline-prof.txt', 'startup-prof.txt'):
            raise ValueError('未知Profile产物名')
    c = p['configs']
    for exception in c.get('exceptions', []):
        if not isinstance(exception.get('reason'),str) or not exception['reason']:
            raise ValueError('项目例外缺少原因')
        if 'path' in exception:
            inside(Path('/placeholder'),exception['path'])
            if exception.get('mode') not in ('local-only','deferred') or exception.get('status') not in ('待确认','未执行'):
                raise ValueError('项目例外不能作为通过')
    for number,reason in p.get('deferred_checks',{}).items():
        if not number.isdigit() or not 1<=int(number)<=15 or not isinstance(reason,str) or not reason.strip():
            raise ValueError('用户暂缓登记无效')
    for host in c['hosts']:
        u = urlsplit(host)
        if u.scheme != 'https' or u.netloc not in ('inshot.cc', 'aws.inshot.cc') or u.query or u.fragment or not u.path.endswith('/') or '..' in u.path.split('/'):
            raise ValueError('正式配置host不合法')
    for row in c['raw'] + c['assets']:
        if len(row) != 4:
            raise ValueError('配置清单结构错误')
        inside(Path('/placeholder'), row[1]); inside(Path('/placeholder'), row[2])
    for local, remote in c['indexes']:
        inside(Path('/placeholder'), local); inside(Path('/placeholder'), remote)
    return p


def registry_text(p, key):
    return inside(SKILL / 'projects' / p['id'], p[key]['registry']).read_text()


def tool_digest(p):
    paths = [SKILL/'SKILL.md', *sorted((SKILL/'scripts').glob('*.py')), *sorted((SKILL/'projects'/p['id']).glob('*.json'))]
    return digest({x.relative_to(SKILL).as_posix(): x.read_bytes() for x in paths if x.is_file()})


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Git读取失败：' + ' '.join(args[:2]))
    return result.stdout


def repo_root(value=None):
    return Path(git(value or Path.cwd(), 'rev-parse', '--show-toplevel').strip()).resolve()


def verify_identity(root, p, files=None):
    def read(name):
        return files.get(name, b'').decode(errors='replace') if files is not None else inside(root, name).read_text()
    def comments(text):
        return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/', lambda m: m[0] if not m[0].startswith(('//','/*')) else ''.join('\n' if c=='\n' else ' ' for c in m[0]), text)
    settings = comments(read(p['identity']['settings']))
    build = comments(read(p['identity']['module_build']))
    def real_match(pattern, text):
        # 屏蔽字符串内容但保留位置，只接受匹配起点在代码中的声明。
        masked = re.sub(r"\"\"\"[\s\S]*?\"\"\"|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", lambda m: ''.join('\n' if ch == '\n' else ' ' for ch in m[0]), text)
        return any(masked[m.start():m.end()].strip() and masked[m.start():].lstrip().startswith(text[m.start():].lstrip().split()[0]) for m in re.finditer(pattern, text, re.M))
    # 两个独立构建声明指纹，不接受字符串中的示例配置。
    if not real_match(r'^[ \t]*include\s*(?:\(\s*)?[\'"]:' + re.escape(p['module']) + r'[\'"]', settings) or not real_match(r'\bapplicationId\s*(?:=\s*)?[\'"]' + re.escape(p['identity']['application_id']) + r'[\'"]', build):
        raise ValueError('项目身份不匹配；禁止回退到其他项目配置')


def relevant(name):
    return '/src/' in name and name.endswith(('.java', '.kt', '.xml', '.json', '.txt')) or name.endswith(('.gradle', '.gradle.kts', '.toml', '.properties')) or name in ('gradlew', 'gradle/wrapper/gradle-wrapper.jar') or name.startswith('buildSrc/')


def worktree_inputs(root):
    names = git(root, '-c', 'core.quotePath=false', 'ls-files', '--cached', '--others', '--exclude-standard').splitlines()
    names += ['local.properties', 'gradle.properties']
    result = {}
    for name in sorted(set(names)):
        if relevant(name):
            path = inside(root, name)
            if path.is_file():
                result[name] = path.read_bytes()
    return result


def commit_inputs(root, commit):
    names = [n for n in git(root, '-c', 'core.quotePath=false', 'ls-tree', '-r', '--name-only', commit).splitlines() if relevant(n)]
    # 批量读取，避免每个源码文件启动一次git；端点作为不同输入保留。
    proc = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch'], input=''.join(f'{commit}:{n}\n' for n in names).encode(), capture_output=True)
    if proc.returncode:
        raise ValueError('无法读取提交快照')
    data = proc.stdout; offset = 0; result = {}
    for name in names:
        end = data.index(b'\n', offset); header = data[offset:end].split(); size = int(header[2]); offset = end + 1
        result[name] = data[offset:offset + size]; offset += size + 1
    return result


def new_output(path, repo):
    path = Path(path).resolve(); repo = Path(repo).resolve()
    if path.exists() or path.is_relative_to(repo) or path.is_relative_to(SKILL.parents[1]):
        raise ValueError('输出必须为仓库及整个插件外的全新目录，不覆盖历史结果')
    return path


def graph_safe(text, p, required=None, baseline=False):
    tasks = re.findall(r'^[ \t]*(:\S+)[ \t]', text, re.M)
    if required and required not in tasks:
        raise ValueError('任务图缺少预期任务')
    for pattern in p['gradle']['danger_patterns']:
        if pattern == 'install' and baseline:
            continue
        if any(re.search(pattern, task.rsplit(':',1)[-1], re.I) for task in tasks):
            raise ValueError('任务图包含项目登记危险任务')
    for task in tasks:
        name = task.rsplit(':', 1)[-1]
        # connected AndroidTest仅在显式Baseline阶段允许，其安装是该阶段授权的一部分。
        if re.search(r'upload|publish|copy.*baselineprofile|pixel\w*|manageddevice', name, re.I) or (not baseline and re.search(r'install|connected.*AndroidTest|generate.*BaselineProfile', name, re.I)):
            raise ValueError('任务图包含未授权或危险任务：' + task)
    return tasks
