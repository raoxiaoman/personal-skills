#!/usr/bin/env python3
"""回归用例。

真值来源：template29 同时有 Figma 源文件（节点 1096:8）和线上配置，
是唯一可做真值对拍的样本。断言只覆盖已验证精确的项。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, 'scripts'))
sys.path.insert(0, HERE)

import build_config as bc
from shemei1_data import (VERTICAL, HORIZONTAL, VERTICAL_STICKERS,
                          HORIZONTAL_STICKERS, sticker_identity)

FONT_DIR = '/data/user/0/x/files/Video.Guru/.store/Font'

# 足球1（Figma 1096:8）抓取结果：按「含图形的组整体作为素材单元」策略
FOOTBALL1 = {
    "frame": {"id": "1096:8", "name": "足球1 1", "w": 600, "h": 800},
    "elements": [
        # 几个文字：同组（Play-hard）的应合并，其余各自独立
        {"kind": "text", "id": "t1", "name": "FINAL-MATCH", "box": {"x": 24.5, "y": 18, "w": 91, "h": 25},
         "rot": 0, "chars": "FINAL MATCH", "font": "Bebas:Regular", "size": 21,
         "align": "LEFT", "color": {"r": 179, "g": 228, "b": 87}},
        {"kind": "text", "id": "t2", "name": "PLAY HARD", "box": {"x": 503.6, "y": 18, "w": 75, "h": 25},
         "rot": 0, "chars": "PLAY HARD ", "font": "Bebas:Regular", "size": 21,
         "align": "LEFT", "color": {"r": 179, "g": 228, "b": 87}},
        {"kind": "text", "id": "t3", "name": "STAY LEGENDARY", "box": {"x": 463.9, "y": 43, "w": 117, "h": 25},
         "rot": 0, "chars": "STAY LEGENDARY", "font": "Bebas:Regular", "size": 21,
         "align": "LEFT", "color": {"r": 179, "g": 228, "b": 87}},
        {"kind": "text", "id": "t4", "name": "DATE", "box": {"x": 199.1, "y": 734, "w": 211, "h": 22},
         "rot": 0, "chars": "9:30 AM EDT", "font": "Anton:Regular", "size": 18,
         "align": "LEFT", "color": {"r": 255, "g": 255, "b": 255}},
        # 背景/遮罩：应被剔除
        {"kind": "image", "id": "bg1", "name": "Vector", "nodeType": "VECTOR",
         "box": {"x": 0, "y": 0, "w": 600, "h": 800}, "rot": 0},
        {"kind": "image", "id": "bg2", "name": "photo", "nodeType": "RECTANGLE",
         "box": {"x": -161.5, "y": -219.5, "w": 944.1, "h": 1143}, "rot": 0},
        {"kind": "image", "id": "bg3", "name": "矩形", "nodeType": "VECTOR",
         "box": {"x": 0, "y": 650, "w": 600, "h": 150}, "rot": 0},
        # 足球贴纸：抓取时已聚合为一个单元
        {"kind": "image", "id": "ball", "name": "编组", "group": "编组",
         "nodeType": "GROUP", "box": {"x": 452, "y": 660, "w": 103, "h": 61}, "rot": 0},
    ],
}

META = {"templateNum": 29, "canvas": [961, 1282], "fontDir": FONT_DIR,
        "fonts": {"Bebas:Regular": "Bebas-Regular.otf", "Anton:Regular": "Anton-Regular.ttf"}}

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}\n      得到 {got!r}\n      期望 {want!r}")


def main():
    bp = json.load(open(os.path.join(SKILL, 'reference', 'blueprint.json')))
    r = bc.build(json.loads(json.dumps(FOOTBALL1)), bp, META)

    print("元素数量与合并规则")
    check("文字数（同段合并后）", len(r['texts']), 3)
    check("贴纸数", len(r['stickers']), 1)

    print("文字合并（按位置，不依赖分组）")
    contents = sorted(t['TI_1'] for t in r['texts'])
    check("合并结果", contents, ['9:30 AM EDT', 'FINAL MATCH', 'PLAY HARD\nSTAY LEGENDARY'])

    print("颜色换算（精确）")
    by_text = {t['TI_1']: t['TI_2'] for t in r['texts']}
    check("绿色 rgb(179,228,87)", by_text['FINAL MATCH'], -4987817)
    check("白色", by_text['9:30 AM EDT'], -1)

    print("字体映射（精确）")
    fonts = {t['TI_1']: t['TI_6'] for t in r['texts']}
    check("Bebas:Regular", fonts['FINAL MATCH'], FONT_DIR + "/Bebas-Regular.otf")
    check("Anton:Regular", fonts['9:30 AM EDT'], FONT_DIR + "/Anton-Regular.ttf")

    print("背景剔除")
    check("只有 1 个贴纸（背景全剔除）", len(r['stickers']), 1)
    check("画布宽", r['texts'][0]['TI_9']['TI_27'], 961)
    check("画布高", r['texts'][0]['TI_9']['TI_28'], 1282)

    print("位置换算（画布 961x1282 / 画板 600x800 = 1.6017）")
    cx = by_idx = {t['TI_1']: t['TI_9']['TI_22'][8] for t in r['texts']}
    check("FINAL MATCH 中心 x ≈ 112.1", abs(cx['FINAL MATCH'] - 112.1) < 0.5, True)
    st = r['stickers'][0]
    check("贴纸原始宽", round(st['SI_3'], 1), 103.0)
    check("贴纸原始高", round(st["SI_4"], 1), 61.0)

    print("横竖屏一致性（社媒1 真实数据）")
    # 设计在横屏未给 Scrapbook/time/good/food 分组；按分组合并会得到
    # 竖屏 4 个、横屏 6 个文字，切换画布比例时模板重匹配会错位。
    v = bc.group_texts([bc.Element(e) for e in VERTICAL])
    h = bc.group_texts([bc.Element(e) for e in HORIZONTAL])
    expect = ['Scrapbook\ntime', 'good\nfood', 'more\ncoffee', 'one day\nin my life']
    check("横竖屏文字数一致", len(v) == len(h), True)
    check("竖屏合并结果", sorted(e.raw['chars'] for e in v), expect)
    check("横屏合并结果", sorted(e.raw['chars'] for e in h), expect)

    print("贴纸横竖屏匹配（社媒1 真实数据，设计命名不一致）")
    # 横竖屏画板尺寸不同（600x800 / 800x450），缩放比例也不同（1.79 / 1.35），
    # 必须用相对尺寸匹配；用绝对尺寸会把 11x14 认成 15x18。
    vcanvas, hcanvas = (1075, 1434), (1080, 610)

    def to_cfg(rows, figma_wh, canvas):
        fw, fh = figma_wh
        out = []
        for label, w, h, x, y in rows:
            box = {"x": x * canvas[0] / fw, "y": y * canvas[1] / fh,
                   "w": w * canvas[0] / fw, "h": h * canvas[1] / fh}
            out.append({"_id": label, "SI_6": bc.bbox_from_box(box)})
        return out

    vs = to_cfg(VERTICAL_STICKERS, (600, 800), vcanvas)
    hs = to_cfg(HORIZONTAL_STICKERS, (800, 450), hcanvas)
    vctx = bc._orient_ctx(vs, vcanvas)
    hctx = bc._orient_ctx(hs, hcanvas)
    matched = bc._align_pair(vs, hs, vctx, hctx, '贴纸')
    pairs = [(vs[i]['_id'], sticker_identity(m['_id'])) for i, m in enumerate(matched)]
    wrong = [f"{a}→{b}" for a, b in pairs if a != b]
    check("12 个贴纸全部配对正确", wrong, [])

    print("相邻但不同的文字不应合并")
    # 同字体同颜色但水平错开较远（FINAL MATCH 与 SCORE 在画板两端）
    texts = [
        {"kind": "text", "name": "A", "box": {"x": 24.5, "y": 18, "w": 91, "h": 25}, "rot": 0,
         "chars": "FIRST", "font": "Bebas:Regular", "size": 21, "align": "LEFT",
         "color": {"r": 179, "g": 228, "b": 87}},
        {"kind": "text", "name": "B", "box": {"x": 278.7, "y": 18, "w": 44, "h": 25}, "rot": 0,
         "chars": "SECOND", "font": "Bebas:Regular", "size": 21, "align": "LEFT",
         "color": {"r": 179, "g": 228, "b": 87}},
    ]
    check("水平错开较远不合并", len(bc.group_texts([bc.Element(e) for e in texts])), 2)

    print("贴边属性")
    check("无后缀 → 0", st['SI_12'], 0)
    check("@top → 1", bc.parse_adjust_suffix("书@top"), (1, "书"))
    check("@full → 9", bc.parse_adjust_suffix("花@full")[0], 9)
    check("@bottom → 2", bc.parse_adjust_suffix("x@bottom")[0], 2)
    check("未知后缀 → 0", bc.parse_adjust_suffix("x@zzz")[0], 0)

    print(f"\n通过 {passed} / 失败 {failed}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
