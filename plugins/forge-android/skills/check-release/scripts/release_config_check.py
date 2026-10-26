"""包内 JSON 的只读比较，不调用同步脚本的写回入口。"""
from datetime import datetime, timezone
import hashlib
import json
import gzip
import io
import http.client
import zlib
import urllib.request
from urllib.parse import urlparse
from release_common import load_project


LIMIT = 16 * 1024 * 1024


def parse(text):
    def pairs(entries):
        value = {}
        for key, item in entries:
            if key in value:
                raise ValueError('重复 JSON key')
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('非标准 JSON 数值')
    return json.loads(text.lstrip('﻿'), object_pairs_hook=pairs, parse_constant=invalid)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def valid_url(url, project=None):
    p = project or load_project('videoguru')
    # 仅允许已登记的完整对象路径，不能利用前缀读取其他功能配置。
    config = p['configs']
    paths = {e[2] for e in config['raw'] + config['assets']} | {e[1] for e in config['indexes']}
    return url in {host + path for host in config['hosts'] for path in paths}


def fetch(path, project=None):
    p = project or load_project('videoguru')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, url):
            if url not in {host + path for host in p['configs']['hosts']}:
                raise ValueError('拒绝跳转到未登记的正式配置地址')
            return super().redirect_request(request, fp, code, message, headers, url)
    failures = []
    for host in p['configs']['hosts']:
        url = host + path
        if not valid_url(url, p):
            raise ValueError('配置路径未登记')
        try:
            with urllib.request.build_opener(Redirect()).open(url, timeout=20) as response:
                if response.geturl() not in {host + path for host in p['configs']['hosts']}:
                    raise ValueError('响应来源不在白名单')
                content = response.read(LIMIT + 1)
                if len(content) > LIMIT:
                    raise ValueError('响应超过大小限制')
                if response.headers.get('Content-Encoding', '').lower() == 'gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                        content = stream.read(LIMIT + 1)
                    if len(content) > LIMIT:
                        raise ValueError('解压响应超过大小限制')
                text = content.decode('utf-8-sig'); parse(text)
                return dict(content=text, source=response.geturl(), timestamp=datetime.now(timezone.utc).isoformat(), failures=failures)
        except (ValueError, OSError, UnicodeError, EOFError, zlib.error, http.client.HTTPException) as error:
            failures.append(dict(source=url, error=type(error).__name__, status=getattr(error, 'code', None)))
    raise ValueError('两个正式来源均读取失败：' + path + '；' + '、'.join(f"{urlparse(f['source']).netloc}: {f['error']}" + (f" HTTP {f['status']}" if f['status'] else '') for f in failures))


def number(value):
    # 现有更新与埋点过滤配置使用数字字符串版本，保留正文类型比较。
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('版本不是非负整数')
    return value


def body_version(data, key, asset=False, root_version_keys=()):
    if not isinstance(data, dict):
        raise ValueError('配置根不是对象')
    if asset or key in ('update2', 'updateMenu', 'remote') or key in root_version_keys:
        return number(data['version'])
    values = data[key]
    if not isinstance(values, list) or not values or not isinstance(values[0], dict):
        raise ValueError('版本容器结构不符')
    return number(values[0]['version'])


def compare(local_text, online_text, key, asset, local_index, online_index, root_version_keys=()):
    local, online = parse(local_text), parse(online_text)
    lv, ov = body_version(local, key, asset, root_version_keys), body_version(online, key, asset, root_version_keys)
    messages = []
    for label, index, value in [('本地', local_index, lv), ('云端', online_index, ov)]:
        if key not in index:
            messages.append(label + '索引缺项')
        elif number(index[key]) != value:
            messages.append(label + '索引与正文版本不一致')
    equal = canonical(local) == canonical(online)
    category = '内容一致' if equal else '云端较新' if ov > lv else '本地较新' if lv > ov else '同版本内容漂移'
    return dict(local_version=lv, online_version=ov, category=category, index_issues=messages,
                local_digest=sha(canonical(local)), online_digest=sha(canonical(online)),
                status='通过' if equal and not messages else '待确认')


def check(read, fetcher=None, project=None):
    project = project or load_project("videoguru")
    config = project["configs"]
    raw, assets, indexes = config["raw"], config["assets"], config["indexes"]
    fetcher = fetcher or (lambda path: fetch(path, project))
    snapshots, results, errors = {}, [], []
    local_indexes, online_indexes = [], []
    def download(path):
        record = fetcher(path)
        snapshots[path] = record
        return record['content']
    for local_path, remote in indexes:
        try:
            local = parse(read(local_path)); online = parse(download(remote))
            if remote == 'VersionInfo.json':
                local, online = local['version'], online['version']
            if not isinstance(local, dict) or not isinstance(online, dict):
                raise ValueError('索引不是对象')
            local_indexes.append(local); online_indexes.append(online)
        except (ValueError, KeyError, TypeError, OSError):
            local_indexes.append({}); online_indexes.append({})
            errors.append(remote + '：索引读取或解析失败')
    for asset, entries in [(False, raw), (True, assets)]:
        for name, path, remote, key in entries:
            local_issues = []
            try:
                local_v = body_version(parse(read(path)), key, asset, config.get('root_version_keys', ()))
                index = local_indexes[int(asset)]
                if key not in index:
                    local_issues.append('本地索引缺项')
                elif number(index[key]) != local_v:
                    local_issues.append('本地索引与正文版本不一致')
            except (ValueError, KeyError, TypeError, OSError):
                local_issues.append('本地结构或版本校验失败')
            exception = next((e for e in config.get('exceptions', []) if e.get('path') == path), None)
            if exception:
                result = dict(name=name, path=path, status='待确认', category='用户暂缓' if exception['mode']=='deferred' else '本地维护；云端正文未验证', index_issues=local_issues, exception=exception, remote_executed=False)
                results.append(result)
                continue
            try:
                result = compare(read(path), download(remote), key, asset, local_indexes[int(asset)], online_indexes[int(asset)], config.get('root_version_keys', ()))
                result.update(name=name, path=path, source=snapshots[remote]['source'])
            except (ValueError, KeyError, TypeError, OSError) as error:
                reason = str(error) if isinstance(error, ValueError) and str(error).startswith('两个正式来源') else '结构或版本校验失败：' + type(error).__name__
                result = dict(name=name, path=path, status='待确认', category=reason, index_issues=local_issues)
            results.append(result)
    for _, remote in indexes:
        try:
            previous = snapshots.get(remote)
            current = fetcher(remote)
            if previous is None or canonical(parse(previous['content'])) != canonical(parse(current['content'])) or previous['source'] != current['source']:
                errors.append(remote + '：采集前后索引或来源变化')
        except (ValueError, KeyError, TypeError, OSError):
            errors.append(remote + '：采集后复核失败')
    sources = {urlparse(r['source']).netloc for r in snapshots.values()}
    if len(sources) > 1:
        errors.append('本轮使用多个云端来源，需确认镜像一致性')
    errors += [e['reason'] for e in config.get('exceptions', [])]
    evidence = [f"{r['path']}：{r['category']}" + ('；' + '、'.join(r.get('index_issues', [])) if r.get('index_issues') else '') for r in results] + errors
    status = '通过' if results and not errors and all(r['status'] == '通过' for r in results) else '待确认'
    return dict(name='包内 JSON', status=status, evidence=evidence, phase='配置差异', details=results), snapshots
