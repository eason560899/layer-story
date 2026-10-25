"""Publish a layer-identification guide and schematic animation from rendered layers.

Only the supplied layer order, images, labels and optional author notes are used.
This module does not infer physical assembly steps, material thickness or geometry.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as PDFImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


INK = "#19362F"
MUTED = "#60736C"
PAPER = "#F6F3EC"
MATTE = "#E8E9E3"
LINE = "#D5DCD3"
ACCENT = "#D6E889"
WHITE = "#FFFFFF"

COPY = {
    "en": {
        "edition": "LAYER STORY",
        "overview": "Layer reference",
        "order": "BACK TO FRONT",
        "order_help": "Layer 01 is the back. The highest number is the front.",
        "scope": "Layer-order reference only. Spacing in the animation is schematic.",
        "layer": "LAYER",
        "piece": "This layer",
        "combined": "Layers 01 through {number}",
        "note": "Author's note",
        "reference": "Use the author's project instructions for materials and assembly.",
        "guide": "Layer identification guide",
        "all": "Complete composition",
        "count": "{count} original layers",
        "continued": "Layer index",
        "footer": "Schematic spacing / original layer order",
        "grid_order": "Read separated layers left to right, then top to bottom.",
    },
    "zh": {
        "edition": "LAYER STORY",
        "overview": "逐层辨识参考",
        "order": "从后到前",
        "order_help": "第 01 层在最后，最大编号层在最前。",
        "scope": "仅供层序与辨识参考；动画展开间距为示意。",
        "layer": "图层",
        "piece": "本层原图",
        "combined": "第 01 至 {number} 层组合",
        "note": "作者说明",
        "reference": "材料与具体装配方法请以作者的项目说明为准。",
        "guide": "图层辨识图册",
        "all": "完整组合",
        "count": "共 {count} 个原始图层",
        "continued": "图层索引",
        "footer": "示意间距 / 原始层序",
        "grid_order": "展开后按从左到右、从上到下的编号阅读。",
    },
}


def _path(value: str | Path, out: Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else out / candidate


def _font_candidates(data: dict[str, Any], cjk: bool) -> list[Path]:
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    provided = data.get("font_path") or os.environ.get("LAYER_STORY_FONT")
    paths = [Path(provided)] if provided else []
    chinese = [
        windows / "msyh.ttc", windows / "simhei.ttf", windows / "simsun.ttc",
        Path("/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    latin = [
        windows / "segoeui.ttf", windows / "arial.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    paths.extend(chinese + latin if cjk else latin + chinese)
    try:
        fallback = ImageFont.truetype("DejaVuSans.ttf", 14)
        paths.append(Path(fallback.path))
    except OSError:
        pass
    return list(dict.fromkeys(paths))


class Fonts:
    def __init__(self, data: dict[str, Any], text: str):
        needed = {ord(c) for c in text if not c.isspace()}
        cjk = any(0x2E80 <= c <= 0x9FFF or 0xF900 <= c <= 0xFAFF for c in needed)
        failures = []
        for path in _font_candidates(data, cjk):
            if not path.is_file():
                continue
            name = "LayerStory_" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
            try:
                face = TTFont(name, str(path), subfontIndex=0)
                missing = needed.difference(face.face.charToGlyph)
                if missing:
                    failures.append(f"{path.name}: missing {len(missing)} characters")
                    continue
                ImageFont.truetype(str(path), 16, index=0)
                pdfmetrics.registerFont(face)
                self.path, self.pdf_name = path, name
                self.cache: dict[int, ImageFont.FreeTypeFont] = {}
                return
            except Exception as exc:
                failures.append(f"{path.name}: {type(exc).__name__}")
        detail = "; ".join(failures[:5])
        raise RuntimeError(
            "No readable, embeddable TrueType font covers the supplied text. "
            "For Chinese, install Microsoft YaHei/SimHei or a TrueType Noto Sans SC font, "
            "or set LAYER_STORY_FONT to a suitable font file. "
            "Unsupported glyphs will not be replaced with empty squares. " + detail
        )

    def at(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self.cache:
            self.cache[size] = ImageFont.truetype(str(self.path), size, index=0)
        return self.cache[size]


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Wrap both CJK text and long unbroken Latin identifiers without truncation."""
    lines: list[str] = []
    for paragraph in str(text).replace("\t", " ").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and font.getlength(candidate) > width:
                split = current.rfind(" ")
                if split > 0:
                    lines.append(current[:split].rstrip())
                    current = current[split + 1:] + char
                else:
                    lines.append(current)
                    current = char
            else:
                current = candidate
        lines.append(current.rstrip())
    return lines


