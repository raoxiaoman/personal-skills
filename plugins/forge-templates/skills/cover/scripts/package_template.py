#!/usr/bin/env python3
"""校验素材后在全新目录打包，不删除旧目录或重排贴纸编号。"""
import argparse
import shutil
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_common import asset_file, load_json, new_output, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'stickers', 'fonts', 'cover', 'out'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--template-num', required=True, type=int)
    args = parser.parse_args()
    try:
        out = new_output(args.out)
        config = Path(args.config)
        data = load_json(config)
        num, stickers, fonts = validate_config(data, args.template_num)
        expected = f'cover_template_item_config_{num}.json'
        cover = Path(args.cover)
        if not cover.is_file():
            raise ValueError('缺少封面文件')
        sources = {expected: config, 'cover.webp': cover}
        sources.update({name: asset_file(args.stickers, name) for name in stickers})
        sources.update({name: asset_file(args.fonts, name) for name in fonts})
        out.mkdir(parents=True, exist_ok=False)
        build = out/'build'
        build.mkdir()
        for name, source in sorted(sources.items()):
            shutil.copyfile(source, build/name)
        archive = out/f'template{num}.zip'
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as stream:
            for name in sorted(sources.keys()-{'cover.webp'}):
                stream.write(build/name, name)
        print(f'写出：{archive}；仅通过本地核心契约与素材存在性检查，视觉/客户端下载另验')
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
