# docs/img —— 界面预览图索引

这些图是 `Tools/preview_new.py` 按**固件真实点阵/像素**渲染的 800×480 预览，
不是真机照片。用于烧录前肉眼核对版式。

## 最终版（以这两张为准）

| 文件 | 内容 |
|---|---|
| `final_v3_s6.png` | 第 6 首《忘不掉的你》：默认漫画封面、40px 中文歌词、当前句**居中**、三个触屏按钮 |
| `final_v3_s5.png` | 第 5 首英文歌：无中文译文、长句折两行、40px 原生字模 |
| `desktop_app_live.png` | 桌面控制台真实启动截图（含桌面快捷方式） |

## 过程记录（保留作对照，不代表当前版式）

| 文件 | 阶段 |
|---|---|
| `preview_song1.png` / `preview_song5*.png` / `preview_boot.png` | 最早的「上图片下歌词」版式 |
| `preview_anim_0020.png` / `preview_anim_0134.png` | 当前句彩虹变色动效的两个色相 |
| `preview_big1.png` / `preview_big5.png` | 引入 40px 原生字模 |
| `new_s5.png` / `new_s6.png` | 改「左 1/3 图 + 右 2/3 歌词」 |
| `v3_s6.png` / `v4_s*.png` / `v5_s5.png` | ASCII 字宽 16→20、折行规则迭代 |
| `final_s1.png` / `final_s5.png` | 第 6 首加入、英文单语 |
| `center_s*.png` | 当前句改居中（遮罩尚未去掉） |
| `final_v2_s*.png` | 去掉大面积遮罩后的中间态 |
| `desktop_app.png` | 桌面软件早期版（无预置列表/封面） |

重新生成：

```bat
py Tools\preview_new.py --song 6 --time 01:10 --out docs\img\final_v3_s6.png
```
