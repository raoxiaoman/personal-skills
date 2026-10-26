#!/usr/bin/env python3
"""校验本地核心配置和 ZIP 清单；可选 HTTPS HEAD 仅检查可达性。"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_common import load_json, validate_config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def base_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('远端检查须使用无凭据、查询或片段的明确 HTTPS 根路径')
    return value.rstrip('/')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--zip', required=True)
    parser.add_argument('--base-url', help='显式授权该资源根路径的 HTTPS HEAD')
    parser.add_argument('--font-base-url', help='显式授权该字体根路径的 HTTPS HEAD')
    args = parser.parse_args()
    try:
        path = Path(args.config)
        data = load_json(path)
        num, stickers, fonts = validate_config(data)
        config_name = f'cover_template_item_config_{num}.json'
        if Path(args.zip).name != f'template{num}.zip':
            raise ValueError('ZIP 文件名与模板编号不一致')
        expected = {config_name, *stickers, *fonts}
        with zipfile.ZipFile(args.zip) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected:
                raise ValueError('ZIP 包含重复、缺失或额外文件，或存在非预期目录路径')
            if archive.getinfo(config_name).file_size > 16 * 1024 * 1024:
                raise ValueError('包内配置超过读取上限')
            packaged = json.loads(archive.read(config_name).decode('utf-8-sig'))
            validate_config(packaged, num)
            if packaged != data:
                raise ValueError('ZIP 内配置与指定最终配置不一致')
        urls = []
        if args.base_url:
            base = base_url(args.base_url)
            urls.extend(base+'/'+quote(name) for name in (config_name, f'template{num}.zip', 'cover.webp'))
        if args.font_base_url:
            base = base_url(args.font_base_url)
            urls.extend(base+'/'+quote(name) for name in sorted(fonts))
        opener = urllib.request.build_opener(NoRedirect())
        for url in urls:
            with opener.open(urllib.request.Request(url, method='HEAD'), timeout=20) as response:
                if response.status != 200:
                    raise ValueError(f'HTTP 可达性检查未通过：{response.status}')
            print('HEAD 200 '+url)
        print('本地核心契约与 ZIP 清单/配置一致性通过；不代表素材视觉、完整客户端 schema 或 App 验收通过')
        print('远端：仅 HEAD 可达，未核对内容、CDN 缓存或客户端下载' if urls else '远端：未执行')
        return 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
