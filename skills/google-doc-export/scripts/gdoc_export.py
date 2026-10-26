#!/usr/bin/env python3
"""
gdoc_export.py — 从已导出的 Google Doc 文件中提取文本与图片。
用法：
    python3 ~/.claude/skills/google-doc-export/scripts/gdoc_export.py --txt .playwright-mcp/V1-650-AI-Trim.txt \
        --docx .playwright-mcp/V1-650-AI-Trim.docx \
        --out docs/ai-trim-assets
"""
import argparse
import os
import zipfile
from xml.etree import ElementTree as ET


# ── 提取 txt 文本 ───────────────────────────────────────────────
def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# ── 从 docx 提取图片 ───────────────────────────────────────────
def extract_images(docx_path: str, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            if name.startswith("word/media/"):
                target = os.path.join(out_dir, os.path.basename(name))
                with open(target, "wb") as f:
                    f.write(z.read(name))
                saved.append(target)
    return saved


# ── 从 docx 解析段落与图片的位置关系 ────────────────────────────
def extract_paragraphs_with_images(docx_path: str) -> list[dict]:
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    }

    with zipfile.ZipFile(docx_path) as z:
        rels_root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
        rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels_root}

        body = ET.fromstring(z.read("word/document.xml")).find("w:body", ns)

    results = []
    for child in list(body):
        tag = child.tag.split("}")[-1]
        if tag != "p":
            continue

        texts = [t.text or "" for t in child.findall(".//w:t", ns)]
        full_text = "".join(texts).strip()

        image_refs = []
        for blip in child.findall(".//a:blip", ns):
            rid = blip.attrib.get(f'{{{ns["r"]}}}embed')
            if rid:
                image_refs.append(rel_map.get(rid, rid))

        if full_text or image_refs:
            results.append({"text": full_text, "images": image_refs})

    return results


# ── 主入口 ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="提取 Google Doc 导出文件的内容与图片")
    parser.add_argument("--txt", required=True, help="导出的 txt 文件路径")
    parser.add_argument("--docx", required=True, help="导出的 docx 文件路径")
    parser.add_argument("--out", required=True, help="图片输出目录")
    args = parser.parse_args()

    text = read_text(args.txt)
    print("=" * 60)
    print("【文本内容】")
    print("=" * 60)
    print(text)
    print()

    images = extract_images(args.docx, args.out)
    print("=" * 60)
    print(f"【提取图片】共 {len(images)} 张")
    print("=" * 60)
    for img in images:
        size_kb = os.path.getsize(img) // 1024
        print(f"  - {img}  ({size_kb}KB)")
    print()

    paragraphs = extract_paragraphs_with_images(args.docx)
    print("=" * 60)
    print("【段落与图片映射】")
    print("=" * 60)
    for i, p in enumerate(paragraphs):
        prefix = f"  [{i:3d}]"
        if p["text"]:
            preview = p["text"][:80]
            print(f"{prefix} 文字: {preview}")
        if p["images"]:
            for img_ref in p["images"]:
                print(f"{prefix} 图片: {img_ref}")

    print()
    print("=" * 60)
    print("【使用提示】")
    print("=" * 60)
    print(f"  文本已导出到控制台，图片已保存到 {args.out}/")
    print("  请将上述文本和图片整理为项目内需求文档。")


if __name__ == "__main__":
    main()