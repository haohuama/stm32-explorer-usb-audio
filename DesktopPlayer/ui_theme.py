# -*- coding: utf-8 -*-
"""ui_theme.py —— macOS「音乐」风格的视觉规范 + 绘制工具

参考的是 macOS Sonoma / Apple Music App 的视觉语言：
  * 左侧毛玻璃质感侧栏（这里用深色半透明色块近似）
  * 顶栏用 SF Pro Display 替代品「Segoe UI Variable Display」
  * 歌词区居中大字，当前句高亮 + 上下渐隐
  * 播放控件用细线条符号（⏮ ▶ ⏭）而非实心方块
  * 强调色用 Apple Music 的粉红系 #FA2D48 → 渐变到 #FB5C74

Tk 没有真正的毛玻璃/圆角控件，所有圆角用 Canvas 的 arc+rect 手绘。
"""
import os

# ---------------------------------------------------------------- 颜色
BG_DEEP = "#0A0A0C"            # 最底层
BG = "#121215"                 # 主背景
SIDEBAR = "#1B1B20"            # 侧栏
SIDEBAR_HI = "#26262E"         # 侧栏选中项
CARD = "#1A1A1F"               # 卡片
CARD_HI = "#22222A"            # 卡片悬浮
EDGE = "#2C2C34"               # 分隔线 / 描边
FG = "#F5F5F7"                 # 主文字（Apple 的 labelColor）
FG2 = "#A1A1A8"                # 次要文字
FG3 = "#6E6E76"                # 三级文字 / 禁用
ACCENT = "#FA2D48"             # Apple Music 粉红
ACCENT2 = "#FB5C74"            # 渐变另一端
ACCENT_SOFT = "#3A1B24"        # 强调色淡化底

PLAY = "#FFFFFF"               # 播放按钮
TRACK = "#3A3A42"              # 进度条底槽
HILITE = "#FB5C74"             # 歌词当前句

SPEEDS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]

FONT_UI = "Segoe UI Variable Text"
FONT_UI_CN = "Microsoft YaHei UI"
FONT_DISPLAY = "Segoe UI Variable Display"
FONT_DISPLAY_CN = "Microsoft YaHei UI"

# 圆角半径
R_SMALL = 6
R_MED = 10
R_LARGE = 16


def font_family(display=False, cn=False):
    """中文优先用 YaHei UI，英文用 Segoe UI Variable。"""
    if cn:
        return FONT_DISPLAY_CN if display else FONT_UI_CN
    return FONT_DISPLAY if display else FONT_UI


def mix(c1, c2, t):
    """两个 #RRGGBB 之间线性插值。"""
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ---------------------------------------------------------------- 绘制
def round_rect(cv, x1, y1, x2, y2, r, fill="", outline="", width=1, tags=None):
    """在 Canvas 上画一个圆角矩形（用 4 个角弧 + 2 个矩形拼）。"""
    r = max(0, min(int(r), (x2 - x1) // 2, (y2 - y1) // 2))
    kw = dict(fill=fill, outline=outline, width=width)
    if tags:
        kw["tags"] = tags
    if r == 0:
        return cv.create_rectangle(x1, y1, x2, y2, **kw)
    items = [
        cv.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **kw),
        cv.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **kw),
        cv.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", **kw),
        cv.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", **kw),
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, **kw),
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, **kw),
    ]
    return items[0]


def round_rect_shadow(cv, x1, y1, x2, y2, r, fill, shadow_alpha_layers=5):
    """带柔和投影的圆角矩形（用几层逐渐透明的深色矩形近似阴影）。"""
    for i in range(shadow_alpha_layers, 0, -1):
        off = i * 2
        shade = "#%02X%02X%02X" % (0, 0, 0) if i < 3 else "#0C0C0F"
        round_rect(cv, x1 - off, y1 - off + 2, x2 + off, y2 + off + 3,
                   r + off, fill=shade, outline="")
    return round_rect(cv, x1, y1, x2, y2, r, fill=fill, outline="")


def make_cover_image(path, size, radius=0, darken=0.0):
    """读封面 -> 居中裁成正方形 -> 可选圆角遮罩 -> PIL Image。"""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2,
                  (w - s) // 2 + s, (h - s) // 2 + s)).resize((size, size), Image.LANCZOS)
    if radius > 0:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                               radius=radius, fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(im, (0, 0), mask)
        im = out
    if darken > 0:
        overlay = Image.new("RGB", (size, size),
                            (int(10 * darken), int(10 * darken), int(14 * darken)))
        im = Image.blend(im.convert("RGB"), overlay, darken)
    return im


def make_blur_background(cover_path, w, h, blur=48, darken=0.62):
    """用封面生成一张模糊的深色背景图（Apple Music 的「专辑色」氛围感）。"""
    from PIL import Image, ImageFilter
    if not cover_path or not os.path.isfile(cover_path):
        return None
    try:
        im = Image.open(cover_path).convert("RGB")
        # 放大到略大于窗口再模糊，避免边缘出现空白
        scale = max(w / im.width, h / im.height) * 1.15
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                       Image.LANCZOS)
        left = (im.width - w) // 2
        top = (im.height - h) // 2
        im = im.crop((left, top, left + w, top + h))
        im = im.filter(ImageFilter.GaussianBlur(blur))
        # 压暗：越往下越暗，让底部控件区可读
        px = im.load()
        for y in range(h):
            k = darken + 0.18 * (y / float(max(1, h - 1)))
            for x in range(0, w, 2):
                r, g, b = px[x, y]
                px[x, y] = (int(r * (1 - k)), int(g * (1 - k)), int(b * (1 - k)))
                if x + 1 < w:
                    px[x + 1, y] = px[x, y]
        return im
    except Exception:
        return None


def dominant_color(im, fallback="#FA2D48"):
    """从封面取一个主色（量化后取出现最多的色相），用作强调色。"""
    try:
        from PIL import Image
        small = im.convert("RGB").resize((32, 32), Image.LANCZOS)
        q = small.quantize(colors=8, method=Image.MEDIANCUT).convert("RGB")
        counts = {}
        px = q.load()
        for y in range(32):
            for x in range(32):
                r, g, b = px[x, y]
                # 忽略太暗/太灰的像素
                mx, mn = max(r, g, b), min(r, g, b)
                if mx < 60 or (mx - mn) < 25:
                    continue
                key = (r // 32, g // 32, b // 32)
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return fallback
        (r, g, b), _n = max(counts.items(), key=lambda kv: kv[1])
        r = min(255, r * 32 + 16)
        g = min(255, g * 32 + 16)
        b = min(255, b * 32 + 16)
        return "#%02X%02X%02X" % (r, g, b)
    except Exception:
        return fallback
