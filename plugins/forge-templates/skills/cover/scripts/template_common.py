"""本地模板工具共用的核心配置契约与新输出边界。"""
import json
import math
from pathlib import Path
import re


GROUPS = ('texts', 'stickers', 'textsH', 'stickersH')
PLUGIN = Path(__file__).resolve().parents[3]


def load_json(path):
    def invalid(value):
        raise ValueError('JSON 不允许非有限数值：'+value)
    with Path(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream, parse_constant=invalid)


def new_output(path):
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_relative_to(PLUGIN):
        raise ValueError('输出须为整个插件之外的新路径，不覆盖历史产物')
    return path


def asset_name(value, kind, template_num=None):
    if not isinstance(value, str) or not value or '\\' in value or '\0' in value:
        raise ValueError('素材引用路径无效')
    name = value.rsplit('/', 1)[-1]
    if not name or name in ('.', '..') or '..' in Path(value).parts:
        raise ValueError('素材文件名或路径无效')
    if kind == 'sticker':
        match = re.fullmatch(r'template([1-9][0-9]*)_sticker([1-9][0-9]*)\.png', name)
        if not match or template_num is not None and int(match[1]) != template_num:
            raise ValueError('错误编号贴纸：'+name)
    elif Path(name).suffix.lower() not in ('.ttf', '.otf'):
        raise ValueError('字体必须引用实际 ttf/otf 文件')
    return name


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('配置包含非有限数值')
    if isinstance(value, dict):
        for child in value.values():
            finite(child)
    elif isinstance(value, list):
        for child in value:
            finite(child)


def equal(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-7)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def geometry(item, fields):
    for key, length in fields:
        if key in item:
            value = item[key]
            if not isinstance(value, list) or len(value) != length or any(type(v) not in (int, float) for v in value):
                raise ValueError(key+' 几何数组结构无效')


def validate_config(data, template_num=None):
    if not isinstance(data, dict) or any(not isinstance(data.get(k), list) for k in GROUPS):
        raise ValueError('配置须包含四个列表 texts/stickers/textsH/stickersH')
    finite(data)
    ids = {}
    numbers = set()
    stickers, fonts = set(), set()
    for group in GROUPS:
        text = group.startswith('texts')
        key, number = ('TI_13', 'TI_12') if text else ('SI_11', 'SI_10')
        ids[group] = {}
        for item in data[group]:
            if not isinstance(item, dict):
                raise ValueError(group+' 包含非对象元素')
            style = item.get(key)
            num = item.get(number)
            if type(style) is not int or style < 1 or style in ids[group]:
                raise ValueError(group+' 样式编号缺失、重复或无效')
            if type(num) is not int or num < 1:
                raise ValueError(group+' 模板编号缺失或无效')
            numbers.add(num)
            geometry(item, [('BI_10', 9), ('BI_12', 10), ('BI_13', 10), ('SI_2', 9), ('SI_5', 10), ('SI_6', 10)])
            if 'BI_5' in item or 'BI_6' in item:
                if any(type(item.get(k)) not in (int, float) or item[k] <= 0 for k in ('BI_5', 'BI_6')):
                    raise ValueError('画布宽高须为正数')
            if 'BI_3' in item and (type(item['BI_3']) not in (int, float) or item['BI_3'] <= 0):
                raise ValueError('显示缩放须为正数')
            ids[group][style] = item
            if text:
                if not isinstance(item.get('TI_1'), str):
                    raise ValueError('文字内容必须是字符串')
                fonts.add(asset_name(item.get('TI_6'), 'font'))
                tp = item.get('TI_9')
                if tp is not None:
                    if not isinstance(tp, dict):
                        raise ValueError('TI_9 必须是对象')
                    geometry(tp, [('TI_20', 10), ('TI_22', 10), ('TI_23', 9)])
                    if 'TI_2' in item or 'TP_8' in tp:
                        colors = tp.get('TP_8')
                        if not isinstance(colors, list) or len(colors) != 2 or any(c != item.get('TI_2') for c in colors):
                            raise ValueError('纯色文字的颜色副本不一致')
                    for base, prop in [('BI_5', 'TI_27'), ('BI_6', 'TI_28')]:
                        if (base in item or prop in tp) and not equal(item.get(base), tp.get(prop)):
                            raise ValueError('文字布局画布与当前画布不一致')
                    for base, prop in [('BI_12', 'TI_20'), ('BI_13', 'TI_22'), ('BI_10', 'TI_23'), ('BI_3', 'TI_29'), ('TI_6', 'TP_14'), ('TI_1', 'TP_15')]:
                        if (base in item or prop in tp) and not equal(item.get(base), tp.get(prop)):
                            raise ValueError(f'文字重复字段不一致：{base}/{prop}')
            else:
                stickers.add(asset_name(item.get('SI_1'), 'sticker', num))
    if len(numbers) != 1 or template_num is not None and numbers != {template_num}:
        raise ValueError('四组元素必须属于同一指定模板，且模板不能为空')
    for vertical, horizontal in [('texts', 'textsH'), ('stickers', 'stickersH')]:
        if set(ids[vertical]) != set(ids[horizontal]):
            raise ValueError(vertical+' 横竖屏样式编号或数量不一致')
        for key, item in ids[vertical].items():
            other = ids[horizontal][key]
            if vertical == 'texts' and item['TI_1'] != other['TI_1']:
                raise ValueError('同一样式编号的横竖屏文字内容不一致')
            if vertical == 'stickers' and asset_name(item['SI_1'], 'sticker') != asset_name(other['SI_1'], 'sticker'):
                raise ValueError('同一样式编号的横竖屏贴纸引用不一致')
    for groups in [('texts', 'stickers'), ('textsH', 'stickersH')]:
        canvases = {(item['BI_5'], item['BI_6']) for group in groups for item in data[group] if 'BI_5' in item}
        if len(canvases) > 1:
            raise ValueError('同一方向元素画布尺寸不一致')
    return numbers.pop(), stickers, fonts


def asset_file(directory, name):
    root = Path(directory).resolve()
    source = (root/name).resolve()
    if not source.is_relative_to(root) or not source.is_file():
        raise ValueError('素材缺失或符号链接逃离输入目录：'+name)
    return source
