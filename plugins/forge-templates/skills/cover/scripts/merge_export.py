#!/usr/bin/env python3
"""保留 App 导出真值，部分方向合并后写入新文件。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_common import GROUPS, load_json, new_output, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'exported', 'out'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--direction', choices=('v', 'h'))
    args = parser.parse_args()
    try:
        out = new_output(args.out)
        base, exported = load_json(args.base), load_json(args.exported)
        template_num, _, _ = validate_config(base)
        if not isinstance(exported, dict):
            raise ValueError('导出配置必须是对象')
        if all(key in exported for key in GROUPS):
            result = exported
        else:
            if not args.direction:
                raise ValueError('部分导出须显式指定 --direction v 或 h')
            if not isinstance(base, dict):
                raise ValueError('基础配置必须是对象')
            groups = ('texts', 'stickers') if args.direction == 'v' else ('textsH', 'stickersH')
            if any(key not in exported for key in groups):
                raise ValueError('导出文件缺少目标方向字段')
            result = dict(base)
            result.update({key: exported[key] for key in groups})
        validate_config(result, template_num)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(out)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
