"""社媒1 真实 Figma 数据（文字部分），用于回归。

竖屏画板 1088:4361，横屏画板 1088:4303。
注意：设计在横屏未给 Scrapbook/time/good/food 分组，与竖屏不一致。
"""

BOLD_LIGHT = {"r": 250, "g": 240, "b": 228}
REG_WHITE = {"r": 255, "g": 248, "b": 240}
BOLD_BROWN = {"r": 114, "g": 83, "b": 73}


def _t(name, x, y, w, h, rot, font, color):
    return {"kind": "text", "name": name, "group": None, "groupTextOnly": False,
            "box": {"x": x, "y": y, "w": w, "h": h}, "rot": rot, "chars": name,
            "font": font, "size": 24, "align": "LEFT", "color": color}


VERTICAL = [
    _t("more", 499.8, 194.5, 47, 40.4, 17, "Caveat:Bold", BOLD_LIGHT),
    _t("coffee", 506.8, 215.7, 52.8, 42.1, 17, "Caveat:Bold", BOLD_LIGHT),
    _t("one day", 203.6, 321.9, 190.7, 112.4, 7, "Caveat:Regular", REG_WHITE),
    _t("in my life", 211.5, 381.7, 229.5, 117.1, 7, "Caveat:Regular", REG_WHITE),
    _t("Scrapbook", 98.3, 97.5, 91, 53.8, 17, "Caveat:Bold", BOLD_BROWN),
    _t("time", 105.3, 133.3, 48.9, 41, 17, "Caveat:Bold", BOLD_BROWN),
    _t("good", 125.3, 652.1, 43.2, 39.2, 17, "Caveat:Bold", BOLD_BROWN),
    _t("food", 132.3, 675.4, 42.2, 38.9, 17, "Caveat:Bold", BOLD_BROWN),
]

HORIZONTAL = [
    _t("one day", 264.6, 179.9, 190.7, 112.4, 7, "Caveat:Regular", REG_WHITE),
    _t("in my life", 272.5, 239.7, 229.5, 117.1, 7, "Caveat:Regular", REG_WHITE),
    _t("Scrapbook", 227.3, 20.5, 91, 53.8, 17, "Caveat:Bold", BOLD_BROWN),
    _t("time", 234.3, 56.3, 48.9, 41, 17, "Caveat:Bold", BOLD_BROWN),
    _t("good", 76.3, 375.1, 43.2, 39.2, 17, "Caveat:Bold", BOLD_BROWN),
    _t("food", 83.3, 398.4, 42.2, 38.9, 17, "Caveat:Bold", BOLD_BROWN),
    _t("more", 624.8, 71.5, 47, 40.4, 17, "Caveat:Bold", BOLD_LIGHT),
    _t("coffee", 631.8, 92.7, 52.8, 42.1, 17, "Caveat:Bold", BOLD_LIGHT),
]


# ---- 贴纸：横竖屏匹配回归 ----
# 元组：(图元标识, Figma宽, Figma高, Figma x, Figma y)
# 设计在横竖屏给同一素材起了不同名字（形状备份-7 vs 形状备份-8），
# 且排版不同导致尺寸与位置都变，只能靠「相对尺寸 + 名字主干 + 归一化位置」匹配。
VERTICAL_STICKERS = [
    ("星星", 11, 14, 561, 232),
    ("装饰A", 14.4, 29.3, 544.3, 253.6),
    ("餐盘", 155, 130, 122, 534),
    ("书本", 190.4, 175.3, 25.1, 181.7),
    ("闪光大", 35.8, 40.1, 429.1, 474),
    ("爱心A", 25, 35, 540, 411),
    ("爱心B", 14, 18, 178, 680),
    ("爱心C", 15, 18, 156, 137),
    ("下划线", 172.9, 62.9, 243.1, 463),
    ("装饰B", 14.4, 29.3, 125.6, 634.9),
    ("装饰C", 13.3, 29.3, 104.7, 164.6),
    ("咖啡杯", 111, 119, 455, 239),
]
HORIZONTAL_STICKERS = [
    ("爱心C@横", 15, 18, 285, 60),
    ("下划线@横", 172.9, 62.9, 311.1, 312),
    ("书本@横", 175.5, 175.5, 146.7, 75.3),
    ("装饰C@横", 13.3, 29.3, 227, 97),
    ("爱心B@横", 14, 18, 129, 403),
    ("装饰B@横", 14.4, 29.3, 76.6, 357.9),
    ("星星@横", 11, 14, 686, 109),
    ("装饰A@横", 14.4, 29.3, 669.3, 130.6),
    ("爱心A@横", 25, 35, 536, 229),
    ("闪光大@横", 35.8, 40.1, 491.1, 309),
    ("咖啡杯@横", 111, 119, 580, 116),
    ("餐盘@横", 127, 106.5, 81, 270),
]


def sticker_identity(label):
    """去掉 @横 后缀，得到与竖屏一致的图元标识"""
    return label.replace('@横', '')