def _text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], lines: list[str],
          font: ImageFont.FreeTypeFont, fill: str = INK, leading: float = 1.35) -> float:
    x, y = xy
    step = math.ceil(font.size * leading)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, anchor="lt")
        y += step
    return y


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    ratio = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _paste_center(page: Image.Image, artwork: Image.Image, box: tuple[int, int, int, int],
                  padding: int = 0) -> None:
    left, top, right, bottom = box
    fitted = _fit(artwork, max(1, right - left - padding * 2), max(1, bottom - top - padding * 2))
    page.alpha_composite(fitted, (left + (right - left - fitted.width) // 2,
                                  top + (bottom - top - fitted.height) // 2))


def _plate(artwork: Image.Image, width: int, height: int, padding: int = 18) -> Image.Image:
    plate = Image.new("RGBA", (width, height), MATTE)
    _paste_center(plate, artwork, (0, 0, width, height), padding)
    ImageDraw.Draw(plate).rectangle((0, 0, width - 1, height - 1), outline=LINE, width=1)
    return plate


def _overview(data: dict[str, Any], images: list[Image.Image], cumulative: list[Image.Image],
              fonts: Fonts, copy: dict[str, str], out: Path) -> None:
    width, margin = 1600, 88
    title_lines = _wrap(data["title"], fonts.at(66), width - 2 * margin)
    brand_lines = _wrap(data.get("brand", ""), fonts.at(25), width - 2 * margin - 270)
    title_y = 108 + max(1, len(brand_lines)) * 34
    hero_y = title_y + len(title_lines) * 86 + 36
    hero_h = 630
    columns = 2 if len(images) <= 4 else 3 if len(images) <= 12 else 4
    gap, thumb_h = 24, 230 if columns < 4 else 200
    card_w = (width - 2 * margin - (columns - 1) * gap) // columns
    card_rows = []
    label_font = fonts.at(25 if columns < 4 else 23)
    for start in range(0, len(images), columns):
        cards = []
        for i in range(start, min(start + columns, len(images))):
            label = _wrap(data["layers"][i]["label"], label_font, card_w - 28)
            cards.append((i, label))
        row_h = thumb_h + 54 + max(len(v) for _, v in cards) * math.ceil(label_font.size * 1.35) + 22
        card_rows.append((cards, row_h))
    index_y = hero_y + hero_h + 122
    total_h = index_y + sum(h + 26 for _, h in card_rows) + 120
    page = Image.new("RGBA", (width, total_h), PAPER)
    draw = ImageDraw.Draw(page)
    draw.text((margin, 56), copy["edition"], font=fonts.at(25), fill=MUTED, anchor="lt")
    draw.text((width - margin, 56), copy["count"].format(count=len(images)), font=fonts.at(23),
              fill=MUTED, anchor="rt")
    if data.get("brand"):
        _text(draw, (margin, 100), brand_lines, fonts.at(25), MUTED)
    _text(draw, (margin, title_y), title_lines, fonts.at(66), leading=1.3)
    hero_box = (margin, hero_y, width - margin, hero_y + hero_h)
    draw.rectangle(hero_box, fill=MATTE)
    _paste_center(page, cumulative[-1], hero_box, 30)
    draw.text((margin + 24, hero_y + 22), copy["all"], font=fonts.at(22), fill=MUTED, anchor="lt")
    draw.text((margin, hero_y + hero_h + 36), copy["order"], font=fonts.at(30), fill=INK, anchor="lt")
    draw.text((width - margin, hero_y + hero_h + 40), copy["order_help"], font=fonts.at(23),
              fill=MUTED, anchor="rt")
    y = index_y
    for cards, row_h in card_rows:
        for col, (i, label_lines) in enumerate(cards):
            x = margin + col * (card_w + gap)
            draw.rectangle((x, y, x + card_w, y + row_h), fill=WHITE, outline=LINE)
            page.alpha_composite(_plate(images[i], card_w, thumb_h, 20), (x, y))
            draw.rounded_rectangle((x + 14, y + 14, x + 70, y + 52), radius=9, fill=INK)
            draw.text((x + 42, y + 33), f"{i + 1:02d}", font=fonts.at(23), fill=WHITE, anchor="mm")
            _text(draw, (x + 14, y + thumb_h + 24), label_lines, label_font)
        y += row_h + 26
    draw.line((margin, total_h - 89, width - margin, total_h - 89), fill=LINE, width=2)
    draw.text((margin, total_h - 59), copy["scope"], font=fonts.at(24), fill=MUTED, anchor="lt")
    page.convert("RGB").save(out / "overview.png", optimize=True)


def _pdf_image(image: Image.Image, width: float, height: float) -> PDFImage:
    pixels = _plate(image, max(1, round(width * 2.5)), max(1, round(height * 2.5)), 22)
    stream = io.BytesIO()
    pixels.save(stream, format="PNG")
    stream.seek(0)
    return PDFImage(stream, width=width, height=height)


def _guide(data: dict[str, Any], images: list[Image.Image], cumulative: list[Image.Image],
           fonts: Fonts, copy: dict[str, str], out: Path) -> None:
    page_w, page_h = A4
    usable = page_w - 88
    styles = {
        "eyebrow": ParagraphStyle("eyebrow", fontName=fonts.pdf_name, fontSize=10, leading=15,
                                   textColor=colors.HexColor(MUTED), spaceAfter=10),
        "title": ParagraphStyle("title", fontName=fonts.pdf_name, fontSize=27, leading=37,
                                 textColor=colors.HexColor(INK), spaceAfter=15, wordWrap="CJK"),
        "label": ParagraphStyle("label", fontName=fonts.pdf_name, fontSize=22, leading=31,
                                 textColor=colors.HexColor(INK), spaceAfter=20, wordWrap="CJK"),
        "body": ParagraphStyle("body", fontName=fonts.pdf_name, fontSize=10, leading=16,
                                textColor=colors.HexColor(INK), wordWrap="CJK", spaceAfter=10),
        "small": ParagraphStyle("small", fontName=fonts.pdf_name, fontSize=8.5, leading=13,
                                 textColor=colors.HexColor(MUTED), wordWrap="CJK", spaceAfter=8),
        "caption": ParagraphStyle("caption", fontName=fonts.pdf_name, fontSize=10, leading=16,
                                   textColor=colors.HexColor(INK), alignment=TA_CENTER,
                                   wordWrap="CJK"),
    }
    def p(text: str, style: str = "body") -> Paragraph:
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

    def page_chrome(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(PAPER))
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        canvas.setFont(fonts.pdf_name, 8)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(44, page_h - 34, copy["edition"])
        # The full brand is on the opening page; the running header stays compact.
        canvas.drawRightString(page_w - 44, page_h - 34, copy["guide"])
        canvas.setStrokeColor(colors.HexColor(LINE))
        canvas.line(44, 45, page_w - 44, 45)
        canvas.drawString(44, 30, copy["scope"])
        canvas.drawRightString(page_w - 44, 30, str(doc.page))
        canvas.restoreState()

    story = [p(copy["overview"], "eyebrow"), p(data["title"], "title")]
    if data.get("brand"):
        story.append(p(data["brand"], "body"))
    story += [p(copy["count"].format(count=len(images)), "small"),
              _pdf_image(cumulative[-1], usable, 300), Spacer(1, 20),
              p(copy["order"], "eyebrow"), p(copy["order_help"], "small")]
    rows = []
    for i, layer in enumerate(data["layers"]):
        rows.append([p(f"{i + 1:02d}", "body"), p(layer["label"], "body")])
    index = Table(rows, colWidths=[32, usable - 32], hAlign="LEFT")
    index.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor(LINE)),
    ]))
    story.append(index)
    image_w = (usable - 18) / 2
    for i, layer in enumerate(data["layers"]):
        story += [PageBreak(), p(f"{copy['layer']} {i + 1:02d} / {len(images):02d}", "eyebrow"),
                  p(layer["label"], "label")]
        comparison = Table([
            [p(copy["piece"], "caption"), "", p(copy["combined"].format(number=f"{i + 1:02d}"), "caption")],
            [_pdf_image(images[i], image_w, 250), "", _pdf_image(cumulative[i], image_w, 250)],
        ], colWidths=[image_w, 18, image_w], hAlign="LEFT")
        comparison.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
        ]))
        story += [comparison, Spacer(1, 22), p(copy["order_help"], "small")]
        if layer.get("note"):
            story += [Spacer(1, 8), p(copy["note"], "eyebrow"), p(layer["note"], "body")]
        story += [Spacer(1, 15), p(copy["reference"], "small")]
    document = SimpleDocTemplate(
        str(out / "layer-guide.pdf"), pagesize=A4, leftMargin=44, rightMargin=44,
        topMargin=66, bottomMargin=65, title=data["title"],
        author=data.get("brand", ""), subject=copy["guide"],
    )
    document.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)


