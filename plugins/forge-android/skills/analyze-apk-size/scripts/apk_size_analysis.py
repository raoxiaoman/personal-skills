#!/usr/bin/env python3
"""只读比较两个 APK；仅依赖 Python 标准库，以 python3 -I 调用。"""
import argparse
import collections
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

MAX_DEX = 256 * 1024 * 1024
MAX_METADATA = 1024 * 1024
PREFIXES = {
    'com/google/android/gms/internal/ads/': 'Google Ads',
    'com/google/android/gms/ads/': 'Google Ads',
    'com/applovin/shadow/': 'AppLovin shadow',
    'com/applovin/': 'AppLovin other',
    'com/unity3d/': 'Unity',
    'gatewayprotocol/': 'gatewayprotocol（需核对依赖归属）',
    'com/bytedance/': 'ByteDance',
    'com/tiktok/': 'TikTok',
    'com/android/billingclient/': 'Billing',
    'com/google/': 'Google other',
    'com/ironsource/': 'IronSource',
    'com/vungle/': 'Vungle',
    'com/inmobi/': 'InMobi',
    'androidx/': 'AndroidX',
    'kotlin/': 'Kotlin',
    'kotlinx/': 'KotlinX',
}
DEX_NAME = re.compile(r'^classes(?:[2-9]|[1-9][0-9]+)?\.dex$')


class AnalysisError(ValueError):
    pass


def package_group(descriptor, prefixes):
    name = descriptor[1:-1] if descriptor.startswith('L') else descriptor
    for prefix in sorted(prefixes, key=len, reverse=True):
        if name.startswith(prefix):
            return prefixes[prefix]
    parts = name.split('/')
    if len(parts) < 3:
        return 'Other / obfuscated'
    return 'prefix:' + '/'.join(parts[:3])


