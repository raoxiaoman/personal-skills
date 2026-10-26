#!/usr/bin/env python3
"""可被 unittest discover 自动发现的封面模板回归测试。"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL / "scripts"))

import build_config as bc


class CoverTemplateRegressionTests(unittest.TestCase):
    def test_rgb_to_android_argb(self):
        self.assertEqual(bc.rgb_to_int({"r": 179, "g": 228, "b": 87}), -4987817)
        self.assertEqual(bc.rgb_to_int({"r": 255, "g": 255, "b": 255}), -1)

    def test_adjust_suffix_keeps_sticker_semantics(self):
        self.assertEqual(bc.parse_adjust_suffix("书@top"), (1, "书"))
        self.assertEqual(bc.parse_adjust_suffix("花@full"), (9, "花"))
        self.assertEqual(bc.parse_adjust_suffix("coffee@bottom"), (2, "coffee"))
        self.assertEqual(bc.parse_adjust_suffix("arrow"), (0, "arrow"))

    def test_texts_with_same_style_and_overlap_merge_in_y_order(self):
        rows = [
            {"kind": "text", "name": "second", "box": {"x": 10, "y": 30, "w": 60, "h": 20},
             "rot": 0, "chars": "SECOND", "font": "Caveat:Regular", "size": 24,
             "align": "LEFT", "color": {"r": 255, "g": 255, "b": 255}},
            {"kind": "text", "name": "first", "box": {"x": 10, "y": 5, "w": 60, "h": 20},
             "rot": 0, "chars": "FIRST", "font": "Caveat:Regular", "size": 24,
             "align": "LEFT", "color": {"r": 255, "g": 255, "b": 255}},
        ]
        grouped = bc.group_texts([bc.Element(row) for row in rows])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].raw["chars"], "FIRST\nSECOND")

    def test_texts_far_apart_do_not_merge(self):
        rows = [
            {"kind": "text", "name": "left", "box": {"x": 0, "y": 0, "w": 30, "h": 20},
             "rot": 0, "chars": "LEFT", "font": "Caveat:Regular", "size": 24,
             "align": "LEFT", "color": {"r": 255, "g": 255, "b": 255}},
            {"kind": "text", "name": "right", "box": {"x": 200, "y": 0, "w": 30, "h": 20},
             "rot": 0, "chars": "RIGHT", "font": "Caveat:Regular", "size": 24,
             "align": "LEFT", "color": {"r": 255, "g": 255, "b": 255}},
        ]
        self.assertEqual(len(bc.group_texts([bc.Element(row) for row in rows])), 2)

    def test_orientation_matching_uses_relative_geometry(self):
        vertical = [{"_id": "arrow", "SI_6": bc.bbox_from_box({"x": 10, "y": 20, "w": 17, "h": 32})}]
        horizontal = [{"_id": "arrow@h", "SI_6": bc.bbox_from_box({"x": 20, "y": 10, "w": 17, "h": 32})}]
        vctx = bc._orient_ctx(vertical, (1075, 1434))
        hctx = bc._orient_ctx(horizontal, (1080, 610))
        matched = bc._align_pair(vertical, horizontal, vctx, hctx, "贴纸")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["_id"], "arrow@h")


if __name__ == "__main__":
    unittest.main()

class PackagingRegressionTests(unittest.TestCase):
    def _config(self, root, sticker_name="template7_sticker1.png"):
        config = {
            "texts": [{"TI_1": "title", "TI_6": "/font/Test.ttf", "TI_12": 7, "TI_13": 1}],
            "stickers": [{"SI_1": f"file:///sticker/{sticker_name}", "SI_10": 7, "SI_11": 1}],
            "textsH": [{"TI_1": "title", "TI_6": "/font/Test.ttf", "TI_12": 7, "TI_13": 1}],
            "stickersH": [{"SI_1": f"file:///sticker/{sticker_name}", "SI_10": 7, "SI_11": 1}],
        }
        path = root / "cover_template_item_config_7.json"
        path.write_text(__import__("json").dumps(config), encoding="utf-8")
        return path

    def test_packaging_keeps_config_sticker_number_and_required_assets(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            stickers = root / "stickers"
            fonts = root / "fonts"
            stickers.mkdir(); fonts.mkdir()
            (stickers / "template7_sticker1.png").write_bytes(b"png")
            (fonts / "Test.ttf").write_bytes(b"font")
            (root / "cover.webp").write_bytes(b"cover")
            out = root / "package"
            subprocess.run([
                sys.executable, '-I', '-B', str(SKILL / "scripts" / "package_template.py"),
                "--config", str(config), "--stickers", str(stickers),
                "--fonts", str(fonts), "--cover", str(root / "cover.webp"),
                "--template-num", "7", "--out", str(out),
            ], check=True, capture_output=True, text=True)
            import zipfile
            with zipfile.ZipFile(out / "template7.zip") as archive:
                self.assertEqual(set(archive.namelist()), {
                    "cover_template_item_config_7.json", "template7_sticker1.png", "Test.ttf"
                })

    def test_packaging_rejects_sticker_from_another_template(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root, "template8_sticker1.png")
            stickers = root / "stickers"; fonts = root / "fonts"
            stickers.mkdir(); fonts.mkdir()
            (stickers / "template8_sticker1.png").write_bytes(b"png")
            (fonts / "Test.ttf").write_bytes(b"font")
            (root / "cover.webp").write_bytes(b"cover")
            result = subprocess.run([
                sys.executable, '-I', '-B', str(SKILL / "scripts" / "package_template.py"),
                "--config", str(config), "--stickers", str(stickers),
                "--fonts", str(fonts), "--cover", str(root / "cover.webp"),
                "--template-num", "7", "--out", str(root / "package"),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("错误编号贴纸", result.stderr + result.stdout)