def _video_base(data: dict[str, Any], fonts: Fonts, copy: dict[str, str], count: int) -> Image.Image:
    page = Image.new("RGBA", (1080, 1080), PAPER)
    draw = ImageDraw.Draw(page)
    draw.text((62, 42), copy["edition"], font=fonts.at(21), fill=MUTED, anchor="lt")
    draw.text((1018, 42), copy["count"].format(count=count), font=fonts.at(21), fill=MUTED, anchor="rt")
    for size in range(45, 17, -1):
        lines = _wrap(data["title"], fonts.at(size), 956)
        if len(lines) <= 3 and len(lines) * math.ceil(size * 1.3) <= 145:
            break
    else:
        raise ValueError("The project title is too long for the video heading; use a shorter title.")
    _text(draw, (62, 86), lines, fonts.at(size), leading=1.3)
    draw.line((62, 230, 1018, 230), fill=LINE, width=2)
    draw.text((62, 928), copy["order"], font=fonts.at(21), fill=MUTED, anchor="lt")
    draw.text((62, 966), copy["grid_order"], font=fonts.at(21), fill=MUTED, anchor="lt")
    draw.text((62, 1052), copy["footer"], font=fonts.at(17), fill=MUTED, anchor="lt")
    if data.get("brand"):
        for brand_size in range(17, 10, -1):
            brand_lines = _wrap(data["brand"], fonts.at(brand_size), 440)
            if len(brand_lines) <= 2:
                break
        else:
            raise ValueError("The brand name is too long for the video footer; use a shorter brand name.")
        brand_step = math.ceil(brand_size * 1.25)
        brand_y = 1070 - len(brand_lines) * brand_step
        for line in brand_lines:
            draw.text((1018, brand_y), line, font=fonts.at(brand_size), fill=MUTED, anchor="rt")
            brand_y += brand_step
    return page


