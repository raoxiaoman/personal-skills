"""本地埋点证据采集与解析；不启动查看器、不清日志、不证明服务端接收。"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def parse(line):
    source = None
    event = None
    params = {}
    if re.search(r'\b(?:FA|FA-SVC)\s*:', line) and 'Logging event' in line:
        source = 'firebase-sdk'
        m = re.search(r'Logging event(?:\s+\([^)]+\))?:\s*([^,]+)', line)
        if m and '=' not in m[1]:
            event = m[1].strip()
        else:
            m = re.search(r'(?:^|,)name=([^,]+)', line)
            event = m[1].strip() if m else None
        for key in ('content_type', 'item_id'):
            m = re.search(r'\b' + key + r'(?:\([^)]+\))?=([^,}\]]*)', line)
            if m:
                params[key] = m[1].strip()
    elif 'UtTrackFirebaseImpl' in line and 'logEvent:' in line:
        source = 'app'
        for key, label in [('event', 'event'), ('content_type', 'content'), ('item_id', 'item_id')]:
            m = re.search(r'\b' + label + r':\s*([^,\s]+)', line)
            if m:
                if key == 'event':
                    event = m[1]
                else:
                    params[key] = m[1]
    elif 'ISFirebaseListener' in line and 'sendEvent' in line:
        source = 'app-legacy'
        m = re.search(r'eventName=([^,\s]+)', line)
        event = m[1] if m else None
        keys = re.search(r'key=\[([^\]]*)\]', line)
        values = re.search(r'value=\[([^\]]*)\]', line)
        if keys and values:
            for key, value in zip(keys[1].split(','), values[1].split(',')):
                if key.strip() in ('content_type', 'item_id'):
                    params[key.strip()] = value.strip()
        m = re.search(r'item_id:\s*([^,\s]+)', line)
        if m:
            params['item_id'] = m[1]
    if not event or event.startswith('sampled_'):
        return None
    # 只保留事件契约标识，不输出任意动态载荷、用户或支付标识。
    tokens = [event, params.get('content_type', ''), params.get('item_id', '')]
    if any(len(t) > 100 or re.search(r'[^\w. /≤<>:+-]', t) for t in tokens):
        return None
    return dict(source=source, event=event, content_type=tokens[1], item_id=tokens[2])


def report(text, contents):
    counts = Counter()
    events = []
    for line in text.splitlines():
        value = parse(line)
        if value and value['content_type'] in contents:
            counts[tuple(value.values())] += 1
            events.append(value)
    return dict(schema_version=1, events=events,
                counts=[dict(source=k[0], event=k[1], content_type=k[2], item_id=k[3], count=v)
                        for k, v in sorted(counts.items())],
                notice='不跨来源去重；日志次数不是业务唯一事件次数；无日志不证明未埋点；服务端接收未验证')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='解析已有日志；不连接设备')
    parser.add_argument('--capture', action='store_true', help='显式授权只读限时logcat采集')
    parser.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'))
    parser.add_argument('--package')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--content', action='append', required=True, help='允许保存的content_type，重复指定')
    parser.add_argument('--output', type=Path, required=True, help='全新输出文件，禁止覆盖')
    args = parser.parse_args()
    try:
        if bool(args.input) == args.capture:
            raise ValueError('选择--input或--capture之一')
        args.output = args.output.expanduser().resolve()
        if args.output.exists() or args.output.is_relative_to(Path(__file__).resolve().parents[3]):
            raise ValueError('输出须为整个插件之外的新文件')
        if not all(re.fullmatch(r'[A-Za-z_][\w.-]*', x) for x in args.content):
            raise ValueError('content必须是事件契约标识')
        metadata = {}
        if args.capture:
            bound = os.environ.get('ANDROID_SERIAL')
            if not bound or args.serial != bound:
                raise ValueError('设备缺失或与当前绑定冲突')
            if not args.package or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', args.package) or not 1 <= args.seconds <= 300:
                raise ValueError('需合法包名及1..300秒采集时间')
            adb = ['adb', '-s', args.serial]
            state = subprocess.check_output(adb + ['get-state'], text=True, timeout=10).strip()
            if state != 'device':
                raise ValueError('当前绑定设备不可用')
            pid = subprocess.check_output(adb + ['shell', 'pidof', args.package], text=True, timeout=10).strip()
            if not re.fullmatch(r'\d+', pid):
                raise ValueError('应用主进程未运行或PID不唯一，不猜进程')
            stamp = subprocess.check_output(adb + ['shell', "date '+%m-%d %H:%M:%S.000'"], text=True, timeout=10).strip()
            command = adb + ['logcat', '--pid=' + pid, '-v', 'threadtime', '-T', stamp, '-s', 'FA:V', 'FA-SVC:V', 'ISFirebaseListener:V', 'UtTrackFirebaseImpl:V', '*:S']
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = proc.communicate(timeout=args.seconds)
                raise ValueError('logcat提前退出：' + str(proc.returncode) + '；请核对ADB时间参数与设备连接')
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
            current = subprocess.check_output(adb + ['shell', 'pidof', args.package], text=True, timeout=10).strip()
            metadata = dict(serial=args.serial, package=args.package, pid=pid, start=stamp,
                            process_stable=current == pid, stderr_present=bool(stderr),
                            scope='仅目标主进程；不涵盖其他进程FA-SVC；应用重启需新采集')
            text = stdout.decode(errors='replace')
        else:
            text = args.input.read_text(errors='replace')
            metadata = dict(scope='导入日志，应用/设备来源由提供者确认')
        result = report(text, set(args.content))
        result['capture'] = metadata
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(args.output)
        return 2 if not result['events'] or metadata.get('process_stable') is False else 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
