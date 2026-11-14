#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成精简 GBK 16x16 点阵字库（仅包含本项目 UI/演示歌词实际用到的汉字）。

输出: User/Hardware/LCD/cn_font.h
原理: 从 Windows 自带 simsun.ttc 渲染 16x16 位图，按 GBK 双字节码索引。
      源码里的中文字符串统一按 GBK 编码写入 C 数组（字节转义），
      避免 Keil/编辑器 UTF-8 编码歧义（与 docs/LCD歌词显示_方案与代码框架.md 一致）。
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = r"C:/Windows/Fonts/simsun.ttc"
FONT_SIZE = 16
GLYPH_W, GLYPH_H = 16, 16
OUT = r"C:/stm32TEST/User/Hardware/LCD/cn_font.h"

# 界面文字 + 演示歌词里出现的全部汉字（去重后由脚本自动收集）
UI_TEXT = (
    # 只列“屏上真正会显示”的汉字。
    # 这里放的是固定界面文字（标题栏 + 空歌词提示）；歌词本体的字来自 DEMO_LYRICS。
    # 每多一个字 = 32 字节 Flash（MDK-Lite 只有 32KB）。
    "江南林俊杰无歌词"
)

DEMO_LYRICS = [
    "风到这里就是粘",
    "粘住过客的思念",
    "雨到了这里缠成线",
    "缠着我们流连人世间",
    "你在身边就是缘",
    "缘分写在三生石上面",
    "爱有万分之一甜",
    "宁愿我就葬在这一点",
    "圈圈圆圆圈圈",
    "天天年年天天 的我",
    "深深看你的脸",
    "生气的温柔",
    "埋怨的温柔 的脸",
    "不懂爱恨情愁煎熬的我们",
    "都以为相爱就像风云的善变",
    "相信爱一天 抵过永远",
    "在这一刹那冻结了时间",
    "不懂怎么表现温柔的我们",
    "还以为殉情只是古老的传言",
    "离愁能有多痛 痛有多浓",
    "当梦被埋在江南烟雨中",
    "心碎了才懂",
    "圈圈圆圆圈圈",
    "天天年年天天 的我",
    "深深看你的脸",
    "生气的温柔",
    "埋怨的温柔 的脸",
    "不懂爱恨情愁煎熬的我们",
    "都以为相爱就像风云的善变",
    "相信爱一天 抵过永远",
    "在这一刹那冻结了时间",
    "不懂怎么表现温柔的我们",
    "还以为殉情只是古老的传言",
    "离愁能有多痛 痛有多浓",
    "当梦被埋在江南烟雨中",
    "心碎了才懂",
    "相信爱一天 抵过永远",
    "在这一刹那冻结了时间",
    "不懂怎么表现温柔的我们",
    "还以为殉情只是古老的传言",
    "离愁能有多痛 痛有多浓",
    "当梦被埋在江南烟雨中",
    "心碎了才懂",
    "你真的懂唯一的定义",
    "并不简单如呼吸",
    "你真的希望你能厘清",
    "若没交⼼怎么说明",
    "我真的爱你 句句不轻易",
    "眼神中飘移 总是在关键时刻清楚洞悉",
    "你的不坚定 配合我颠沛流离",
    "死去中清醒 明⽩你背着我聪明",
    "那些我 想说的 没说的 话",
    "有时我 怀疑那 只是我 傻瓜",
    "但如果真的爱 不会算计",
    "爱是不嫉妒 不张狂 不求⾃⼰",
    "无关你的回应 永不⽌息",
    "你知道",
    "我真的爱你 没⼈能比拟",
    "眼神没肯定 总是在关键时刻清楚洞悉",
    "你的不坚定 配合我颠沛流离",
    "死去中清醒 明⽩你背着我聪明",
    "我知道",
    "爱本质无异 是因为⼈多得拥挤",
    "你不想证明 证明我是你唯一",
    "证明我是你唯一",
    "开始想念你的口红",
    "温度留在我手中",
    "我听够了受够了那些争吵让我哑了喉咙",
    "我只是觉得我们之间欠个道歉",
    "我真的希望你能对我的错误别再抱怨",
    "你的香水味道总会让我变得冲动",
    "在我周围我的大脑会渐渐地失控",
    "就像命运捉弄你的话被我默诵",
    "你慢慢地走远我竟然不忍心道一句珍重",
    "你的语音我期待出现在屏幕中",
    "恍恍惚惚就像掉进了那无底洞",
    "有你躺在我身边我会渐渐地放松",
    "整个世界都会慢慢变得不同",
    "我不想再去在乎那些乱七八糟的事",
    "最凶狠的争吵却总是发生在纪念日",
    "泛黄的日志荒诞的世事",
    "我记忆中模糊了脸却爱你手心的痣",
    "G. E. M.",
    "美丽的泡沫虽然一刹花火",
    "你所有承诺虽然都太脆弱",
    "爱本是泡沫如果能够看破",
    "有什么难过",
    "再美的花朵盛开过就凋落",
    "再亮眼的星一闪过就坠落",
    "爱本是泡沫如果能够看破",
    "有什么难过",
    "凌晨的两点半我还在你家门口",
    "地铁的终点站我不敢再去回首",
    "有时候享受一个人幻想的纯粹",
    "也学着享受费洛蒙不断飘荡的滋味",
    "酒总会让我疲惫却永远难以入睡",
    "记忆中的香味让我在黑暗中下坠",
    "当两个人在一开始就注定都是刺猬",
    "一切的罪魁祸首都是自尊心在作祟",
    "Everyday自己的决定自己去 Pay",
    "没什么出路最初的默契早就异位 no delay",
    "我以为也许时间足够准备",
    "最后的侥幸不想被击溃到支离破碎",
    "所以最后回忆都不留痕迹的 Gone",
    "可不可以不要留我一个人游荡",
    "你的内心是我没办法进入的 Town",
    "我只好把烧过的灰烬拼成无奈的 Song",
    "G. E. M.",
    "全都是泡沫只一刹的花火",
    "你所有承诺全部都太脆弱",
    "而你的轮廓怪我没有看破",
    "才如此难过",
    "相爱的把握要如何再搜索",
    "相拥着寂寞难道就不寂寞",
    "爱本是泡沫怪我没有看破",
    "才如此难过",
    "还是会想你 还是会怪你",
    "怪你轻而易举潇洒抽离",
    "还是爱着你 想走进你心里",
    "拨开迷雾抓住你的声音",
    "几百遍 重复了几百遍",
    "重复的情绪重复了熬过想你的夜",
    "这思念难道直到感受不到痛为止",
    "可这过程我怎么可能会装作没事",
    "你教会我怎么爱你却没教会遗忘",
    "随意的举动撕碎我所有的立场",
    "我心知肚明不愿戳穿你的另一面",
    "却没想过如今变成我的nightmare",
    "昏黄的路灯照不亮整条街",
    "我怎么用力也走不到你心里",
    "倾盆的雨下了一整夜",
    "我们离得这么近你却看不清楚我的泪滴",
    "我知道我可以随时被代替",
    "却还是接受不了这种落差",
    "我们的爱就像是流星落下",
    "随烟火消失的火花",
    "还是会想你 还是会怪你",
    "怪你轻而易举潇洒抽离",
    "还是爱着你 想走进你心里",
    "拨开迷雾抓住你的声音",
    "曾在我怀里看着我撒娇的你",
    "慢一秒接电话都会生气的你",
    "那场在公交站台下不停的雨",
    "每一次许的愿望都会关于你",
    "im liar 世界最大的liar",
    "说过最痛的谎是绝对不会放开你",
    "like fire we burning like fire",
    "我们从3000 degrees 骤降到零下",
    "你说你早都放下了任何猜疑",
    "这份牵挂只会让你崩溃",
    "由始至终的选择权都在你",
    "我早都流够了只属于你的泪",
    "这份爱最好的结尾用这段文字来作为纪念",
    "放下了所有的偏执放下你有没有时间来限制",
    "伪装住这份情绪你不懂有多么累",
    "shawty its so freaking heartache",
    "还是会想你 还是会怪你",
    "怪你轻而易举潇洒抽离",
    "还是爱着你 想走进你心里",
    "拨开迷雾抓住你的声音",
    "本歌曲来自网易云音乐〖云上工作室〗",
    "10亿现金激励，千亿流量扶持！",
    "江南",
    "唯一",
    "泡沫",
    "还是会想你",
]


