"""购买label契约及调用增量盘点，不凭文本存在证明动态支付链路。"""
from collections import Counter
import json
import re
import release_contract_tests as contract_tests

from release_common import load_project, strict_json

NAMES = ('launchBillingFlow', 'getObfuscatedProfileId', 'setObfuscatedProfileId')


def registry(text):
    rows = strict_json(text)
    if not isinstance(rows, list):
        raise ValueError('购买契约登记必须为列表')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'].strip() or row['id'] in ids:
            raise ValueError('购买契约id缺失或重复')
        ids.add(row['id'])
        for key in ('labels', 'entries', 'tests'):
            if not isinstance(row.get(key), list) or not all(isinstance(x, str) for x in row[key]):
                raise ValueError('购买契约结构不符')
        if not isinstance(row.get('constants'), dict) or not isinstance(row.get('policy'), str):
            raise ValueError('购买契约常量或policy不符')
        if not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z_]\w*', k) and isinstance(v, str) and v.strip() for k, v in row['constants'].items()):
            raise ValueError('标签常量必须为标识符与非空字符串映射')
        if any(not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', t) for t in row['tests']):
            raise ValueError('测试必须为完整类名')
        if any(p.startswith('/') or '..' in p.split('/') for p in row['entries'] + [row['policy']]):
            raise ValueError('购买契约路径必须在仓库内')
    return rows


def calls(text, lexical):
    clean = lexical(text)
    masked = lexical(text, True)
    result = []
    for m in re.finditer(r'\b(' + '|'.join(NAMES) + r')\s*\(', masked):
        # 排除方法声明；复杂Java声明仍需人工复核。
        prefix = masked[max(0, m.start()-30):m.start()]
        if re.search(r'\bfun\s+$', prefix):
            continue
        depth, start, args = 1, m.end(), []
        i = start
        while i < len(masked) and depth:
            c = masked[i]
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif c == ',' and depth == 1:
                args.append(clean[start:i].strip()); start = i + 1
            i += 1
        if depth:
            result.append(dict(name=m[1], line=clean.count('\n', 0, m.start()) + 1, args=[], uncertain=True, signature='unclosed'))
            continue
        last = clean[start:i-1].strip()
        if last:
            args.append(last)
        result.append(dict(name=m[1], line=clean.count('\n', 0, m.start()) + 1, args=args, uncertain=False, signature=re.sub('"""[\\s\\S]*?"""|"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'|\\s+', lambda token: '' if token[0].isspace() else token[0], clean[m.start():i])))
    return result


def check(old, new, registration, lexical, project=None):
    project = project or load_project("videoguru")
    user_path = project["purchase"]["user"]
    rows = registry(registration)
    evidence = ['只核对契约文本与调用候选；不输出用户ID/token/profileId实例，不证明运行时传递或中台接收。']
    issues, uncertainties, changes = [], [], []
    entries = {p for row in rows for p in row['entries']}
    user = lexical(new.get(user_path, ''))
    normalization = all(v in user for v in project['purchase']['normalization'])
    if not normalization:
        uncertainties.append('profileId规范化实现缺失或已变化；碰撞计算仅按登记的去下划线/16字符口径，需复核')
    for row in rows:
        text = lexical(new.get(row['policy'], ''))
        if not text:
            uncertainties.append(row['id'] + '：登记policy缺失')
        values = re.findall(r'"((?:\\.|[^"\\])*)"', text)
        for constant, expected in row['constants'].items():
            m = re.search(r'\b' + re.escape(constant) + r'\s*=\s*"([^"\n]*)"', text)
            if not m or m[1] != expected:
                issues.append(row['id'] + '：常量 ' + constant + ' 与已确认契约不符')
        for label in row['labels']:
            if not label:
                issues.append(row['id'] + '：登记label为空')
            elif label not in values:
                uncertainties.append(row['id'] + '：预期label未在policy中定位：' + label)
        variants = [label.replace('_', '')[:16] for label in row['labels']]
        if any(n > 1 for n in Counter(variants).values()):
            issues.append(row['id'] + '：去下划线/截断后组间label碰撞')
        missing = [p for p in row['entries'] if p not in new]
        if missing:
            uncertainties.append(row['id'] + '：登记入口缺失')
        evidence.append(row['id'] + '：预期label=' + ', '.join(row['labels']) + '；入口=' + ', '.join(row['entries']) + '；测试=' + (', '.join(row['tests']) or '无登记测试，覆盖缺口'))
    for path in sorted(set(old) | set(new)):
        if not path.endswith(('.java', '.kt')):
            continue
        before, after = calls(old.get(path, ''), lexical), calls(new.get(path, ''), lexical)
        old_counts = Counter(c['signature'] for c in before)
        new_counts = Counter(c['signature'] for c in after)
        for call in after:
            if old_counts[call['signature']]:
                old_counts[call['signature']] -= 1
                continue
            changes.append(dict(path=path, line=call['line'], name=call['name'], kind='新增或修改', registered=path in entries))
            if call['uncertain']:
                uncertainties.append(f'{path}:{call["line"]}：参数无法解析')
            if path not in entries and path != user_path:
                uncertainties.append(f'{path}:{call["line"]}：未登记调用/封装，需要人工关联label契约')
            args = call['args']
            if call['name'] in ('getObfuscatedProfileId', 'setObfuscatedProfileId'):
                if not args:
                    evidence.append(f'{path}:{call["line"]}：无参数profileId调用，需沿UserManager默认SubscribeProPolicy.getLabel核对，不视为漏传')
                elif args[0] in ('null', '""'):
                    issues.append(f'{path}:{call["line"]}：profile label明确为空')
            if call['name'] == 'launchBillingFlow':
                # 只解析明确命名参数，不猜不同重载的位置参数。
                named = [a for a in args if re.match(r'(?:obfuscatedProfileId|profileId|accountId)\s*=', a)]
                for value in named:
                    if re.search(r'=\s*(?:null|"")$', value):
                        issues.append(f'{path}:{call["line"]}：购买profile/account命名参数明确为空')
                uncertainties.append(f'{path}:{call["line"]}：Billing动态参数/重载及回调链仍需人工核对')
        for call in before:
            if new_counts[call['signature']]:
                new_counts[call['signature']] -= 1
            else:
                changes.append(dict(path=path, line=call['line'], name=call['name'], kind='删除或替换', registered=path in entries))
    for row in rows:
        for path in [row['policy']] + row['entries']:
            if old.get(path) != new.get(path):
                evidence.append(row['id'] + '：相关文件变化需核对分组、会话保存及透传：' + path)
    if old.get(user_path) != new.get(user_path):
        uncertainties.append('UserManager构造/默认label来源文件变化，须复核')
    evidence += [f"{c['path']}:{c['line']} {c['name']}：{c['kind']}" for c in changes]
    evidence += issues + uncertainties
    for path in (project['identity']['module_build'], project['identity']['settings']):
        if old.get(path) != new.get(path):
            evidence.append(path + '：依赖构建输入变化，须另行解析支付最终版本；不凭缓存源码通过')
    evidence.append('accountId运行时非空性、SDK条件下发与服务端接收未验证；未登记实验不能自动通过。')
    return dict(name='购买 label 契约', status='异常' if issues else '待确认', evidence=evidence, changes=changes, selectors=sorted({t for r in rows for t in r['tests']}))
