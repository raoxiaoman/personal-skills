#!/usr/bin/env python3
"""从双方向 Figma 中性数据克隆模板骨架，生成待人工校准的候选配置。"""
import argparse
import difflib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from template_common import asset_name, load_json, new_output, validate_config

DEFAULT_CANVAS = (1075, 1434)     # 竖屏主流画布（3:4）
DEFAULT_CANVAS_H = (1080, 610)    # 横屏主流画布（16:9）

# 文字合并判据（按位置，不依赖 Figma 分组——设计在横竖屏的分组方式不一致）
ROT_TOL = 3.0        # 旋转角容差（度）
OVERLAP_MIN = 0.3    # 水平重叠至少占较窄者宽度的比例
GAP_MAX = 0.8        # 垂直间距上限（占较高者高度的比例）


class Element:
    """中性元素。box 走属性读取，避免合并时 raw 被替换后持有过期引用。"""

    def __init__(self, raw):
        self.raw = raw
        self.kind = raw['kind']
        self.name = raw['name']
        self.group = raw.get('group')
        self.rot = raw.get('rot', 0)

    @property
    def box(self):
        return self.raw['box']

    @property
    def center(self):
        b = self.box
        return (b['x'] + b['w'] / 2, b['y'] + b['h'] / 2)

    def style_key(self):
        """文字能否合并的样式判据"""
        r = self.raw
        return (r.get('font'), r.get('size'),
                json.dumps(r.get('color'), sort_keys=True), r.get('align'))


# ---------- 基础换算 ----------

def rgb_to_int(color):
    """Figma {r,g,b} → Android ARGB int（补充不透明 alpha）。"""
    if not color:
        return -1
    rgb = (round(color['r']) << 16) | (round(color['g']) << 8) | round(color['b'])
    argb = 0xFF000000 | rgb
    return argb - 0x100000000 if argb >= 0x80000000 else argb


def font_file(figma_font, font_map):
    """'Bebas:Regular' → 'Bebas-Regular.otf'（按 meta 映射表，缺省用规律拼）"""
    if figma_font in font_map:
        return font_map[figma_font]
    fam, _, style = figma_font.partition(':')
    return f"{fam}-{style}.ttf"


def parse_adjust_suffix(name):
    """图层名 @top/@full/@bottom 等后缀 → SI_12 值"""
    table = {'common': 0, 'top': 1, 'bottom': 2, 'left': 3, 'right': 4,
             'upperleft': 5, 'upperright': 6, 'lowerleft': 7, 'lowerright': 8, 'full': 9}
    if '@' not in name:
        return 0, name
    base, _, tag = name.rpartition('@')
    key = tag.strip().lower().replace('_', '').replace('-', '')
    return table.get(key, 0), base


# ---------- 过滤与合并 ----------

def drop_background(elements, frame):
    """剔除背景/遮罩：铺满宽度、铺满高度、或宽高任一超出画板的元素。"""
    fw, fh = frame['w'], frame['h']
    kept, dropped = [], []
    for e in elements:
        b = e.box
        full_width = b['w'] >= fw * 0.98
        full_height = b['h'] >= fh * 0.98
        oversized = b['w'] > fw * 1.02 or b['h'] > fh * 1.02
        (dropped if (full_width or full_height or oversized) else kept).append(e)
    return kept, dropped


def _mergeable(a, b):
    """两个文字是否属于同一段多行文字（视觉相邻 + 样式一致）。

    不依赖 Figma 分组：实测设计在横竖屏的分组方式不一致，
    按分组会得到两边元素数不同，切换画布比例时模板重匹配会错位。
    """
    if a.style_key() != b.style_key():
        return False
    if abs(a.rot - b.rot) > ROT_TOL:
        return False
    ax1, ax2 = a.box['x'], a.box['x'] + a.box['w']
    bx1, bx2 = b.box['x'], b.box['x'] + b.box['w']
    overlap = min(ax2, bx2) - max(ax1, bx1)
    if overlap < OVERLAP_MIN * min(a.box['w'], b.box['w']):
        return False
    gap = b.box['y'] - (a.box['y'] + a.box['h'])
    tallest = max(a.box['h'], b.box['h'])
    return -0.5 * tallest <= gap <= GAP_MAX * tallest


