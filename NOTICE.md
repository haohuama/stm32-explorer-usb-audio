# 第三方组件与许可证声明

本仓库包含或依赖以下第三方组件，版权归各自作者/公司所有，使用时请遵守其许可证：

| 组件 | 位置 | 来源 / 许可证 |
|---|---|---|
| STM32F4 HAL 驱动、CMSIS | `Drivers/` | STMicroelectronics；按 ST 许可（各文件头保留版权声明） |
| STM32 USB Device Library（Core + CDC Class） | `Middlewares/USB/STM32_USB_Device_Library/` | STMicroelectronics；**SLA0044**（Ultimate Liberty License，各文件头保留版权声明） |
| WM8978 驱动 | `User/Hardware/WM8978/` | 基于 lovelyterry 的 **MIT** 实现改造，保留原版权 |
| USB_APP 适配层、上位机脚本 | `Middlewares/USB/USB_APP/`、`Tools/` | 本项目原创 |

## 说明

- `docs/` 中的部分文档是个人学习/移植笔记，可能引用第三方资料（如开发板手册）的要点；
  **原始第三方手册、原理图、参考例程均未包含在本仓库内**，相关版权归原作者所有。
- `Tools/` 下的示例音频（未随仓库分发）不含任何版权音乐。
- 本项目仅供学习与个人使用；如需商用，请自行确认各第三方组件的许可条款。
