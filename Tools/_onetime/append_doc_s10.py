#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 §10「导入真歌词实战」追加到实施说明文档末尾（幂等）。"""
import io
import os

DOC = r"C:/stm32TEST/docs/LCD歌词界面_模块1集成说明.md"

SECTION = """
---

## 10. 导入真歌词：《江南 - 林俊杰》实战（32KB 内落地）

### 10.1 一键导入流程（以后换歌照做）

```
py Tools/lrc_to_c.py "C:/Users/xxx/歌名.lrc"
py Tools/gen_cn_font.py
py Tools/check_font.py
py Tools/build_check.py --microlib
```

- `lrc_to_c.py`：解析 LRC（同时支持网易云的 JSON 混排行 `{"t":..,"c":[{"tx":..}]}` 与
  标准 `[mm:ss.xx]` 行），自动剔除 `作词/作曲/编曲/制作人/吉他/录音室/OP/SP` 等
  **带冒号的制作人员行**（这些不该上屏，且白占字库），然后把歌词写进
  `lcd_ui.c` 的 `s_demo_lrc[]`（GBK 转义），并同步 `gen_cn_font.py` 的 `DEMO_LYRICS`。
- `gen_cn_font.py`：只渲染真正用到的汉字。
- `check_font.py`：校验屏上每个字都有点阵（防空白方块）。
- `build_check.py --microlib`：量体积，必须 `PASS`。

### 10.2 这首歌的规模

| 项 | 值 |
|---|---|
| 歌词行数 | 43（已剔除 10 行制作人员名单） |
| 不重复汉字 | 110（歌词）+ 6（"江南林俊杰"、"无歌词"）= 116 |
| 16x16 点阵占用 | 116 x 32 = **3712 字节** |
| LRC 文本占用 | 43 行 x 约 26 字节 = 约 1120 字节 |

### 10.3 为塞进 32KB 又做的两处结构性裁剪

1. **关闭 ASCII 字模**（新开关 `lcd.h: LCD_KEEP_ASCII_FONT 0`）
   `asc2_1608[95][16]`（1520B）连同 `lcd_show_char/num/string` 的代码一起不编译
   （保留空实现，符号不丢）。**因为屏上现在只画中文**：标题改为中文
   「江南 林俊杰」，空歌词提示改为「无歌词」。
   收益约 **-2400 字节**。把宏改回 1 即恢复英文/数字显示（lcd.c 里 include 与
   三个函数体都在 `#if LCD_KEEP_ASCII_FONT` 内，可逆）。
2. **歌词循环周期改为整首歌长**（`lcd_ui.c: LRC_CYCLE_MS 267900`）
   上位机是单曲循环发流，`consumed_bytes` 会一直累加，必须用歌曲时长取模，
   每轮歌词才能重新对齐。换歌时同步改这个值（= WAV 帧数/44100*1000）。

### 10.4 最终体积（脚本实测，microLIB）

```
image  ROM = 31924 bytes (31.18 KB)      Keil 侧约 32120
上限       = 32768                        余量 约 650
```

### 10.5 已知限制（务必知道）

1. **只有单曲循环时歌词才准**。上位机连续播多首时，MCU 不知道"换歌了"，
   `consumed_bytes` 连续增长 → 第二首开始歌词会错位。
   想多首连播且歌词正确，需要 PC 端在换歌处插一个同步标记（可作下一步）。
2. **中文只有这 116 个字**。换歌要重跑 §10.1 四步；余量仅约 20 个字的空间。
   要在卡里放很多首歌的词，必须解除 32KB（见 10.6），或把点阵搬到外部 SPI Flash。
3. 屏上不再显示英文/数字（ASCII 字模已关）。

### 10.6 一劳永逸：Keil MDK-Community（免费、无 32KB 限制）

Arm 官方的 **MDK-Community** 版对学生 / 爱好者 / 非商业用途**完全免费，且没有代码大小限制**
（它就是为取代带 32KB 限制的 MDK-Lite 而推出的）。官方原文：*"The MDK-Community edition
has no code size limits and supports all non-commercial use cases."*

在 Keil 里激活：

```
File -> License Management -> User-Based License -> Activate...
  -> 弹窗右上角 License Server...
  -> 地址填 https://mdk-preview.keil.arm.com
  -> Query -> 选 "Keil MDK Community" -> Activate -> Close
```

激活后本工程可以立刻恢复这些（都不再需要为字节数发愁）：

| 开关 | 位置 | 改回后得到 |
|---|---|---|
| `LCD_KEEP_ASCII_FONT 1` | `lcd.h` | 英文/数字显示（+2.4KB） |
| `LCD_KEEP_ALL_IC 1` | `lcd.h` | 7 种 LCD 控制器全支持（+3.7KB） |
| `FF_USE_LFN 1` | `FatFS/ffconf.h` | 中文长文件名（+175KB 转换表） |
| `P2_SELFTEST_ENABLE 1` | `main.c` | TF 卡自检（+7KB） |
| 恢复 24px 字模 | `lcdfont.h` | 大标题（+3.4KB） |
| 字库换成全量 GBK | `gen_cn_font.py` | 任意歌词都不用再生成字库 |

> 换句话说：**32KB 只是"未授权 Keil"的限制，不是芯片的限制**。F407 有 1MB Flash，
> 上面这些加起来也不过 200KB。要不要激活 Community 由你决定，激活前本版就是能跑的形态。
"""


def main():
    s = open(DOC, encoding="utf-8").read()
    if "## 10. 导入真歌词" in s:
        # 截断到 §10 之前重写，保证幂等
        i = s.find("## 10. 导入真歌词")
        i = s.rfind("\n---\n", 0, i)
        s = s[:i]
    s = s.rstrip() + "\n" + SECTION
    open(DOC, "w", encoding="utf-8", newline="").write(s)
    print("§10 已写入，文档行数:", s.count("\n") + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
