"""在当前绑定设备上采集 UI 证据；不安装、启动、导航或修改设备设置。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET


class CaptureError(Exception):
    pass


def command(adb, *args, timeout):
    try:
        result = subprocess.run([*adb, *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CaptureError(f'ADB 调用未完成：{type(error).__name__}') from error
    if result.returncode:
        raise CaptureError(f'ADB 阶段失败：{args[0]}，退出码 {result.returncode}')
    return result.stdout


def text(adb, *args, timeout):
    return command(adb, *args, timeout=timeout).decode('utf-8').strip()


def layout(adb, timeout):
    remote = '/data/local/tmp/forge-android-ui-' + uuid.uuid4().hex + '.xml'
    error = None
    data = b''
    try:
        command(adb, 'shell', 'uiautomator', 'dump', remote, timeout=timeout)
        data = command(adb, 'exec-out', 'cat', remote, timeout=timeout)
        if len(data) > 16 * 1024 * 1024 or b'<!DOCTYPE' in data or b'<!ENTITY' in data:
            raise CaptureError('层级内容超限或含不支持的声明')
        if ET.fromstring(data).tag != 'hierarchy':
            raise CaptureError('未取得有效的 hierarchy 根节点')
    except (CaptureError, ET.ParseError) as failure:
        error = str(failure)
    try:
        command(adb, 'shell', 'rm', '-f', remote, timeout=timeout)
    except CaptureError as failure:
        error = f'{error + "; " if error else ""}本轮设备临时文件清理失败：{failure}'
    if error:
        raise CaptureError(error)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='插件之外的全新证据目录')
    parser.add_argument('--serial', help='只能匹配当前 ANDROID_SERIAL')
    parser.add_argument('--adb', default='adb', help='已安装的 ADB 可执行文件')
    parser.add_argument('--layout-tree', action='store_true')
    parser.add_argument('--timeout', type=int, default=20)
    args = parser.parse_args()
    try:
        serial = os.environ.get('ANDROID_SERIAL')
        if not serial or args.serial and args.serial != serial:
            raise CaptureError('设备未绑定或 --serial 与当前 ANDROID_SERIAL 冲突')
        if not 1 <= args.timeout <= 120:
            raise CaptureError('--timeout 须为 1..120 秒')
        directory = args.output_dir.expanduser().resolve()
        if directory.exists() or directory.is_relative_to(Path(__file__).resolve().parents[3]):
            raise CaptureError('证据目录须为整个插件之外的新目录，不覆盖历史结果')
        executable = shutil.which(args.adb)
        if not executable:
            raise CaptureError('未找到 ADB；使用现有 SDK 的 adb 或 --adb，不自动安装')
        adb = [executable, '-s', serial]
        if text(adb, 'get-state', timeout=args.timeout) != 'device':
            raise CaptureError('当前绑定设备不可用，不自动换机')
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        png = command(adb, 'exec-out', 'screencap', '-p', timeout=args.timeout)
        if (len(png) < 45 or not png.startswith(b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR')
                or not png.endswith(b'\0\0\0\0IEND\xaeB`\x82')):
            raise CaptureError('截图输出缺少 PNG 签名、IHDR 或 IEND')
        width, height = struct.unpack('>II', png[16:24])
        if not width or not height:
            raise CaptureError('截图尺寸无效')
        with (directory/'screen.png').open('xb') as stream:
            stream.write(png)
        metadata = dict(serial=serial, screenshot_width=width, screenshot_height=height,
                        layout_requested=args.layout_tree, scope='本轮采集证据，不证明应用版本或视觉/交互正确')
        for key, query in [
            ('model', ['getprop', 'ro.product.model']),
            ('sdk', ['getprop', 'ro.build.version.sdk']),
            ('locale', ['getprop', 'persist.sys.locale']),
            ('display_size', ['wm', 'size']),
            ('density', ['wm', 'density']),
            ('font_scale', ['settings', 'get', 'system', 'font_scale']),
        ]:
            metadata[key] = text(adb, 'shell', *query, timeout=args.timeout)
        with (directory/'device.json').open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2)
        if args.layout_tree:
            xml = layout(adb, args.timeout)
            with (directory/'layout.xml').open('xb') as stream:
                stream.write(xml)
        print(directory)
        return 0
    except (CaptureError, OSError, UnicodeError) as error:
        print(f'采集失败：{error}；已生成的本轮证据保留，不自动重跑', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