def collect_chars():
    s = UI_TEXT + "".join(DEMO_LYRICS)
    # 只取 GBK 可编码的汉字/全角符号（ASCII 用驱动自带 asc2_1608）
    out = set()
    for ch in s:
        if ord(ch) < 0x80:
            continue
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            continue
        out.add(ch)
    return sorted(out, key=lambda c: c.encode("gbk"))


def render_glyph(font, ch):
    img = Image.new("1", (GLYPH_W, GLYPH_H), 0)
    d = ImageDraw.Draw(img)
    d.text((0, -1), ch, font=font, fill=1)
    # 每行 2 字节，高位在左；共 16 行 = 32 字节
    bits = []
    px = img.load()
    for y in range(GLYPH_H):
        v = 0
        for x in range(GLYPH_W):
            if px[x, y]:
                v |= 0x8000 >> x
        bits.append((v >> 8) & 0xFF)
        bits.append(v & 0xFF)
    return bits


def main():
    if not os.path.exists(FONT_PATH):
        print("missing font:", FONT_PATH)
        sys.exit(1)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    chars = collect_chars()
    print("chars =", len(chars), "->", "".join(chars))

    rows = []
    for ch in chars:
        code = ch.encode("gbk")
        if len(code) != 2:
            continue
        key = (code[0] << 8) | code[1]
        bits = render_glyph(font, ch)
        rows.append((key, ch, bits))
    rows.sort(key=lambda r: r[0])

    with open(OUT, "w", encoding="ascii") as f:
        f.write("/* Auto-generated by Tools/gen_cn_font.py -- DO NOT EDIT.\n")
        f.write(" * Simplified Chinese 16x16 bitmap font, GBK indexed.\n")
        f.write(" * Source glyphs: Windows simsun.ttc (system font, rendered for this project).\n")
        f.write(" * Only %d glyphs actually used by the UI and demo lyrics are included.\n" % len(rows))
        f.write(" * Layout: 16 rows x 2 bytes, MSB = leftmost pixel.\n")
        f.write(" */\n")
        f.write("#ifndef __CN_FONT_H\n#define __CN_FONT_H\n\n")
        f.write("#include <stdint.h>\n\n")
        f.write("typedef struct { uint16_t gbk; uint8_t bits[32]; } cn_glyph_t;\n\n")
        f.write("static const cn_glyph_t g_cn_font[] = {\n")
        for key, ch, bits in rows:
            f.write("    {0x%04X, {" % key)
            f.write(",".join("0x%02X" % b for b in bits))
            f.write("}},\n")
        f.write("};\n\n")
        f.write("#define CN_FONT_COUNT  ((uint16_t)(sizeof(g_cn_font)/sizeof(g_cn_font[0])))\n\n")
        f.write("#endif\n")

    print("wrote", OUT, "glyphs =", len(rows),
          "bytes =", os.path.getsize(OUT))


if __name__ == "__main__":
    main()
