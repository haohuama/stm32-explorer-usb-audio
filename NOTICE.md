# 第三方组件与许可证声明

本仓库包含或依赖以下第三方组件，版权归各自作者/公司所有，使用时请遵守其许可证：

| 组件 | 位置 | 来源 / 许可证 |
|---|---|---|
| STM32F4 HAL 驱动、CMSIS | `Drivers/` | STMicroelectronics；按 ST 许可（各文件头保留版权声明） |
| STM32 USB Device Library（Core + CDC Class） | `Middlewares/USB/STM32_USB_Device_Library/` | STMicroelectronics；**SLA0044**（Ultimate Liberty License，各文件头保留版权声明） |
| ChaN FatFs R0.14b | `Middlewares/FATFS/ff.c` `ff.h` `ffunicode.c` | ChaN；**FatFs License**（"free software, not restricted by any license"；允许任意用途与再分发，须保留版权声明与来源说明，**不含任何担保**）。见 `Middlewares/FATFS/LICENSE.txt` |
| LCD 驱动（FSMC 8080，多控制器） | `User/Hardware/LCD/lcd.c` `lcd.h` `lcd_ex.c` `lcdfont.h` | 正点原子（ALIENTEK）探索者例程，仅作学习移植使用；文件头版权信息保留。**如需商用请自行确认授权** |
| WM8978 驱动 | `User/Hardware/WM8978/` | 基于 lovelyterry 的 **MIT** 实现改造，保留原版权 |
| SDIO / WAV 播放参考（未直接并入，仅参考接口与引脚） | 见 `docs/` | LibDriver `wm8978`（**MIT**）；正点原子 实验43（版权不明，**仅参考，未复制其 diskio/音频代码**） |
| USB_APP 适配层、LCD 歌词界面、上位机与生成脚本 | `Middlewares/USB/USB_APP/`、`User/APP/`、`User/Hardware/LCD/lcd_ui.c`、`Tools/` | 本项目原创 |

## 字体与点阵

- `User/Hardware/LCD/cn_font.h` 是**由本项目脚本生成的位图点阵数据**（16×16，仅包含屏上实际用到的几百个汉字），
  由 `Tools/gen_cn_font.py` 从本机系统字体渲染而来。**仓库不包含任何字体文件（.ttf/.ttc）**。
  若你要把生成的点阵用于商业发布，请自行确认所用系统字体的授权条款。

## 说明

- `docs/` 中的部分文档是个人学习/移植笔记，可能引用第三方资料（如开发板手册）的要点；
  **原始第三方手册、原理图、参考例程、字库文件均未包含在本仓库内**，相关版权归原作者所有。
- `Tools/` 下的示例音频与播放列表 WAV（`pl01.wav`~`pl04.wav` 等，未随仓库分发）均为版权音乐，
  仅本机测试使用，**不在本仓库内**。
- 本项目仅供学习与个人使用；如需商用，请自行确认各第三方组件的许可条款。
