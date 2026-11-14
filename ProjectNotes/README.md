# ProjectNotes —— 项目日志与配套资料

这里汇总的是**工作区**（`C:\Users\mhh20\WorkBuddy\STM32项目`）里的过程资料，
之前只存在本地，2026-11-14 一并纳入本仓库，方便一个仓库看全。

| 目录/文件 | 内容 |
|---|---|
| `2026-11-14_工作日志.md` | 当天 7 轮改动的完整记录（硬件核对 → 界面 → 按键 → 触屏 → 桌面软件 → 同步） |
| `项目长期约定.md` | 板级事实、硬性约定、引脚表、踩坑清单、许可证纪律（长期维护） |
| `参考资料/` | 工作区 `docs/` 的 21 份技术文档：项目计划书、硬件核对表、CODEC 验证、许可证核查表、Phase 0~4 实施说明等 |
| `技能包/` | `stm32f407-explorer-audio` 技能包（SKILL.md + references/ + scripts/），可复用的板级经验 |

## 不入库的东西

按项目约定，以下内容**不**放进仓库，只保留在本地备份 zip 中：

- `Tools/*.wav` / `*.mp3` —— 版权与体积（一首 WAV 约 30MB）
- `Output/` —— Keil 构建产物
- 认证信息、token、密钥
- 微信临时目录里的原图（已复制成 `DesktopPlayer/assets/default_cover.jpg` 入库）

`Tools/collect_notes.py` 可随时重新汇总（幂等，覆盖同名文件）。

## 本次上传范围

`DesktopPlayer/`（桌面控制台）、`Tools/` 新增脚本、`docs/` 新增文档与预览图、
固件源码全部改动、`ProjectNotes/` 本目录。
