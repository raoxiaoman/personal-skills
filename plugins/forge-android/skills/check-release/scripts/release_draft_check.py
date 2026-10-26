"""草稿字段候选增量与登记测试；不自动判断业务默认值或迁移正确性。"""
import json
from pathlib import Path
import re
import release_contract_tests as contract_tests

from release_common import load_project, strict_json, inside


def source(path, project=None):
    p = project or load_project('videoguru')
    return any(path.startswith(m + '/src/') for m in p['modules']) and '/src/' in path and path.split('/src/', 1)[1].split('/')[0] in p['sources'] and path.endswith(('.java', '.kt'))


def registry(text):
    data = strict_json(text)
    if not isinstance(data, list):
        raise ValueError('草稿测试登记必须是列表')
    for row in data:
        if not isinstance(row, dict):
            raise ValueError('草稿契约条目必须是对象')
        if not all(isinstance(row.get(k), list) for k in ('models', 'tests', 'evidence')):
            raise ValueError('草稿测试登记结构不符')
        if not row['models'] or not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z_]\w*', v) for v in row['models']):
            raise ValueError('模型必须为非空简单类名列表')
        if not all(isinstance(v, str) and v.strip() for v in row['evidence']):
            raise ValueError('依据路径必须为非空字符串')
        for path in row['evidence']:
            inside(Path('/placeholder'), path)
        if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', v) for v in row['tests']):
            raise ValueError('测试选择器必须为完整类名，不接受命令或通配符')
    return data


def inventory(files, lexical, project=None):
    classes = {}
    uncertain = []
    for path, text in files.items():
        if not source(path, project):
            continue
        clean = lexical(text)
        masked = re.sub('"""[\\s\\S]*?"""|"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'', lambda m: ' ' * len(m[0]), clean)
        headers = [h for h in re.finditer(r'\b(?:class|interface)\s+(\w+)([^{}]*)\{', clean) if masked[:h.start()].count('{') == masked[:h.start()].count('}')]
        for h in headers:
            name = h[1]
            parents = set()
            for group in re.findall(r'\b(?:extends|implements)\s+(.+?)(?=\b(?:extends|implements)\b|$)', h[2]):
                parents.update(p.strip().split('<', 1)[0].split('.')[-1] for p in group.split(','))
            if path.endswith('.kt'):
                # 构造函数参数里的冒号不属于继承；先跳过成对括号，再取顶层冒号。
                depth = 0
                for offset, char in enumerate(h[2]):
                    if char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                    elif char == ':' and depth == 0:
                        parents.update(p.split('.')[-1] for p in re.findall(r'(?:^|,)\s*([\w.]+)', h[2][offset + 1:]))
                        break
            if name in classes:
                uncertain.append('同名模型无法可靠归属：' + name)
            classes[name] = dict(path=path, parents=parents, text=clean, header=h, multiple=len(headers) != 1)
    return classes, uncertain


def fields(model):
    text, h = model['text'], model['header']
    # 仅处理类体第一层分号声明；保留字符串以读取SerializedName。
    depth, start, result, uncertain = 1, h.end(), {}, []
    parens = 0
    masked = re.sub('"""[\\s\\S]*?"""|"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'', lambda m: ' ' * len(m[0]), text)
    i = start
    while i < len(text) and depth:
        c = masked[i]
        if c == '(':
            parens += 1
        elif c == ')':
            parens -= 1
        elif c == '{' and parens == 0:
            if depth == 1 and '=' in text[start:i]:
                uncertain.append('带块初始化的字段需人工核对')
            depth += 1
        elif c == '}' and parens == 0:
            depth -= 1
            if depth == 1:
                start = i + 1
        elif c == ';' and depth == 1:
            value = text[start:i].strip()
            start = i + 1
            annotations = re.findall(r'@(?:[\w]+\.)*SerializedName\s*\(([^)]*)\)', value)
            plain = re.sub(r'@[\w.]+(?:\s*\([^)]*\))?', '', value).strip()
            match = re.fullmatch(r'((?:(?:public|protected|private|static|transient|final|volatile)\s+)*)((?:[\w.]+)(?:\s*<[^;]+>)?(?:\[\])?)\s+(\w+)\s*(?:=\s*([\s\S]+))?', plain)
            if match:
                modifiers, typ, name, default = match.groups()
                if not set(modifiers.split()) & {'static', 'transient', 'final'}:
                    result[name] = dict(type=re.sub(r'\s+', '', typ), default=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\s+', lambda m: '' if m[0].isspace() else m[0], default or ''), json_name=annotations or [name], line=text.count('\n', 0, i) + 1)
            elif value and not '(' in plain:
                uncertain.append('未识别类体声明')
        i += 1
    return result, uncertain


def check(old, new, registration, lexical, project=None):
    project = project or load_project("videoguru")
    entries = registry(registration)
    oi, ou = inventory(old, lexical, project)
    ni, nu = inventory(new, lexical, project)
    explicit = {m for row in entries for m in row['models']}
    def selected(name, index, seen=None):
        seen = seen or set()
        if name in project["draft"]["roots"] or name in explicit:
            return True
        if name in seen or name not in index:
            return False
        return any(selected(p, index, seen | {name}) for p in index[name]['parents'])
    changes, warnings = [], []
    warnings += [w for w in ou + nu if any(selected(w.split('：')[-1], index) for index in (oi, ni))]
    for name in sorted(set(oi) | set(ni)):
        if not (selected(name, oi) or selected(name, ni)):
            continue
        before, after = oi.get(name), ni.get(name)
        if before and after and before['text'] == after['text']:
            continue
        if any(m and (m['path'].endswith('.kt') or m['multiple']) for m in (before, after)):
            warnings.append(name + '：Kotlin或多类文件需人工语义核对')
            continue
        a, aw = fields(before) if before else ({}, [])
        b, bw = fields(after) if after else ({}, [])
        warnings += [name + '：' + w for w in aw + bw]
        for field in sorted(set(a) | set(b)):
            av, bv = a.get(field), b.get(field)
            if av and bv and {k: v for k, v in av.items() if k != 'line'} == {k: v for k, v in bv.items() if k != 'line'}:
                continue
            related = [r for r in entries if name in r['models']]
            changes.append(dict(model=name, field=field, kind='新增' if av is None else '删除' if bv is None else '契约变化', path=(after or before)['path'], before=av, after=bv, tests=sorted({t for r in related for t in r['tests']}), evidence=sorted({e for r in related for e in r['evidence']})))
    evidence = ['候选字段盘点，不推断默认值正确或无需迁移；非完整Java/Kotlin语义解析。']
    for c in changes:
        evidence.append(f"{c['path']}:{(c['after'] or c['before'])['line']} {c['model']}.{c['field']}：{c['kind']}；测试：{', '.join(c['tests']) or '未登记'}；持久化/Gson/迁移依据：{', '.join(c['evidence']) or '未登记'}")
    evidence += sorted(set(warnings))
    if not changes and not warnings:
        evidence.append('已识别模型范围内未发现字段契约变化；不代表完整草稿回归通过。')
    return dict(name='草稿属性兼容', status='待确认' if changes or warnings else '不涉及', evidence=evidence, changes=changes, selectors=sorted({t for c in changes for t in c['tests']}))


def run_tests(root, selectors, timeout, project=None):
    return contract_tests.run_tests(root, selectors, timeout, '草稿契约测试', project)