def _merge_chain(items):
    """把一串同段文字合成一个多行 TextItem（按 y 顺序）"""
    first = items[0]
    m = Element(dict(first.raw))
    xs = [i.box['x'] for i in items]
    ys = [i.box['y'] for i in items]
    xe = [i.box['x'] + i.box['w'] for i in items]
    ye = [i.box['y'] + i.box['h'] for i in items]
    m.raw['box'] = {'x': min(xs), 'y': min(ys),
                    'w': max(xe) - min(xs), 'h': max(ye) - min(ys)}
    m.raw['chars'] = '\n'.join(i.raw['chars'].rstrip() for i in items)
    m.raw['_merged'] = len(items)
    m.raw['_parts'] = [dict(i.raw) for i in items]
    return m


def group_texts(elements):
    """同段多行文字合并为一个 TextItem。"""
    others = [e for e in elements if e.kind != 'text']
    texts = sorted([e for e in elements if e.kind == 'text'],
                   key=lambda e: (e.box['y'], e.box['x']))

    chains = []
    for t in texts:
        for ch in chains:
            if _mergeable(ch[-1], t):
                ch.append(t)
                break
        else:
            chains.append([t])

    merged = [ch[0] if len(ch) == 1 else _merge_chain(ch) for ch in chains]
    return merged + others



# ---------- 横竖屏对齐 ----------

def _cfg_box(item):
    """从配置项取包围盒。文字在 TI_9.TI_22，贴纸在 SI_6（均为 10 元布局数组）。"""
    pts = item['TI_9']['TI_22'] if 'TI_9' in item else item['SI_6']
    xs = pts[0:8:2]
    ys = pts[1:8:2]
    return {'x': min(xs), 'y': min(ys),
            'w': max(xs) - min(xs), 'h': max(ys) - min(ys)}


# 匹配权重：尺寸最可靠（同一素材只是缩放），其次图层名，位置最弱
W_SIZE, W_NAME, W_POS = 0.5, 0.3, 0.2


def _name_sim(na, nb):
    """图层名相似度。设计在横竖屏常给同一素材起不同名字
    （形状备份-7 vs 形状备份-8），所以只看前缀主干，去掉尾部数字。"""
    def stem(n):
        return re.sub(r'[-_ ]?\d+$', '', n or '')
    sa, sb = stem(na), stem(nb)
    if not sa or not sb:
        return 0.0
    return difflib.SequenceMatcher(None, sa, sb).ratio()


def _similarity(a, b, vctx, hctx):
    """两个异向元素的相似度，0=无关 1=一致。

    尺寸必须用**相对尺寸**：横竖屏画板尺寸不同（600x800 vs 800x450），
    缩放比例也不同（1.79 vs 1.35），直接比绝对值会把 11x14 认成 15x18。
    """
    ab, bb = _cfg_box(a), _cfg_box(b)
    vavg, havg = vctx['avg'], hctx['avg']

    def rel(box, avg, scale):
        return box['w'] / avg[0] * scale, box['h'] / avg[1] * scale

    # 归一化到同一尺度后比较
    arw, arh = ab['w'] / vavg[0], ab['h'] / vavg[1]
    brw, brh = bb['w'] / havg[0], bb['h'] / havg[1]
    size_sim = (min(arw, brw) / max(arw, brw) * min(arh, brh) / max(arh, brh))

    vcanvas, hcanvas = vctx['canvas'], hctx['canvas']

    acx = (ab['x'] + ab['w'] / 2) / vcanvas[0]
    acy = (ab['y'] + ab['h'] / 2) / vcanvas[1]
    bcx = (bb['x'] + bb['w'] / 2) / hcanvas[0]
    bcy = (bb['y'] + bb['h'] / 2) / hcanvas[1]
    pos_sim = max(0.0, 1 - math.hypot(acx - bcx, acy - bcy) / 0.5)

    name_sim = _name_sim(a.get('_name'), b.get('_name'))

    return W_SIZE * size_sim + W_NAME * name_sim + W_POS * pos_sim


def _orient_ctx(items, canvas):
    """预计算一个方向的匹配上下文（平均尺寸 + 画布），供 _similarity 使用。"""
    boxes = [_cfg_box(i) for i in items]
    n = max(len(boxes), 1)
    return {'canvas': canvas,
            'avg': (sum(b['w'] for b in boxes) / n, sum(b['h'] for b in boxes) / n)}