class Dex:
    def __init__(self, data):
        self.data = data
        if len(data) < 112 or data[:4] != b'dex\n' or data[7] != 0:
            raise AnalysisError('不是标准 DEX 或头部截断')
        if data[4:7] not in (b'035', b'037', b'038', b'039', b'040'):
            raise AnalysisError('不支持的 DEX 版本（仅支持 035/037/038/039/040）')
        if self.u32(32) != len(data) or self.u32(36) != 112:
            raise AnalysisError('DEX 文件长度或头部长度不一致')
        if self.u32(40) != 0x12345678:
            raise AnalysisError('不支持的 DEX 字节序')
        for at, width in ((56, 4), (64, 4), (72, 12), (80, 8), (88, 8), (96, 32)):
            self.table(at, width)

    def check(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise AnalysisError('DEX 结构越界或截断')

    def u32(self, offset):
        self.check(offset, 4)
        return struct.unpack_from('<I', self.data, offset)[0]

    def u16(self, offset):
        self.check(offset, 2)
        return struct.unpack_from('<H', self.data, offset)[0]

    def table(self, at, width):
        count, offset = self.u32(at), self.u32(at + 4)
        if count and offset < 112:
            raise AnalysisError('DEX 表偏移落在头部')
        self.check(offset, count * width)
        return count, offset

    def leb(self, offset, signed=False):
        value = 0
        for index in range(5):
            self.check(offset, 1)
            byte = self.data[offset]
            offset += 1
            value |= (byte & 127) << (index * 7)
            if not byte & 128:
                if signed and byte & 64:
                    value -= 1 << ((index + 1) * 7)
                if signed:
                    if not -(1 << 31) <= value < (1 << 31):
                        raise AnalysisError('SLEB128 超出 32 位')
                elif value >= 1 << 32:
                    raise AnalysisError('ULEB128 超出 32 位')
                return value, offset
        raise AnalysisError('LEB128 过长')

    def code_size(self, offset):
        if offset < 112 or offset % 4:
            raise AnalysisError('非法 code_item 偏移')
        self.check(offset, 16)
        tries = self.u16(offset + 6)
        instructions = self.u32(offset + 12)
        end = offset + 16 + instructions * 2
        self.check(offset, end - offset)
        if tries:
            end += (instructions % 2) * 2
            self.check(end, tries * 8)
            tries_start = end
            end += tries * 8
            handlers_start = end
            count, end = self.leb(end)
            if count > len(self.data) - end:
                raise AnalysisError('异常处理数量越界')
            offsets = set()
            type_count = self.u32(64)
            for _ in range(count):
                offsets.add(end - handlers_start)
                size, end = self.leb(end, signed=True)
                if abs(size) > (len(self.data) - end) // 2:
                    raise AnalysisError('异常处理结构过长')
                for _ in range(abs(size)):
                    type_id, end = self.leb(end)
                    address, end = self.leb(end)
                    if type_id >= type_count or address >= instructions:
                        raise AnalysisError('异常处理类型或指令地址越界')
                if size <= 0:
                    address, end = self.leb(end)
                    if address >= instructions:
                        raise AnalysisError('catch-all 地址越界')
            for i in range(tries):
                at = tries_start + i * 8
                start = self.u32(at)
                length = self.u16(at + 4)
                if start + length > instructions or self.u16(at + 6) not in offsets:
                    raise AnalysisError('try_item 地址或 handler 偏移非法')
        return end - offset

    def analyze(self, prefixes):
        strings = []
        string_cache = {}
        string_bytes = 0
        count, offset = self.table(56, 4)
        for i in range(count):
            at = self.u32(offset + i * 4)
            if at < 112:
                raise AnalysisError('非法字符串偏移')
            if at not in string_cache:
                start = at
                _, at = self.leb(at)
                end = self.data.find(b'\0', at, at + MAX_METADATA + 1)
                if end < 0:
                    raise AnalysisError('DEX 字符串未终止或超过 1 MiB 安全限制')
                string_bytes += end - at
                if string_bytes > 2 * len(self.data):
                    raise AnalysisError('DEX 字符串存在过量重叠，超过解析安全预算')
                # 包描述符与 R8 标记为 ASCII；其余 MUTF-8 不用于语义归因。
                string_cache[start] = self.data[at:end].decode('utf-8', 'replace')
                at = start
            strings.append(string_cache[at])
        count, offset = self.table(64, 4)
        types = []
        for i in range(count):
            index = self.u32(offset + i * 4)
            if index >= len(strings):
                raise AnalysisError('类型字符串索引越界')
            types.append(strings[index])
        stats = collections.defaultdict(lambda: {'classes': 0, 'methods': 0, 'bytes': 0})
        codes = {}
        class_data_seen = set()
        classes_seen = set()
        count, offset = self.table(96, 32)
        for i in range(count):
            at = offset + i * 32
            type_id = self.u32(at)
            if type_id >= len(types) or type_id in classes_seen:
                raise AnalysisError('类索引越界或重复')
            classes_seen.add(type_id)
            group = package_group(types[type_id], prefixes)
            stats[group]['classes'] += 1
            stats[group]['bytes'] += 32
            cd = self.u32(at + 24)
            if not cd:
                continue
            if cd < 112 or cd in class_data_seen:
                raise AnalysisError('class_data 偏移非法或重复')
            class_data_seen.add(cd)
            start = cd
            counts = []
            for _ in range(4):
                n, cd = self.leb(cd)
                counts.append(n)
            if sum(counts) > len(self.data) - cd:
                raise AnalysisError('类字段或方法数量越界')
            for n in counts[:2]:
                index = 0
                for j in range(n):
                    diff, cd = self.leb(cd)
                    index += diff
                    _, cd = self.leb(cd)
                    if index >= self.u32(80) or (j and not diff):
                        raise AnalysisError('字段索引越界或重复')
                    stats[group]['bytes'] += 8
            for n in counts[2:]:
                index = 0
                for j in range(n):
                    diff, cd = self.leb(cd)
                    index += diff
                    _, cd = self.leb(cd)
                    code, cd = self.leb(cd)
                    if index >= self.u32(88) or (j and not diff):
                        raise AnalysisError('方法索引越界或重复')
                    stats[group]['methods'] += 1
                    stats[group]['bytes'] += 8
                    if code:
                        if code not in codes:
                            codes[code] = (self.code_size(code), set())
                        codes[code][1].add(group)
            stats[group]['bytes'] += cd - start
        # 跨组共享的 code_item 留在未分摊区域，避免重复计量或任意分给一组。
        for size, owners in codes.values():
            if len(owners) == 1:
                stats[next(iter(owners))]['bytes'] += size
        owned = sum(s['bytes'] for s in stats.values())
        if owned > len(self.data):
            raise AnalysisError('DEX 专属结构合计超过文件大小')
        markers = [s for s in strings if s.startswith('~~R8{')]
        return {'groups': dict(stats), 'raw_bytes': len(self.data),
                'unassigned_bytes': len(self.data) - owned, 'r8_markers': markers}


def category(name):
    if DEX_NAME.fullmatch(name):
        return 'DEX'
    if name.startswith('lib/'):
        return '/'.join(name.split('/')[:2])
    return name.split('/')[0]


def inspect_apk(path, prefixes):
    path = Path(path).expanduser().resolve()
    result = {'path': str(path), 'size_bytes': path.stat().st_size, 'categories': {},
              'sdk_properties': {}, 'dex': {'complete': True, 'files': {}, 'groups': {},
                                          'raw_bytes': 0, 'unassigned_bytes': 0},
              'warnings': []}
    entries = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len({i.filename for i in infos}) != len(infos):
            raise AnalysisError('ZIP 含重复文件名，拒绝进行不准确的对账')
        groups = collections.defaultdict(lambda: {'compressed_bytes': 0, 'raw_bytes': 0, 'files': 0})
        dex_groups = collections.defaultdict(lambda: {'classes': 0, 'methods': 0, 'bytes': 0})
        for info in infos:
            entries[info.filename] = {'compressed_bytes': info.compress_size,
                                      'raw_bytes': info.file_size, 'crc32': info.CRC,
                                      'compression_method': info.compress_type}
            g = groups[category(info.filename)]
            g['compressed_bytes'] += info.compress_size
            g['raw_bytes'] += info.file_size
            g['files'] += 1
            if info.filename.endswith('.properties') and info.file_size <= MAX_METADATA:
                try:
                    text = archive.read(info).decode('utf-8', 'replace')
                    pairs = dict(line.split('=', 1) for line in text.splitlines()
                                 if '=' in line and not line.startswith(('#', '!')))
                    if 'version' in pairs:
                        result['sdk_properties'][info.filename] = pairs
                except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                    result['warnings'].append(f'{info.filename}: 无法读取版本元数据：{exc}')
            if DEX_NAME.fullmatch(info.filename):
                try:
                    if info.file_size > MAX_DEX:
                        raise AnalysisError(f'单 DEX 超过 {MAX_DEX // 1024 // 1024} MiB 安全限制')
                    dex = Dex(archive.read(info)).analyze(prefixes)
                    result['dex']['files'][info.filename] = dex
                    result['dex']['raw_bytes'] += dex['raw_bytes']
                    result['dex']['unassigned_bytes'] += dex['unassigned_bytes']
                    for group, values in dex['groups'].items():
                        for key, value in values.items():
                            dex_groups[group][key] += value
                except (AnalysisError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                    result['dex']['complete'] = False
                    result['warnings'].append(f'{info.filename}: DEX 分析失败：{exc}')
        result['categories'] = dict(groups)
        result['dex']['groups'] = dict(dex_groups)
        if not result['dex']['files']:
            result['dex']['complete'] = False
            result['warnings'].append('没有成功解析的标准 classes*.dex（资源 split APK 可没有 DEX）')
    result['compressed_entries_bytes'] = sum(e['compressed_bytes'] for e in entries.values())
    result['zip_overhead_bytes'] = result['size_bytes'] - result['compressed_entries_bytes']
    if result['zip_overhead_bytes'] < 0:
        raise AnalysisError('ZIP 压缩数据总量超过文件长度')
    return result, entries


def compare(old_path, new_path, prefixes=None):
    prefixes = PREFIXES if prefixes is None else prefixes
    old, a = inspect_apk(old_path, prefixes)
    new, b = inspect_apk(new_path, prefixes)
    categories = []
    for group in sorted(set(old['categories']) | set(new['categories'])):
        before = old['categories'].get(group, {})
        after = new['categories'].get(group, {})
        categories.append({'name': group, 'old_compressed_bytes': before.get('compressed_bytes', 0),
                           'new_compressed_bytes': after.get('compressed_bytes', 0),
                           'delta_compressed_bytes': after.get('compressed_bytes', 0) - before.get('compressed_bytes', 0),
                           'delta_raw_bytes': after.get('raw_bytes', 0) - before.get('raw_bytes', 0)})
    files = []
    for name in sorted(set(a) | set(b)):
        before, after = a.get(name, {}), b.get(name, {})
        if before == after:
            continue
        files.append({'path': name, 'status': 'added' if name not in a else 'removed' if name not in b else 'changed',
                      'old': before, 'new': after,
                      'delta_compressed_bytes': after.get('compressed_bytes', 0) - before.get('compressed_bytes', 0),
                      'delta_raw_bytes': after.get('raw_bytes', 0) - before.get('raw_bytes', 0)})
    delta = new['size_bytes'] - old['size_bytes']
    overhead = new['zip_overhead_bytes'] - old['zip_overhead_bytes']
    reconciled = sum(g['delta_compressed_bytes'] for g in categories) + overhead
    if reconciled != delta:
        raise AnalysisError('分类增量与 APK 实际增量不一致')
    return {'schema_version': 1, 'old': old, 'new': new, 'delta_bytes': delta,
            'delta_percent': delta * 100 / old['size_bytes'] if old['size_bytes'] else None,
            'zip_overhead_delta_bytes': overhead, 'reconciled_delta_bytes': reconciled,
            'categories': sorted(categories, key=lambda x: x['delta_compressed_bytes'], reverse=True),
            'files': sorted(files, key=lambda x: (-x['delta_compressed_bytes'], x['path']))}


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('`', "'")


def kib(value):
    return f'{value / 1024:+,.1f}'


def render(report, top=20):
    old, new = report['old'], report['new']
    lines = ['# APK 包体比较', '', f"- 旧包：`{cell(old['path'])}`，{old['size_bytes']:,} 字节",
             f"- 新包：`{cell(new['path'])}`，{new['size_bytes']:,} 字节",
             f"- 净增：**{report['delta_bytes']:+,} 字节（{kib(report['delta_bytes'])} KiB，{report['delta_percent']:+.2f}%）**",
             '- 分类增量 + ZIP 外开销 = 文件净增量：对账通过。', '',
             '## 分类（压缩后，实际 APK 占用）', '',
             '| 分类 | 旧包 KiB | 新包 KiB | 增量 KiB | 未压缩增量 KiB |',
             '| --- | ---: | ---: | ---: | ---: |']
    for g in report['categories']:
        lines.append(f"| {cell(g['name'])} | {g['old_compressed_bytes']/1024:,.1f} | {g['new_compressed_bytes']/1024:,.1f} | {kib(g['delta_compressed_bytes'])} | {kib(g['delta_raw_bytes'])} |")
    lines += [f"| ZIP 外开销（文件头、签名、对齐等） | {old['zip_overhead_bytes']/1024:,.1f} | {new['zip_overhead_bytes']/1024:,.1f} | {kib(report['zip_overhead_delta_bytes'])} | — |", '']
    for title, files in [('增长文件', [f for f in report['files'] if f['delta_compressed_bytes'] > 0]),
                         ('缩减文件', sorted([f for f in report['files'] if f['delta_compressed_bytes'] < 0], key=lambda f: (f['delta_compressed_bytes'], f['path'])))]:
        lines += [f'## {title}（前 {top} 项）', '', '| 文件 | 状态 | 压缩增量 KiB | 未压缩增量 KiB |', '| --- | --- | ---: | ---: |']
        for f in files[:top]:
            lines.append(f"| `{cell(f['path'])}` | {f['status']} | {kib(f['delta_compressed_bytes'])} | {kib(f['delta_raw_bytes'])} |")
        lines.append('')
    lines += ['## DEX 包名前缀归因（未压缩专属结构，不是 SDK 压缩包体）', '']
    if old['dex']['complete'] and new['dex']['complete']:
        a, b = old['dex']['groups'], new['dex']['groups']
        lines += ['| 包归组 | 类增量 | 方法增量 | 专属结构增量 KiB |', '| --- | ---: | ---: | ---: |']
        for name in sorted(set(a) | set(b), key=lambda n: (-(b.get(n, {}).get('bytes', 0)-a.get(n, {}).get('bytes', 0)), n)):
            before, after = a.get(name, {}), b.get(name, {})
            lines.append(f"| {cell(name)} | {after.get('classes',0)-before.get('classes',0):+} | {after.get('methods',0)-before.get('methods',0):+} | {kib(after.get('bytes',0)-before.get('bytes',0))} |")
        lines += [f"| 共享 / 未分摊区域 | — | — | {kib(new['dex']['unassigned_bytes']-old['dex']['unassigned_bytes'])} |",
                  f"| DEX 未压缩总增量 | — | — | {kib(new['dex']['raw_bytes']-old['dex']['raw_bytes'])} |", '']
    else:
        lines += ['**DEX 解析不完整，禁止根据部分结果进行两包 SDK 体积归因。** JSON 中保留成功解析的文件供排查。', '']
    lines += ['口径：class_def、已定义字段/方法 ID、class_data、code_item（含异常处理）；跨组共享 code_item 不分摊。字符串、类型/原型表、调试信息、注解、外部引用、对齐等留在未分摊区域。包名前缀不是完整依赖身份；混淆、内联和类合并会影响归组。', '',
              '## APK 内 SDK 版本证据', '', '| 元数据文件 | 旧版本 | 新版本 |', '| --- | --- | --- |']
    for name in sorted(set(old['sdk_properties']) | set(new['sdk_properties'])):
        lines.append(f"| {cell(name)} | {cell(old['sdk_properties'].get(name,{}).get('version','—'))} | {cell(new['sdk_properties'].get(name,{}).get('version','—'))} |")
    lines += ['', '## R8 构建标记', '']
    for label, apk in [('旧包', old), ('新包', new)]:
        markers = sorted({m for d in apk['dex']['files'].values() for m in d['r8_markers']})
        lines.append(f'### {label}')
        lines.extend(f'- `{cell(m)}`' for m in markers)
        if not markers:
            lines.append('- 未找到 R8 标记。')
    lines += ['', '## 限制与后续核对', '',
              '- SDK 压缩后体积不能按类数量、未压缩占比或某个 classes.dex 的增量硬分摊。',
              '- res/ 名字可能被混淆；路径新增/删除不等于素材真实新增/删除。',
              '- 当前 Gradle/POM 是当前依赖证据，不自动等同于旧 APK 的构建依赖。mapping 必须与 APK 最终 backend=dex 的 R8 pg-map-id 对上。',
              '- 本脚本只读 ZIP，不提取、不执行 APK，不构建、安装、上传或修改项目。',
              '- 比较对象须核对 ABI、渠道、split/universal 与构建类型；本脚本不能单凭文件名证明这些相同。']
    for label, apk in [('旧包', old), ('新包', new)]:
        lines.extend(f'- 警告（{label}）：{cell(w)}' for w in apk['warnings'])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old_apk', help='旧 APK 路径')
    parser.add_argument('new_apk', help='新 APK 路径')
    parser.add_argument('--output-dir', type=Path, help='新建报告目录；已存在时拒绝覆盖')
    parser.add_argument('--top', type=int, default=20, help='文件增减排名项数（默认 20）')
    parser.add_argument('--package-prefix', action='append', default=[], metavar='PREFIX=LABEL',
                        help='补充包名前缀归组，例如 com/example/=业务代码，可重复')
    args = parser.parse_args()
    try:
        if args.top < 1:
            raise AnalysisError('--top 必须大于零')
        if args.output_dir:
            output = args.output_dir.expanduser().resolve()
            if output.exists() or output.is_relative_to(Path(__file__).resolve().parents[3]):
                raise AnalysisError('报告目录须为整个插件之外的新目录，避免覆盖或污染技能源')
        prefixes = dict(PREFIXES)
        for rule in args.package_prefix:
            prefix, sep, label = rule.partition('=')
            if not sep or not prefix.endswith('/') or not label.strip():
                raise AnalysisError('--package-prefix 格式应为 PREFIX/=LABEL')
            prefixes[prefix] = label
        report = compare(args.old_apk, args.new_apk, prefixes)
        markdown = render(report, args.top)
        if args.output_dir:
            directory = args.output_dir.expanduser()
            directory.mkdir(parents=True, exist_ok=False)
            (directory / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            (directory / 'report.md').write_text(markdown, encoding='utf-8')
        print(markdown)
        return 0 if report['old']['dex']['complete'] and report['new']['dex']['complete'] else 2
    except (AnalysisError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
