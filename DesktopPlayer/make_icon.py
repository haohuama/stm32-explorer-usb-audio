# -*- coding: utf-8 -*-
"""make_icon.py —— 生成桌面快捷方式用的 app.ico（纯 Pillow，无需素材）"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
S = 256


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def main():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 深色圆角底 + 蓝色渐变感（两层叠加）
    rounded(d, (4, 4, 252, 252), 52, (18, 22, 32, 255))
    rounded(d, (4, 4, 252, 150), 52, (30, 58, 96, 255))
    rounded(d, (4, 96, 252, 252), 40, (24, 30, 44, 255))

    # 音符：符头 + 符干 + 符尾
    blue = (78, 161, 255, 255)
    white = (240, 244, 255, 255)
    d.ellipse((72, 150, 132, 202), fill=white)          # 符头
    d.rounded_rectangle((122, 60, 134, 182), radius=5, fill=white)  # 符干
    d.polygon([(132, 62), (186, 84), (186, 106), (132, 90)], fill=blue)  # 符尾

    # 底部进度条（呼应播放器）
    rounded(d, (44, 216, 212, 224), 4, (60, 70, 90, 255))
    rounded(d, (44, 216, 150, 224), 4, blue)
    d.ellipse((142, 210, 162, 230), fill=white)

    im.save(OUT, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ico ->", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
