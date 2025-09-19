#!/usr/bin/env python3
"""
exif_watermarker_min.py
最简命令行交互版（修复 text size 兼容问题）：
- 控制台提示输入路径与选项
- 读取 EXIF 日期（优先 DateTimeOriginal），取 YYYY-MM-DD 作为水印
- 支持字体大小、颜色、位置
- 输出到 原目录/<dirname>_watermark 下，文件名追加 _wm
"""

import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ExifTags

# 尝试导入 piexif（可选）
try:
    import piexif  # type: ignore
    HAVE_PIEXIF = True
except Exception:
    HAVE_PIEXIF = False

def input_nonempty(prompt: str, default: str = "") -> str:
    s = input(f"{prompt} " + (f"[默认: {default}] " if default else ""))
    return s.strip() or default

def list_images_in_dir(d: str):
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    files = []
    try:
        for name in os.listdir(d):
            full = os.path.join(d, name)
            if os.path.isfile(full) and os.path.splitext(name.lower())[1] in exts:
                files.append(full)
    except Exception:
        pass
    return sorted(files)

def format_exif_raw(raw):
    if not raw or not isinstance(raw, str):
        return None
    date_part = raw.strip().split(" ")[0]
    parts = date_part.replace("-", ":").split(":")
    if len(parts) >= 3:
        try:
            y, m, d = parts[0:3]
            return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except Exception:
            return None
    return None

def get_date_from_piexif(path):
    if not HAVE_PIEXIF:
        return None
    try:
        exif = piexif.load(path)
        date_bytes = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if date_bytes:
            raw = date_bytes.decode() if isinstance(date_bytes, (bytes, bytearray)) else str(date_bytes)
            return format_exif_raw(raw)
        date0 = exif.get("0th", {}).get(piexif.ImageIFD.DateTime)
        if date0:
            raw = date0.decode() if isinstance(date0, (bytes, bytearray)) else str(date0)
            return format_exif_raw(raw)
    except Exception:
        return None
    return None

def get_date_from_pillow(path):
    try:
        with Image.open(path) as img:
            exif = img._getexif()
            if not exif:
                return None
            tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            for tname in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
                tag = tag_map.get(tname)
                if tag and tag in exif and exif[tag]:
                    raw = exif[tag]
                    return format_exif_raw(raw)
    except Exception:
        return None
    return None

def get_date_string(path):
    # 优先 piexif -> pillow -> 文件修改时间回退
    if HAVE_PIEXIF:
        d = get_date_from_piexif(path)
        if d:
            return d
    d = get_date_from_pillow(path)
    if d:
        return d
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except Exception:
        return None

def parse_color(s):
    s = (s or "").strip()
    if s.startswith("#") and len(s) == 7:
        return tuple(int(s[i:i+2], 16) for i in (1,3,5))
    names = {
        "white": (255,255,255),
        "black": (0,0,0),
        "red": (255,0,0),
        "yellow": (255,255,0),
        "blue": (0,0,255),
        "green": (0,128,0),
    }
    return names.get(s.lower(), (255,255,255))

def compute_font_px(spec, img_w):
    try:
        val = float(spec)
        if val >= 1:
            return int(val)
        if 0 < val < 1:
            return max(12, int(img_w * val))
    except Exception:
        pass
    return 36

def calc_pos(pos_name, img_size, text_size, margin=10):
    iw, ih = img_size; tw, th = text_size
    if pos_name == "top-left":
        return (margin, margin)
    if pos_name == "top-right":
        return (iw - tw - margin, margin)
    if pos_name == "bottom-left":
        return (margin, ih - th - margin)
    if pos_name == "center":
        return ((iw - tw)//2, (ih - th)//2)
    return (iw - tw - margin, ih - th - margin)  # bottom-right default

def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    """
    通用计算文本尺寸：
    - 优先使用 draw.textbbox (Pillow 新版)
    - 回退到 font.getsize 或 draw.textsize
    返回 (width, height)
    """
    try:
        # textbbox 返回 (left, top, right, bottom)
        bbox = draw.textbbox((0,0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        return (w, h)
    except Exception:
        pass
    try:
        # font.getsize 在许多 Pillow 版本可用
        return font.getsize(text)
    except Exception:
        pass
    try:
        return draw.textsize(text, font=font)
    except Exception:
        # 最后保底
        return (len(text) * 8, 16)

def process_image(path, out_dir, font_path, font_spec, color_str, pos_name):
    date_text = get_date_string(path)
    if not date_text:
        print(f"  跳过（无法获取日期）: {path}")
        return False
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            font_px = compute_font_px(font_spec, w)
            try:
                if font_path and os.path.isfile(font_path):
                    font = ImageFont.truetype(font_path, font_px)
                else:
                    font = ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
            draw = ImageDraw.Draw(im)
            tw, th = _measure_text(draw, date_text, font)
            x, y = calc_pos(pos_name, (w,h), (tw,th))
            outline_color = (0,0,0)
            # 描边（简单4方向）
            for dx, dy in [(-1,-1),(-1,1),(1,-1),(1,1)]:
                draw.text((x+dx, y+dy), date_text, font=font, fill=outline_color)
            draw.text((x, y), date_text, font=font, fill=parse_color(color_str))
            # 保存
            base = os.path.basename(path)
            name, ext = os.path.splitext(base)
            out_name = f"{name}_wm{ext}"
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, out_name)
            if ext.lower() in [".jpg", ".jpeg"]:
                im.convert("RGB").save(out_path, quality=95)
            else:
                im.save(out_path)
            print(f"  已保存: {out_path}")
            return True
    except Exception as e:
        print(f"  处理错误: {path} => {e}")
        return False

def main():
    print("== 简易图片 EXIF 日期水印工具 ==")
    path = input_nonempty("请输入图片文件路径或目录路径：")
    if not path:
        print("未输入路径，退出。")
        return
    path = os.path.abspath(path)
    if not os.path.exists(path):
        print("路径不存在，退出。")
        return

    font_spec = input_nonempty("请输入字体大小（像素或相对比例如 0.04 表示宽度的4%），回车使用默认 0.04：", "0.04")
    color = input_nonempty("请输入文字颜色（#RRGGBB 或 white/black/...），回车使用默认 #FFFFFF：", "#FFFFFF")
    pos = input_nonempty("请输入水印位置（top-left/top-right/center/bottom-left/bottom-right），回车使用默认 bottom-right：", "bottom-right")
    font_path = input_nonempty("如需使用自定义字体请输入 ttf 文件路径，否则回车跳过：", "")

    # 收集图片
    if os.path.isfile(path):
        image_list = [path]
        parent_dir = os.path.dirname(path)
        base_dirname = os.path.basename(parent_dir)
        out_dir = os.path.join(parent_dir, base_dirname + "_watermark")
    else:
        image_list = list_images_in_dir(path)
        if not image_list:
            print("目录中没有找到支持的图片文件，退出。")
            return
        base_dirname = os.path.basename(os.path.abspath(path))
        out_dir = os.path.join(os.path.abspath(path), base_dirname + "_watermark")  # 子目录

    print(f"共找到 {len(image_list)} 张图片，输出目录：{out_dir}")
    success = 0
    for i, img in enumerate(image_list, 1):
        print(f"[{i}/{len(image_list)}] 处理: {img}")
        if process_image(img, out_dir, font_path, font_spec, color, pos):
            success += 1

    print(f"完成：共 {len(image_list)} 张，处理成功 {success} 张，输出保存在 {out_dir}")

if __name__ == "__main__":
    main()
