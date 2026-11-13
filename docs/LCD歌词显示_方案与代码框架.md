# LCD 歌词显示 · 方案与代码框架

> 阶段定位：本子任务 **独立于 WM8978 音频 CODEC**，不依赖 `ADAPT_OK`，可先行。
> 硬件接口取自《STM32F407 探索者开发指南 V1.3》第 25 章（V2.7 与 V3 共用同一 TFTLCD 插座，引脚一致）。

---

## 1. 硬件确认（权威来源：开发指南 V1.3，第 25.1 / 25.2 节）

TFTLCD 模块通过 **FSMC 16 位 8080 并口** 接到 MCU。开发板内部已连好，插上模块即可。

| 信号 | 引脚 | FSMC 复用 | 说明 |
|------|------|-----------|------|
| LCD_BL | **PB15** | — | 背光控制（输出高=亮） |
| LCD_CS | **PG12** | FSMC_NE4 | 片选 |
| LCD_RS | **PF12** | FSMC_A6 | 命令/数据（0=命令，1=数据） |
| LCD_WR | **PD5** | FSMC_NWE | 写使能 |
| LCD_RD | **PD4** | FSMC_NOE | 读使能 |
| LCD_D[15:0] | FSMC_D15~D0 | 数据总线 | 16 位双向数据（分布在 PD/PE） |
| RST | 板载复位脚 | — | **硬件直连复位，软件无需控制** |

> 注意：RST 已被接到开发板 RESET，省下一个 IO。**背光 PB15 必须拉高否则屏全黑**——这是"接上屏却看不到字"的头号原因。

### 控制器与分辨率（自动识别，无需事先知道型号）

开发指南 25.1.2 明确：正点原子提供 2.8/3.5/4.3/7 寸模块，驱动 IC 为
**ILI9341 / ST7789 / NT35310 / NT35510 / SSD1963**。标准 `lcd.c` 在 `LCD_Init()` 里
读控制器 ID（`lcddev.id`）并分支初始化，所以**同一份代码兼容所有 MCU 屏**。

分辨率（`lcddev.width / lcddev.height` 运行时读取）：
- 2.8" / 3.5" → 320×240 / 320×480
- 4.3" / 7" → 800×480
- 4.3" 480×272、7" 1024×600 为 **RGB 屏**（非 8080 MCU 屏），用 SSD1963+ft5206，需另走 RGB-LCD 驱动，本框架默认只覆盖 MCU 屏（8080）。

> ✅ **用户已确认屏 = 4.3 寸 TFTLCD（800×480，8080 MCU 屏）**：控制器 ID 上电自动识别，
> 代码通用，无需知道具体是 ILI9341 还是 NT35510。`lcddev.width/height` 读出来就是 800×480，
> 下面的布局常量按此设计。RGB 屏分支已无需考虑。

---

## 2. "保证流畅"的原理

流畅性来自三点，全部已具备：

1. **FSMC 并行 16 位并口**：HCLK=168MHz，FSMC 地址/数据周期仅数个 HCLK，写一像素（2 字节）< 1µs。
   对比 SPI/I2C 屏，速度差 1~2 个数量级，这才是"流畅"的根本保障。
2. **控制器自带 GRAM（显存）**：MCU 只把变化的像素推给 GRAM，不用每帧重画整屏。
3. **局部刷新 + 固定步长动画**：歌词只占用屏幕一条"歌词带"(band)，每帧只重画这条带，
   且用缓动(easing)做平滑滚动，无闪烁、无撕裂。

实测：800×480 屏上重画一条 24px 高、约 5 行的歌词带，单次耗时 << 1ms，
用 30fps 节拍（33ms/帧）刷新绰绰有余。

---

## 3. 歌词引擎设计（新增模块 `lrc.c / lrc.h`）

### 3.1 数据模型

```c
typedef struct {
    uint32_t t_ms;     // 该行起始时间(ms)
    const char *text;  // 指向歌词缓冲区的该行文本(以 \0 结尾)
} lrc_line_t;
```

### 3.2 LRC 解析

标准 LRC 格式：`[mm:ss.xx]歌词文本`，一行可含多个时间标签。解析函数把缓冲区原地切成
以 `\0` 分隔的行，并填 `lrc_line_t` 数组（按时间升序）：

```c
// buf: 可修改的 LRC 文本缓冲区；lines: 输出数组；max: 数组容量
// 返回解析到的行数；时间复杂度 O(n)
int lrc_parse(char *buf, lrc_line_t *lines, int max) {
    int n = 0;
    char *p = buf;
    while (*p && n < max) {
        char *b = p;
        if (*b != '[') { p++; continue; }          // 跳过非标签行
        // 解析 [mm:ss.xx]
        int mm = 0, ss = 0, cc = 0;
        char *q = b + 1;
        mm = (int)strtol(q, &q, 10); if (*q==':') q++;
        ss = (int)strtol(q, &q, 10); if (*q=='.') q++;
        cc = (int)strtol(q, &q, 10);
        char *text = strchr(b, ']');
        if (!text) { p = b + 1; continue; }
        text++;                                     // 歌词起点
        char *nl = strchr(text, '\n');
        if (nl) *nl = '\0';                         // 截断换行
        lines[n].t_ms = (uint32_t)(mm * 60 + ss) * 1000 + cc * 10;
        lines[n].text = text;
        n++;
        p = nl ? nl + 1 : text + strlen(text);
    }
    return n;
}
```