def _align_texts(v_items, h_items, vctx, hctx, label):
    """文字按内容匹配（TI_1）。内容相同是同一段文字的最强证据，
    比几何可靠——横竖屏排版不同，尺寸位置都会变。"""
    if len(v_items) != len(h_items):
        raise ValueError(
            f"{label}横竖屏数量不一致：竖屏 {len(v_items)} / 横屏 {len(h_items)}。"
            "请确认设计在两个画板放置了相同的元素。")
    used_h, mapping = set(), {}
    for i, v in enumerate(v_items):
        same = [j for j, h in enumerate(h_items)
                if j not in used_h and h['TI_1'] == v['TI_1']]
        if not same:
            raise ValueError('横竖屏文字内容无法精确对应，请先人工核对')
        if len(same) > 1:
            raise ValueError('重复文字无法唯一对应，请先人工核对元素身份')
        j = same[0]
        used_h.add(j)
        mapping[i] = j
    return [h_items[mapping[i]] for i in range(len(v_items))]


def _align_pair(v_items, h_items, vctx, hctx, label):
    """把 h_items 重排成与 v_items 一一对应。

    App 用 TI_13 / SI_11 找回同一元素在另一方向的版本
    （CoverEditPresenter.getChangeRestoreItems）。两边编号不对应会让用户
    切换画布比例后元素跑到错误位置。
    """
    if len(v_items) != len(h_items):
        raise ValueError(
            f"{label}横竖屏数量不一致：竖屏 {len(v_items)} / 横屏 {len(h_items)}。"
            "请确认设计在两个画板放置了相同的元素。")

    # 全局贪心：每次取当前最高分的配对。按竖屏顺序逐个取会因先到先得
    # 而抢走后面元素的最优解（实测会把 25x35 配到 111x119）。
    scored = []
    for i, v in enumerate(v_items):
        for j, h in enumerate(h_items):
            scored.append((_similarity(v, h, vctx, hctx), i, j))
    scored.sort(key=lambda t: -t[0])

    used_v, used_h, mapping = set(), set(), {}
    for _, i, j in scored:
        if i in used_v or j in used_h:
            continue
        used_v.add(i)
        used_h.add(j)
        mapping[i] = j

    return [h_items[mapping[i]] for i in range(len(v_items))]


def align_orientations(result, vcanvas, hcanvas):
    """按竖屏顺序对齐横屏元素，并统一编号。"""
    vtexts = _orient_ctx(result['texts'], vcanvas)
    htexts = _orient_ctx(result['textsH'], hcanvas)
    result['textsH'] = _align_texts(result['texts'], result['textsH'],
                                    vtexts, htexts, '文字')

    vstickers = _orient_ctx(result['stickers'], vcanvas)
    hstickers = _orient_ctx(result['stickersH'], hcanvas)
    result['stickersH'] = _align_pair(result['stickers'], result['stickersH'],
                                      vstickers, hstickers, '贴纸')
    apply_style_numbers(result['texts'], 'TI_13')
    apply_style_numbers(result['textsH'], 'TI_13')
    apply_style_numbers(result['stickers'], 'SI_11')
    apply_style_numbers(result['stickersH'], 'SI_11')
    # 横屏贴纸 SI_1 由 main 在拿到 sticker_dir 后统一重写
    return result


# ---------- 生成 ----------

def scale_box(box, frame, canvas):
    """Figma 画板坐标 → 配置画布坐标"""
    kx = canvas[0] / frame['w']
    ky = canvas[1] / frame['h']
    return {'x': box['x'] * kx, 'y': box['y'] * ky,
            'w': box['w'] * kx, 'h': box['h'] * ky}


def bbox_from_box(box):
    """配置的布局数组：[x,y, x2,y, x2,y2, x,y2, cx,cy]"""
    x, y, w, h = box['x'], box['y'], box['w'], box['h']
    return [x, y, x + w, y, x + w, y + h, x, y + h, x + w / 2, y + h / 2]


def matrix_from_box(box):
    """3x3 仿射矩阵，平移到包围盒左上角"""
    return [1.0, 0.0, box['x'], 0.0, 1.0, box['y'], 0.0, 0.0, 1.0]



