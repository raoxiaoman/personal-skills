"""调用现有APK技能；只维护参数、摘要和报告来源，不复制分析实现。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from release_common import SKILL, digest


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def analyze(old, new, output, timeout=180, context=None):
    if not old or not new:
        raise ValueError('必须成对提供--old-apk和--new-apk')
    if context is not None:
        required = {'channel','abi','package_kind','build_type','release_identity'}
        if (not isinstance(context, dict) or set(context) != {'old','new'}
                or any(not isinstance(context[k], dict) or not required <= context[k].keys()
                       or not all(isinstance(context[k][f], str) and context[k][f].strip() for f in required)
                       for k in ('old','new'))):
            raise ValueError('APK可比性声明需完整old/new渠道、ABI、包类型、构建类型、发布身份')
    old, new, output = Path(old).resolve(), Path(new).resolve(), Path(output).resolve()
    if not old.is_file() or not new.is_file() or output.exists():
        raise ValueError('APK缺失或分析目录已存在')
    tool = SKILL.parent/'analyze-apk-size/scripts/apk_size_analysis.py'
    if not tool.is_file():
        return dict(name='新旧 APK 包体', status='未执行', evidence=['同包analyze-apk-size技能缺失，不另造分析器'])
    before = {'old': sha(old), 'new': sha(new), 'tool': sha(tool)}
    command = [sys.executable, '-I', str(tool), str(old), str(new), '--output-dir', str(output)]
    try:
        process = subprocess.run(command, cwd=SKILL, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as error:
        return dict(name='新旧 APK 包体', status='未执行', evidence=['APK分析未完成：' + type(error).__name__])
    result = dict(name='新旧 APK 包体', status='待确认', evidence=[], tool=str(tool), hashes=before, returncode=process.returncode, comparability='未知，须核对渠道、ABI、split/universal、debug/release及实际发布身份', budget='未设置用户预算阈值，不判断增长合理性')
    try:
        if before != {'old': sha(old), 'new': sha(new), 'tool': sha(tool)}:
            result.update(status='未执行', evidence=['APK或分析工具并发变化，结果过期']); return result
        if process.returncode not in (0, 2) or not all((output/n).is_file() for n in ('report.json','report.md')):
            result.update(status='未执行', evidence=['APK分析执行错误或缺少报告']); return result
        raw = json.loads((output/'report.json').read_text())
        if not isinstance(raw, dict) or raw.get('schema_version') != 1:
            raise ValueError('分析报告schema无效')
        for key, path in [('old', old), ('new', new)]:
            entry = raw.get(key)
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or Path(entry['path']).resolve() != path:
                raise ValueError('分析报告输入来源不匹配')
            size = entry.get('size_bytes')
            if type(size) is not int or size < 0 or size != path.stat().st_size:
                raise ValueError('报告APK大小与输入不一致')
        for key in ('delta_bytes', 'zip_overhead_delta_bytes', 'reconciled_delta_bytes'):
            if type(raw.get(key)) is not int:
                raise ValueError('报告对账字段缺失或类型不符')
        if raw['delta_bytes'] != raw['new']['size_bytes'] - raw['old']['size_bytes'] or raw['reconciled_delta_bytes'] != raw['delta_bytes']:
            raise ValueError('报告增量无法对账')
        if 'delta_percent' not in raw or not isinstance(raw.get('categories'), list) or not isinstance(raw.get('files'), list):
            raise ValueError('报告汇总字段缺失或类型不符')
    except (ValueError, OSError, TypeError) as error:
        result.update(status='未执行', evidence=['APK输入或报告无法校验：' + (str(error) if isinstance(error, ValueError) else type(error).__name__)])
        return result
    result.update(measurement='完整' if process.returncode == 0 else 'ZIP可用，DEX归因不完整', markdown=str(output/'report.md'), json=str(output/'report.json'), summary={k:raw[k] for k in ('delta_bytes','delta_percent','zip_overhead_delta_bytes','reconciled_delta_bytes','categories')}, old_size_bytes=raw['old']['size_bytes'], new_size_bytes=raw['new']['size_bytes'], major_files=raw['files'][:20])
    result['report_digest'] = digest({n:(output/n).read_bytes() for n in ('report.json','report.md')})
    if context is not None:
        required = {'channel','abi','package_kind','build_type','release_identity'}
        fields = required - {'release_identity'}
        same = all(context['old'][f] == context['new'][f] for f in fields)
        result['comparability'] = '用户声明口径一致，仍须对照APK元数据' if same else '用户声明口径不一致，不作等口径归因'
        result['context'] = context
    result['evidence'] = [result['measurement'], result['comparability'], result['budget'], '包归组为未压缩DEX结构，不是SDK压缩贡献精确分摊；mapping未经最终R8标记精确匹配不用于归因', result['markdown']]
    # 测量完整和增长合理是两个独立结论，不能靠退出0放行。
    return result