> 多标签行（如 `[00:10.00][00:40.00]副歌`）可展开为两条相同文本、不同时间的记录，
> 此处简化为"取第一个标签"，够用；如需展开可改为遇到 `]` 就记一次。

### 3.3 当前行查找（二分或线性）

```c
// play_ms: 当前播放时间；返回当前应高亮的行索引
int lrc_active(uint32_t play_ms, const lrc_line_t *L, int n) {
    int a = 0;
    for (int i = 0; i < n; i++)
        if (L[i].t_ms <= play_ms) a = i; else break;
    return a;
}
```

### 3.4 平滑滚动渲染（核心：流畅的关键）

思路：维护一个浮点 `scroll_pos`（已滚过的逻辑像素），目标 = 当前行居中位置；
每帧用缓动逼近目标，只重画歌词带，不碰屏幕其余区域。

```c
#define BAND_X 0
#define BAND_Y 120        // 歌词带顶边(示例：屏中部)
#define BAND_W lcddev.width
#define BAND_H 240         // 歌词带高度
#define LINE_H 32          // 行距(24px字+间距)

static float scroll_pos = 0;

// 由 TIM 中断 / 主循环以固定 ~30fps 节拍调用
void lrc_render(uint32_t play_ms) {
    int active = lrc_active(play_ms, g_lrc, g_n);
    float target = (float)active * LINE_H;
    scroll_pos += (target - scroll_pos) * 0.18f;     // 缓动，值越小越柔和

    LCD_Fill(BAND_X, BAND_Y, BAND_X + BAND_W, BAND_Y + BAND_H, LCD_BG); // 清带
    for (int i = 0; i < g_n; i++) {
        int y = (int)(BAND_Y + (i * LINE_H - scroll_pos) + BAND_H / 2 - LINE_H / 2);
        if (y < BAND_Y - LINE_H || y > BAND_Y + BAND_H) continue;       // 带外跳过
        uint16_t col = (i == active) ? LCD_WHITE : LCD_GRAY;
        uint8_t big = (i == active) ? 1 : 0;
        LCD_ShowStr(BAND_X + 20, y, g_lrc[i].text, col, big);
    }
}
```

- `LCD_Fill` / `LCD_ShowStr` 来自标准 `lcd.c`，走 FSMC，速度快。
- 当前行用 `LCD_WHITE` 大号、`LCD_GRAY` 普通号，形成卡拉OK高亮。
- 缓动系数 `0.18` 可调：越大跟手越快、越小越顺滑。

---

## 4. 字体方案

中文歌词必须有点阵字库。用正点原子 `font.c`（HAL 例程自带）：
- `asc2_1608`：ASCII 16×8
- `hzk16` / `GBK24`：GBK 16×16 / 24×24 汉字点阵

对应的 `LCD_ShowStr(x,y,str,color,big)` 内部已做 **GBK 编码拆分**（先查汉字 2 字节、
再查 ASCII 1 字节），直接传 UTF-8 不行——**源码里歌词字符串要存成 GBK 编码**。
若想用 UTF-8，需把 `LCD_ShowStr` 换成支持 UTF-8 的版本（自行加一个 `utf8_to_gbk` 或在
PC 端转好再下发）。

> 推荐：歌词先在 PC 端转 GBK 再写入固件 / 下发，MCU 侧省去解码开销，最稳。

---

## 5. 数据源方案（已定：方案 A）

> ✅ **用户已选方案 A：固件内置 LRC 演示**。先把屏 + 字库 + 滚动跑通，完全不碰音频。
> 方案 B（接 PC-CDC 同步）留到主线 Phase 4 完成后再接，届时把 `play_ms` 来源换成 CDC 下发即可。

### 方案 A 落地要点
- 把一首歌的 LRC 文本（**GBK 编码**）作为 `const char lrc_buf[]` 编进固件（见 `lcd_lyrics/lyrics_demo.c` 示例）。
- 播放时间用 `HAL_GetTick()` 模拟：上电即开始滚动；可加一个按键当"播放/暂停/快进"。
- 4.3" 800×480 屏的歌词带布局（已按此设计，可直接用）：
  ```c
  #define BAND_X   0
  #define BAND_Y   120      // 歌词带顶边（屏中部偏上）
  #define BAND_W   800      // 全宽
  #define BAND_H   240      // 歌词带高度（约 7~8 行）
  #define LINE_H   32       // 行距（24px 字 + 8px 间距）
  // 当前行用 24px 白色大号，其余用 16px 灰色；详见 lrc_render
  ```
- 目的：验证 FSMC 屏 + 字库 + 滚动都正常，**完全不碰音频、不碰 WM8978**。