def affine_from_boxes(original, current, rotation=0.0, uniform=False):
    """把局部文字框映射到画布框，并绕文字中心保留 Figma 旋转。"""
    ow = original['w'] or 1.0
    oh = original['h'] or 1.0
    sx = current['w'] / ow
    sy = current['h'] / oh
    if uniform:
        sx = sy = max(sx, sy)
    angle = math.radians(rotation)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    a, c = sx * cos_a, -sy * sin_a
    b, d = sx * sin_a, sy * cos_a
    local_cx = original['x'] + ow / 2.0
    local_cy = original['y'] + oh / 2.0
    target_cx = current['x'] + current['w'] / 2.0
    target_cy = current['y'] + current['h'] / 2.0
    tx = target_cx - a * local_cx - c * local_cy
    ty = target_cy - b * local_cx - d * local_cy
    return [a, c, tx, b, d, ty, 0.0, 0.0, 1.0]


def box_from_points(points):
    xs = points[0:8:2]
    ys = points[1:8:2]
    return {'x': min(xs), 'y': min(ys),
            'w': max(xs) - min(xs), 'h': max(ys) - min(ys)}

def build_text_item(bp, el, ctx, frame=None):
    item = json.loads(json.dumps(bp))
    box = ctx['scaled'][id(el)]
    tp = item['TI_9']
    item['TI_1'] = el.raw['chars']
    text_color = rgb_to_int(el.raw.get('color'))
    item['TI_2'] = text_color
    item['TI_9']['TP_8'] = [text_color, text_color]
    item['TI_9']['TP_15'] = el.raw['chars']
    item['TI_6'] = ctx['font_dir'] + '/' + font_file(el.raw['font'], ctx['font_map'])
    item['TI_12'] = ctx['template_num']
    item['_name'] = el.name
    item['_source_id'] = el.raw.get('id', el.name)

    # TI_20 是 Android 文字的局部布局框，不是画布坐标；TI_22 才是
    # Figma 映射后的画布框。局部宽高按 template100 自己的 Figma 框和
    # 当前文字 scale 反推，避免复用 template4 的文字宽度。
    scale = max(0.25, float(el.raw.get('size', 24)) / 48.0)
    local_values = ctx.get('text_local_h' if ctx.get('horizontal') else 'text_local', {}).get(el.raw['chars'])
    if local_values:
        local = {'x': local_values[0], 'y': local_values[1],
                 'w': local_values[2] - local_values[0],
                 'h': local_values[3] - local_values[1]}
    else:
        local = {'x': -46.0, 'y': -46.0,
                 'w': box['w'] / scale, 'h': box['h'] / scale}
    tp['TI_20'] = bbox_from_box(local)
    tp['TI_22'] = bbox_from_box(box)
    matrix = affine_from_boxes(local, box, -el.rot, uniform=True)
    visual_scale = ctx.get('text_visual_scale', {}).get(el.raw['chars'], 1.0)
    visual_offset = ctx.get('text_visual_offset', {}).get(el.raw['chars'], [0.0, 0.0])
    if visual_scale != 1.0:
        cx = box['x'] + box['w'] / 2.0
        cy = box['y'] + box['h'] / 2.0
        matrix[0] *= visual_scale
        matrix[1] *= visual_scale
        matrix[3] *= visual_scale
        matrix[4] *= visual_scale
        matrix[2] = cx - matrix[0] * (local['x'] + local['w'] / 2.0) - matrix[1] * (local['y'] + local['h'] / 2.0)
        matrix[5] = cy - matrix[3] * (local['x'] + local['w'] / 2.0) - matrix[4] * (local['y'] + local['h'] / 2.0)
    matrix[2] += visual_offset[0]
    matrix[5] += visual_offset[1]
    tp['TI_23'] = matrix
    tp['TI_29'] = scale
    tp['TI_19'] = ctx.get('text_line_mult', {}).get(el.raw['chars'], tp.get('TI_19', 1.0))
    alignment = ctx.get('text_align', {}).get(el.raw['chars'])
    if alignment:
        item['TI_4'] = alignment
        tp['TI_26'] = alignment
    item['BI_3'] = scale
    # BaseItem 自己也保存一份局部/当前几何；updatePosition() 使用的是
    # BI_12/BI_13，而不是只读 TextProperty 的 TI_20/TI_22。
    item['BI_12'] = list(tp['TI_20'])
    item['BI_13'] = list(tp['TI_22'])
    item['BI_10'] = list(matrix)
    item['BI_3'] = scale
    tp['TI_27'] = ctx['canvas'][0]
    tp['TI_28'] = ctx['canvas'][1]
    tp['TP_14'] = item['TI_6']
    item['BI_5'] = ctx['canvas'][0]
    item['BI_6'] = ctx['canvas'][1]
    item['BOI_1'] = {'top': 0, 'left': 0,
                     'bottom': ctx['canvas'][1], 'right': ctx['canvas'][0]}
    return item


