#!/usr/bin/env python3
"""使用现有 rsvg-convert 栅格化 SVG，不猜测或自动删除画板背景。"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_common import new_output


def local_reference(value):
    return value.startswith('#') or re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+', value) is not None


def check_svg(path):
    value = path.read_text(encoding='utf-8-sig')
    if '<!DOCTYPE' in value or '<!ENTITY' in value or re.search(r'@import\b', value, re.I):
        raise ValueError('SVG 不允许 DTD、实体或外部 CSS 导入')
    root = ET.fromstring(value)
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('输入不是 SVG')
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] in ('script', 'foreignObject', 'style'):
            raise ValueError('SVG 含不支持的主动内容或样式块')
        for key, attribute in node.attrib.items():
            name = key.rsplit('}', 1)[-1]
            if '\\' in attribute or re.search(r'@import\b', attribute, re.I):
                raise ValueError('SVG 转义样式须先人工处理')
            for reference in re.finditer(r'url\(\s*([^)]*)\)', attribute, re.I):
                if not local_reference(reference[1].strip().strip('\"\'')):
                    raise ValueError('SVG 属性含外部资源引用')
            if name == 'base' or name.startswith('on'):
                raise ValueError('SVG 不允许基址重写或事件处理器')
            if name == 'href' and not local_reference(attribute.strip()):
                raise ValueError('SVG 含外部资源引用，须先导出为独立素材')
    for match in re.finditer(r'url\(\s*([^)]*)\)', value, re.I):
        target = match[1].strip().strip('\"\'')
        if not local_reference(target):
            raise ValueError('SVG CSS 含外部资源引用')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        out = new_output(args.out)
        converter = shutil.which('rsvg-convert')
        if not converter:
            raise ValueError('缺少现有 rsvg-convert，不自动安装依赖')
        files = sorted(args.input.glob('*.svg'))
        if not files:
            raise ValueError('输入目录没有 SVG')
        for path in files:
            check_svg(path)
        out.mkdir(parents=True, exist_ok=False)
        for path in files:
            target = out/(path.stem+'.png')
            subprocess.run([converter, '-o', str(target), str(path.resolve())], check=True, timeout=60)
            if not target.is_file() or not target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('未取得有效 PNG 签名：'+target.name)
            print(target)
        print('背景未自动移除；alpha 通道及素材视觉透明性须另验')
        return 0
    except (ValueError, OSError, ET.ParseError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