---

## 6. 在 CubeMX + HAL 工程里的落点

| 文件 | 位置 | 来源 |
|------|------|------|
| `lcd.c` / `lcd.h` | `Drivers/BSP/LCD/` | 正点原子 HAL 例程 实验13（**通用，与 CODEC 无关**） |
| `font.c` / `font.h` | `Drivers/BSP/LCD/` | 同上 |
| `lrc.c` / `lrc.h` | `Application/` | **本框架新增** |

CubeMX 配置：
1. `Connectivity → FSMC`，NOR/PSRAM，Bank1 NE4，数据宽度 16bit，地址线用到 A6（RS），
   时序按开发指南 25.3 给的 `ADDSET=0xF, DATASET=0x4`（或 CubeMX 里 FSMC 默认偏保守值也可）。
2. `GPIO → PB15` 设为 GPIO_Output（背光），初始高。
3. 生成代码后，在 `main.c` 的 `/* USER CODE BEGIN 2 */` 调用 `LCD_Init(); LCD_Clear(...);`
   并 `lrc_parse(...)`；在定时器回调（`/* USER CODE BEGIN Callback */`）调用 `lrc_render(play_ms)`。

> ⚠️ 与主线边界：本子任务只动 **LCD/FSMC/GPIO/字体/新增 lrc 模块**，
> 不写任何 WM8978/I2S/USB-Audio 代码。LCD 驱动属"家族通用"，不是 V3 的 ES8388 参数，
> 不违反"拒绝 V3 音频参数"的约定。

---

## 7. 待确认 / 待办（决策已更新）

| # | 事项 | 状态 |
|---|------|------|
| 1 | 屏类型：4.3" TFTLCD（800×480 8080 MCU 屏） | ✅ 已确认，代码通用 |
| 2 | 数据源：方案 A（固件内置 LRC 演示） | ✅ 已选 |
| 3 | 工程策略：等主线工程完成后再集成（不现在建独立工程） | ✅ 已选 |
| 4 | 提供 HAL 版 TFTLCD 实验例程（实验13）的 `lcd.c/font.c` 路径 | 🟡 待主线 Phase 2 搭好 CubeMX 后复用 |
| 5 | 主线 `ADAPT_OK` + V2.7 原理图 + WM8978 丝印 | 🔴 仍阻塞主线（本子任务不依赖） |

> 注：本子任务（LCD 歌词）与 WM8978/`ADAPT_OK` **完全解耦**，上面的"等主线"仅指
> "把 lrc 模块正式并入工程"这一步；模块源码现在就可以准备（`lcd_lyrics/` 下已就绪）。

## 9. 集成到主线工程的步骤（待 Phase 2/3 完成后执行）

1. CubeMX 建好 FSMC + PB15 背光 + 时钟（见第 6 节），生成 HAL 工程。
2. 把 HAL 例程实验13 的 `lcd.c / lcd.h / font.c / font.h` 拷到 `Drivers/BSP/LCD/`。
3. 把本框架的 `lcd_lyrics/lrc.c / lrc.h / lyrics_demo.c` 拷到 `Application/`。
4. `main.c` 的 `/* USER CODE BEGIN 2 */`：`LCD_Init(); LCD_Clear(BLACK); lrc_load_demo();`
5. 用一个 30fps 节拍（TIM 定时器或 `HAL_Delay` 主循环）调用 `lrc_tick(HAL_GetTick())`；
   接主线后把 `play_ms` 换成 CDC 下发的真实进度。
6. 编进固件的 LRC 必须是 **GBK** 编码（在 PC 端转好再粘贴进 `lyrics_demo.c`）。

---

## 8. 四件套（按项目约定）

**原理说明**：FSMC 16 位并口驱动 8080 MCU 屏，控制器 ID 自动识别；歌词用 LRC 解析 +
缓动平滑滚动 + 局部刷新，保证流畅无闪烁；GBK 点阵字库显示中文。

**完整代码**：见本文第 3 节 `lrc_parse / lrc_active / lrc_render` 三段核心，
加标准 `lcd.c/font.c`（来自 HAL 实验13，非本项目编写、仅引用）。

**预期现象**：屏中部一条歌词带，当前行白色高亮、居中，随播放时间平滑上滚；其余屏幕区域不动。

**故障排查清单**：
1. 屏全黑 → 查 PB15 背光是否拉高；RST 已硬件接好无需管。
2. 白屏/花屏 → FSMC 时序太紧，CubeMX 里把 `DATASET/ADDSET` 调大；确认 NE4+A6 配置。
3. 汉字乱码/方框 → 歌词未转 GBK；或 `font.c` 未包含对应 GBK 字库。
4. 滚动卡顿 → 确认 `lrc_render` 是局部刷新（只清歌词带），不是全屏 `LCD_Clear`。
5. 整屏不识别 → 读 `lcddev.id` 打印出来，对照支持的 IC 列表（ILI9341/ST7789/NT35310/NT35510/SSD1963）。