def build_sticker_item(bp, el, ctx, idx, sticker_no=None, frame=None):
    item = json.loads(json.dumps(bp))
    box = ctx['scaled'][id(el)]
    raw_box = el.box
    adjust, _ = parse_adjust_suffix(el.name)
    no = sticker_no if sticker_no is not None else idx
    item['SI_1'] = f"file://{ctx['sticker_dir']}/template{ctx['template_num']}_sticker{no}.png"
    # SI_3/SI_4 是贴纸位图本身尺寸，SI_6 是当前画布位置。
    item['SI_3'] = round(raw_box['w'], 3)
    item['SI_4'] = round(raw_box['h'], 3)
    item['SI_5'] = bbox_from_box({'x': 0, 'y': 0, 'w': raw_box['w'], 'h': raw_box['h']})
    item['SI_6'] = bbox_from_box(box)
    original = box_from_points(item['SI_5'])
    matrix = affine_from_boxes(original, box)
    item['SI_2'] = matrix
    item['SI_10'] = ctx['template_num']
    item['BI_12'] = list(item['SI_5'])
    item['BI_13'] = list(item['SI_6'])
    item['BI_10'] = list(matrix)
    item['BI_3'] = matrix[0]
    item['_name'] = el.name
    item['_source_id'] = el.raw.get('id', el.name)
    item['SI_12'] = adjust
    item['BI_5'] = ctx['canvas'][0]
    item['BI_6'] = ctx['canvas'][1]
    item['BOI_1'] = {'top': 0, 'left': 0,
                     'bottom': ctx['canvas'][1], 'right': ctx['canvas'][0]}
    return item


def apply_style_numbers(items, key):
    """写入方向内的样式序号（文字 TI_13 / 贴纸 SI_11）。

    App 用它在切换画布比例时找回同一元素在另一方向的版本，
    横竖屏必须一一对应，否则元素会跑到错误位置。
    """
    for i, it in enumerate(items, 1):
        it[key] = i
    return items


def build(dump, blueprint, meta, canvas=None, horizontal=False):
    frame = dump['frame']
    if canvas is None:
        canvas = tuple(meta.get('canvas', DEFAULT_CANVAS))
    canvas = tuple(canvas)
    elements = [Element(e) for e in dump['elements']]

    if meta.get('include'):
        keep = set(meta['include'])
        elements = [e for e in elements if e.name in keep or e.group in keep]

    elements, dropped = drop_background(elements, frame)
    elements = group_texts(elements)
    split_texts = set(meta.get('splitTexts', []))
    expanded = []
    for e in elements:
        parts = e.raw.get('_parts')
        if parts and split_texts and any(p.get('chars', '').strip() in split_texts for p in parts):
            expanded.extend(Element(dict(p, chars=p.get('chars', '').strip())) for p in parts)
        else:
            expanded.append(e)
    elements = expanded

    ctx = {'canvas': canvas, 'template_num': meta['templateNum'],
           'font_map': meta.get('fonts', {}), 'font_dir': meta.get('fontDir', ''),
           'sticker_dir': meta.get('stickerDir', ''),
           'text_local': meta.get('textLocal', {}),
           'text_local_h': meta.get('textLocalH', {}),
           'text_visual_scale': meta.get('textVisualScale', {}),
           'text_visual_offset': meta.get('textVisualOffset', {}),
           'text_line_mult': meta.get('textLineMult', {}),
           'text_align': meta.get('textAlign', {}),
           'horizontal': canvas[1] < canvas[0],
           'scaled': {id(e): scale_box(e.box, frame, canvas) for e in elements}}

    texts = [build_text_item(blueprint['text'], e, ctx, frame=frame)
             for e in elements if e.kind == 'text']
    stickers = [build_sticker_item(blueprint['sticker'], e, ctx, i + 1, frame=frame)
                for i, e in enumerate([e for e in elements if e.kind == 'image'])]
    return {'texts': apply_style_numbers(texts, 'TI_13'),
            'stickers': apply_style_numbers(stickers, 'SI_11'),
            '_dropped': [e.name for e in dropped],
            '_merged_sources': [{'text': e.raw.get('chars'), 'source_ids': [p.get('id', p.get('name')) for p in e.raw['_parts']]}
                                for e in elements if e.raw.get('_parts')]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--figma', required=True, help='竖屏 dump json')
    ap.add_argument('--figma-h', required=True, help='横屏 dump json')
    ap.add_argument('--blueprint', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    try:
        output = new_output(a.out)
        blueprint, meta = load_json(a.blueprint), load_json(a.meta)
        vd, hd = load_json(a.figma), load_json(a.figma_h)
        if type(meta.get('templateNum')) is not int or meta['templateNum'] < 1:
            raise ValueError('templateNum 须为已确认的正整数')
        for key in ('fontDir', 'stickerDir'):
            value = meta.get(key)
            if not isinstance(value, str) or not value.startswith('/') or '..' in Path(value).parts:
                raise ValueError(key+' 须显式提供已核对的设备路径，不猜项目默认值')
        fonts = meta.get('fonts')
        if not isinstance(fonts, dict):
            raise ValueError('须提供明确的 fonts 字体映射')
        vcanvas = tuple(meta.get('canvas', DEFAULT_CANVAS))
        hcanvas = tuple(meta.get('canvasH', DEFAULT_CANVAS_H))
        for canvas in (vcanvas, hcanvas):
            if len(canvas) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in canvas):
                raise ValueError('画布须为两个正有限数值')
        for dump in (vd, hd):
            frame = dump['frame']
            if any(type(frame[k]) not in (int, float) or not math.isfinite(frame[k]) or frame[k] <= 0 for k in ('w', 'h')):
                raise ValueError('Figma 画板尺寸无效')
            for raw in dump['elements']:
                if raw.get('kind') not in ('text', 'image'):
                    raise ValueError('存在尚未支持的元素类型')
                box = raw['box']
                if any(type(box[k]) not in (int, float) or not math.isfinite(box[k]) for k in ('x', 'y', 'w', 'h')) or box['w'] <= 0 or box['h'] <= 0:
                    raise ValueError('元素须有正尺寸和有限位置，不能用零尺寸参与配对')
                if raw.get('kind') == 'text':
                    if raw.get('font') not in fonts:
                        raise ValueError('缺少实际字体映射：'+str(raw.get('font')))
                    filename = fonts[raw['font']]
                    if asset_name(filename, 'font') != filename:
                        raise ValueError('fonts 映射值须为实际字体文件名，不是路径')
        result = build(vd, blueprint, meta, canvas=vcanvas)
        horizontal = build(hd, blueprint, meta, canvas=hcanvas)
        merged = dict(vertical=result.pop('_merged_sources'), horizontal=horizontal.pop('_merged_sources'))
        dropped = dict(vertical=result.pop('_dropped'), horizontal=horizontal.pop('_dropped'))
        result['textsH'], result['stickersH'] = horizontal['texts'], horizontal['stickers']
        align_orientations(result, vcanvas, hcanvas)
        for index, item in enumerate(result['stickersH'], 1):
            item['SI_1'] = f"file://{meta['stickerDir']}/template{meta['templateNum']}_sticker{index}.png"
        pairs = {}
        for group, other in [('texts', 'textsH'), ('stickers', 'stickersH')]:
            pairs[group] = [{'style': index, 'vertical_source': v['_source_id'], 'horizontal_source': h['_source_id']}
                            for index, (v, h) in enumerate(zip(result[group], result[other]), 1)]
        for group in ('texts', 'textsH', 'stickers', 'stickersH'):
            for item in result[group]:
                item.pop('_name', None)
                item.pop('_source_id', None)
        validate_config(result, meta['templateNum'])
        output.mkdir(parents=True, exist_ok=False)
        path = output/f"cover_template_item_config_{meta['templateNum']}.json"
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        report = dict(dropped_candidates=dropped, dropped_reason='启发式：元素宽/高达到画板98%，或超过102%；不能据此判定业务语义',
                      merged_sources=merged, orientation_pairs=pairs,
                      source_warnings={'vertical': vd.get('warnings', []), 'horizontal': hd.get('warnings', [])},
                      scope='背景尺寸过滤、文字合并与贴纸几何配对均为启发式候选；需逐项核对，未证明视觉或当前客户端兼容')
        with (output/'conversion_report.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(path)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