def _easing(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def _spread(frame: int) -> float:
    time = frame / 24
    if time <= 1 or time >= 11:
        return 0.0
    if time < 4:
        return _easing((time - 1) / 3)
    if time <= 8:
        return 1.0
    return 1.0 - _easing((time - 8) / 3)


def _video_frame_renderer(data: dict[str, Any], images: list[Image.Image], cumulative: list[Image.Image],
                          fonts: Fonts, copy: dict[str, str]):
    """Return a renderer with an unambiguous, numbered grid at full separation.

    Every layer retains its complete shared canvas and aspect ratio. The whole
    layer is translated and uniformly scaled; source pixels are never recoloured,
    cropped to their visible bounds, or assigned to layers by their colour.
    """
    base = _video_base(data, fonts, copy, len(images))
    fitted = [_fit(image, 610, 470) for image in images]
    complete = _fit(cumulative[-1], 610, 470)
    count = len(images)
    columns = 2 if count <= 4 else 3 if count <= 9 else 4 if count <= 16 else 6
    rows = math.ceil(count / columns)
    stage_left, stage_top, stage_w, stage_h, gap = 62, 270, 956, 635, 16
    cell_w = (stage_w - (columns - 1) * gap) / columns
    cell_h = (stage_h - (rows - 1) * gap) / rows
    cells = []
    for i in range(count):
        row, col = divmod(i, columns)
        x = stage_left + col * (cell_w + gap)
        y = stage_top + row * (cell_h + gap)
        cells.append((x, y, x + cell_w, y + cell_h))
    target_ratio = min((cell_w - 24) / fitted[0].width, (cell_h - 54) / fitted[0].height)
    # Every supplied PNG has the same source canvas, so every layer uses one scale.
    target_size = (max(1, round(fitted[0].width * target_ratio)),
                   max(1, round(fitted[0].height * target_ratio)))

    def frame_image(index: int) -> Image.Image:
        frame = base.copy()
        amount = _spread(index)
        if amount == 0:
            frame.alpha_composite(complete, ((1080 - complete.width) // 2, 575 - complete.height // 2))
        else:
            # Numbered card frames appear only near the fully separated position.
            # This avoids badges obscuring or seeming attached to crossing layers.
            label_alpha = _easing((amount - .95) / .05)
            cards = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            card_draw = ImageDraw.Draw(cards)
            if label_alpha > 0:
                for left, top, right, bottom in cells:
                    card_draw.rounded_rectangle((round(left), round(top), round(right), round(bottom)),
                                                radius=9, fill=MATTE, outline=LINE, width=1)
                if label_alpha < 1:
                    cards.putalpha(cards.getchannel("A").point(lambda alpha: round(alpha * label_alpha)))
                frame.alpha_composite(cards)
            for i, layer in enumerate(fitted):
                left, top, right, bottom = cells[i]
                target_cx = (left + right) / 2
                target_cy = (top + 42 + bottom - 12) / 2
                width = max(1, round(layer.width + (target_size[0] - layer.width) * amount))
                height = max(1, round(layer.height + (target_size[1] - layer.height) * amount))
                cx = 540 + (target_cx - 540) * amount
                cy = 575 + (target_cy - 575) * amount
                resized = layer.resize((width, height), Image.Resampling.LANCZOS)
                frame.alpha_composite(resized, (round(cx - width / 2), round(cy - height / 2)))
            if label_alpha > 0:
                badges = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                badge_draw = ImageDraw.Draw(badges)
                for i, (left, top, _, _) in enumerate(cells):
                    x, y = round(left + 10), round(top + 8)
                    badge_draw.rounded_rectangle((x, y, x + 47, y + 27), radius=7, fill=INK)
                    badge_draw.text((x + 23.5, y + 13.5), f"{i + 1:02d}",
                                    font=fonts.at(18), fill=WHITE, anchor="mm")
                if label_alpha < 1:
                    badges.putalpha(badges.getchannel("A").point(lambda alpha: round(alpha * label_alpha)))
                frame.alpha_composite(badges)
        return frame.convert("RGB")
    return frame_image, {
        "columns": columns, "rows": rows,
        "numbering": "One number attached to each complete layer card; left-to-right, then top-to-bottom.",
        "fully_separated_seconds": [4, 8],
        "source_layer_visibility": "All complete layer canvases visible without overlap at full separation.",
    }


def _video(data: dict[str, Any], images: list[Image.Image], cumulative: list[Image.Image],
           fonts: Fonts, copy: dict[str, str], out: Path, skip: bool) -> dict[str, Any]:
    frame_image, grid = _video_frame_renderer(data, images, cumulative, fonts, copy)
    poster = frame_image(0)
    poster.save(out / "video-poster.png", optimize=True)
    first_hash = hashlib.sha256(poster.tobytes()).hexdigest()
    last_hash = hashlib.sha256(frame_image(287).tobytes()).hexdigest()
    metadata = {
        "skipped": bool(skip), "duration_seconds": 12, "fps": 24,
        "frame_count": 288, "width": 1080, "height": 1080,
        "codec": "h264", "pixel_format": "yuv420p", "audio": False,
        "spacing": "schematic",
        "motion": "Original layer stack unfolds to a numbered grid and returns; uniform scale and translation only.",
        "grid": grid,
        "first_composited_frame_sha256": first_hash,
        "last_composited_frame_sha256": last_hash,
        "first_last_composited_frames_identical": first_hash == last_hash,
        "endpoint_comparison_scope": "RGB frames before lossy H.264 encoding; decoded pixels may differ.",
    }
    if skip:
        return metadata
    import imageio_ffmpeg
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo", "-s", "1080x1080",
        "-pix_fmt", "rgb24", "-r", "24", "-i", "-", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-frames:v", "288",
        str(out / "layer-story.mp4"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for frame in range(288):
            process.stdin.write(frame_image(frame).tobytes())
        process.stdin.close()
        process.stdin = None
        _, error = process.communicate()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Video encoding failed: " + error.decode("utf-8", errors="replace")[-3000:])
    metadata["encoder"] = "libx264"
    metadata["crf"] = 19
    return metadata


def create_deliverables(data: dict[str, Any], out: str | Path,
                        skip_video: bool = False) -> dict[str, Any]:
    """Create overview, PDF, poster, optional H.264 video and presentation metadata.

    Input PNG paths may be absolute or relative to ``out``. Each layer image and
    cumulative image must share a canvas. The caller validates source geometry
    and runs the PDF authoring marker before invoking this function.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    layers = data.get("layers", [])
    if not 2 <= len(layers) <= 24:
        raise ValueError("Presentation requires 2 to 24 confirmed source layers.")
    language = data.get("language", "en")
    if language not in COPY:
        raise ValueError("Presentation language must be 'en' or 'zh'.")
    copy = COPY[language]
    text = "\n".join([str(data.get("title", "")), str(data.get("brand", "")),
                       *copy.values(), "0123456789 /",
                       *(str(layer.get(key, "")) for layer in layers for key in ("label", "note"))])
    fonts = Fonts(data, text)
    images, cumulative = [], []
    for layer in layers:
        for key, target in (("png", images), ("cumulative_png", cumulative)):
            with Image.open(_path(layer[key], out)) as image:
                target.append(image.convert("RGBA"))
    expected = (int(data["canvas"]["width"]), int(data["canvas"]["height"]))
    if any(image.size != expected for image in images + cumulative):
        raise ValueError("All layer and cumulative PNGs must match the declared canvas dimensions.")
    _overview(data, images, cumulative, fonts, copy, out)
    _guide(data, images, cumulative, fonts, copy, out)
    video = _video(data, images, cumulative, fonts, copy, out, skip_video)
    metadata = {
        "files": {"overview": "overview.png", "guide": "layer-guide.pdf", "poster": "video-poster.png"},
        "video": video, "language": language, "layer_count": len(layers),
        "layer_order": [{"number": i + 1, "id": layer["id"], "label": layer["label"]}
                        for i, layer in enumerate(layers)],
        "font_file": fonts.path.name,
        "notes_policy": "Only supplied author notes are reproduced. No assembly process is inferred.",
        "warnings": [],
    }
    if not skip_video:
        metadata["files"]["video"] = "layer-story.mp4"
    (out / "presentation-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata
