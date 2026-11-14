# LCD 中文歌词流水线（FSMC 8080 + 精简 GBK 点阵 + 时间同步 + 曲目切换）

在探索者 F407 上用板载 **4.3" 800×480 FSMC 屏**显示滚动歌词的完整做法。
适用于任何"MCU 只有裸 PCM、不知道歌名和进度"的播放场景。

---

## 1. 硬件与驱动

| 项 | 值 |
|---|---|
| 屏 | 4.3" 800×480，16 位 8080 并口 |
| FSMC 引脚 | `CS=PG12` `RS=PF12` `WR=PD5` `RD=PD4` `BL=PB15`；数据线 PD0/1/4/5/8/9/10/14/15 + PE7~15 |
| 驱动 | 正点原子 HAL 版 `lcd.c / lcd.h / lcd_ex.c / lcdfont.h` |
| 函数风格 | 全小写：`lcd_init()` `lcd_display_dir(1)` `lcd_fill()` `lcd_show_string()` `LCD_BL(1)` |

**移植要改的三处**

1. `#include` 路径：`"./BSP/LCD/lcd.h"` → `"lcd.h"`（同目录）
2. **删掉驱动里的 `printf("LCD ID:%x")`** —— 工程没做 stdio 重定向时，`printf` 会走半主机（semi-hosting）→ 直接 HardFault。
   驱动源码里其实自己就写了这条注释警告。
3. `HAL_SRAM_MspInit()` 由 `lcd.c` **自带强符号**（配 FSMC 时钟/GPIO/时序），工程里不要再定义一份。

**与其它外设的冲突**：FSMC 占 PD0/1/4/5/8/9/10/14/15、PE7-15、PF12、PG12、PB15。
SDIO 用 PC8–PC12 + PD2（**不含 PD2 冲突**）；USB 是 PA11/PA12；I2S2 是 PB12/13 + PC3/PC6 —— 全部不重叠。

**必须补进工程**：`stm32f4xx_hal_sram.c` + `stm32f4xx_ll_fsmc.c`（`hal_conf.h` 里的 `HAL_SRAM_MODULE_ENABLED` 要开）。
不加就是一堆 `FSMC_NORSRAM_*` undefined —— 和 USB 缺 `hal_pcd.c` 是同一类坑。

---

## 2. 中文怎么显示（关键：不要依赖外部字库）

正点原子例程的中文显示依赖**外部 SPI Flash 上的字库 .BIN**（`TEXT/fonts.c` + `f_open`），
本机通常没有这个文件，而且它属于 V3 工程。**不要照搬**。

**做法：只把"屏上真正会出现的汉字"渲染成 16×16 点阵，编进固件。**

```python
# Tools/gen_cn_font.py 核心
font = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc", 16)
for ch in needed_chars:                       # 去重后的汉字集合
    img = Image.new("1", (16, 16), 0)
    ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=1)
    bits = pack_rows(img)                     # 每行 2 字节，MSB 在左
```

产物 `cn_font.h`：

```c
typedef struct { uint16_t gbk; const uint8_t bits[32]; } cn_glyph_t;
static const cn_glyph_t g_cn_font[] = {
    { 0xBDBD, { 0x00,0x00, ... } },   /* 江 */
    ...
};
#define CN_FONT_COUNT  (sizeof(g_cn_font)/sizeof(g_cn_font[0]))
```

- 每字 **32 字节**。100 字 ≈ 3.2KB，500 字 ≈ 16KB。
- 只含实际用字 → 比国标全字库（GB2312 约 120KB 点阵）省两个数量级。
- **代价**：换歌词若出现新字，必须重跑脚本 + 重新烧录。想彻底免烧就得把全字库放进外部 Flash 或走数据通道下发。

**查字必须容错**：`cn_bits(gbk)` 找不到就跳过（不画方块、不越界）。

---

## 3. 放大到 32px 但不加字模（省 Flash 的技巧）

16×16 点阵按 **2×2 像素块**绘制，等效 32×32，Flash 0 增长：

```c
/* 同一行连续亮点合并成一次 lcd_fill，把每字 ~256 次写窗口压到 ~50 次 */
for (row = 0; row < 16; row++) {
    line = (bits[row*2] << 8) | bits[row*2+1];
    col = 0;
    while (col < 16) {
        if (line & (0x8000 >> col)) {
            run = col;
            while (col < 16 && (line & (0x8000 >> col))) col++;
            lcd_fill(x + run*2, y + row*2, x + col*2 - 1, y + row*2 + 1, color);
        } else col++;
    }
}
```

布局参考（800×480）：标题 1 行 16px 小字 → 歌词 8 行 × 56px 行距，32px 字。
**每行最多 25 个汉字（800/32）**，超过会被截断，歌词行长度要提前核。

**性能**：只在"当前行变化"时才重画（约每 3~5 秒一次），不进任何中断。
整屏重画 20~30ms，不会让音频 DMA 欠载。

---

## 4. 歌词与歌声同步：时间基准是唯一的坑

### ❌ 错误做法
- `HAL_GetTick()` 累加 → 与音频实际播放脱钩（欠载/暂停/切歌全乱）
- 用"开机以来的 DMA 消费字节数" → DMA 空闲时播静音**也算消费**，所以"开机到点播放之间等了多久"会全部算进歌词进度

### ✅ 正确做法：只累计"真实 PCM 字节"

```c
/* 在 DMA refill（半传输/全传输回调）里，n = 本次从环形缓冲取到的真实字节 */
if (n > 0) {
    if (s_idle_cnt >= AUDIO_IDLE_RESYNC) s_pos_bytes = 0;  /* 断流 >1.5s → 重新开始 */
    s_pos_bytes += n;          /* 静音填充不计时 */
    s_idle_cnt = 0;
} else if (s_idle_cnt < 255) {
    s_idle_cnt++;
}

uint32_t audio_stream_position_ms(void)
{
    return (uint32_t)(((uint64_t)s_pos_bytes * 1000u) / 176400u);  /* 44.1k*2ch*2B */
}
```

效果：**点播放早晚都无所谓**，第一块真实数据就是 0 点；卡顿时歌词自动停住，恢复后继续对齐。

> 如果 mcu 端有多个数据源（USB / TF 卡），位置计数应统一放在"喂给 DMA 的公共出口"，
> 而不是各数据源各算一套。

---

## 5. 曲目切换：让上位机告诉设备"现在第几首"

裸 PCM 无法自描述，必须额外给一条信号。**不要用"时长取模猜曲目"**——顺序一变就错。

| 方案 | 表达范围 | 代价 |
|---|---|---|
| DTR/RTS（`SET_CONTROL_LINE_STATE` 的 wValue bit0/bit1） | **0..2**（3 是端口刚打开时两位都置 1 的默认态，必须忽略） | 0 字节 |
| **baudrate（`SET_LINE_CODING` 前 4 字节 LE）** | **任意**，用 `100000+idx` 区间限定 | 0 字节 |
| 第二个 CDC 接口 / 带 magic 的 in-band 头 | 无限（可传文本） | 要改描述符或污染音频流 |

**推荐：baudrate 编码**（PC 端一行 `ser.baudrate = 100000 + idx`）：

```c
case CDC_SET_LINE_CODING:            /* 0x20，7 字节 */
  linecoding.bitrate = pbuf[0] | pbuf[1]<<8 | pbuf[2]<<16 | pbuf[3]<<24;
  ...
  if (linecoding.bitrate >= 100000u && linecoding.bitrate < 100016u)
      lcd_ui_select_song(linecoding.bitrate - 100000u);
  break;
```

### 🔴 两条 CDC 控制路径的 pbuf 语义不同（易踩坑）

| 请求 | wLength | 传给 `Control()` 的 pbuf | 时机 |
|---|---|---|---|
| `SET_CONTROL_LINE_STATE`(0x22) | 0 | `(uint8_t *)req` —— **整个 Setup 包**，要 `((USBD_SetupReqTypedef*)pbuf)->wValue` | 立即 |
| `SET_LINE_CODING`(0x20) | 7 | `hcdc->data` —— **真正的 7 字节** | `EP0_RxReady` 里才回调 |

另外 `usbd_cdc_if.c` 模板里**本来就有**一个 `case CDC_SET_LINE_CODING`（保存 linecoding），
新逻辑必须**合并进那一条**，另开一个 case 就是 duplicate case 编译错误。

### 设备端收到选曲后
切歌词数据 → **歌词时钟清零**（`audio_stream_reset_position()`）→ 重画标题。
在 USB 中断里只置标志位，真正切数据/画屏放到主循环（`lcd_ui_tick` 开头处理）。

---

## 6. 换歌标准流程（脚本化，不手改 C）

```bat
py Tools/lrc_playlist.py "a.lrc" "b.lrc" "c.lrc" "d.lrc"   :: → lrc_data.h（s_titleN + s_lrcN）
py Tools/gen_cn_font.py                                    :: → cn_font.h（只渲染用到的字）
py Tools/check_lrc.py                                      :: 用与 C 相同规则模拟解析，须 0 空行
py Tools/check_font.py                                     :: 须"缺字:无"
py Tools/build_check.py --microlib                         :: 编译+链接+报体积
```

`lrc_playlist.py` 会自动剔除**带冒号的制作人员行**（`作词: xxx` / `吉他: xxx` / `OP: xxx`）
与 `VERSE1` / `CHORUS` 这类段落标记 —— 这些不该上屏，而且白吃字库空间。

`check_lrc.py` 的价值：它把 C 解析器的规则用 Python 复刻一遍，
能在编译前发现"某个歌词数组解析出 0 行 / 出现空正文"，避免烧完才发现屏上空白。

**加第 N+1 首要三处一起改**：`lrc_playlist.py` 的 `MAX_SONGS`、`lcd_ui.c` 的 `SONG_COUNT`、
`s_lrcs[]`/`s_titles[]` 表项。

---

## 7. 内存账（很容易忽略）

每首歌词解析结果 `ui_line_t[96]`（`uint32_t + char[64]` = 68 B/行）≈ **6.5 KB/首**。
4 首 ≈ 26 KB RAM。F407 有 128 KB，到 9 首左右就到顶。
再多就要改成"只保留当前曲的解析结果"（切曲时重新解析）。

---

## 8. 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 屏全黑，串口有 `[6] LCD` 打印 | 控制器型号不在保留列表 / 背光没开 | 打印 `lcddev.id`，只保留对应控制器分支；确认 `LCD_BL(1)` |
| 烧完直接 HardFault | 驱动里 `printf("LCD ID")` 半主机 | 删掉该行 |
| 缺 `FSMC_NORSRAM_*` undefined | 没加 `hal_sram.c`/`ll_fsmc.c` | 加入 uvprojx |
| 中文全是空白/方块 | 字库没覆盖这些字 | `py Tools/check_font.py` 查缺字，重跑 `gen_cn_font.py` |
| 歌词与歌声整体偏移固定秒数 | 用了"开机以来"的时间基准 | 改成"真实 PCM 字节"基准（见 §4） |
| 每轮循环歌词越来越偏 | 播放器循环发送，字节数持续累加 | 用整首歌长取模，或改用"选曲信号 + 位置清零" |
| 换歌后标题变了但歌词没变 | 只切了 title 没切 `s_cur` | 选曲处理里同时更新 `s_cur` / `s_cur_n` |
## 9. 播放器版式：上半屏封面 + 下半屏歌词（800×480）

800×480 屏做"音乐播放器"的稳妥版式：上半屏 240px 放封面+信息，下半屏 248..472 放滚动歌词。
实现见工程 `lcd_ui.c`，要点只有几条：

- **封面**：Python 把 jpg 转成 RGB565 `const uint16_t s_coverN[240*240]`（Flash 112KB），
  逐行 `lcd_set_cursor + lcd_write_ram_prepare + LCD->LCD_RAM` **直写 GRAM**；
  别用 `lcd_fill` 逐点上色（每次调用都要重设窗口，慢十倍以上）。
  无封面曲目就画竖向渐变 + 居中大号曲目序号占位，不要留黑块。
- **背景板**：另存一张 400×120 的"强模糊 + 压暗"图（96KB），屏上 2× 双线性放大铺满
  800×240，比直接存 800×240（375KB）省 3/4 Flash。
  **压暗之后必须再向右渐隐**（1.0 → 0.22 混近黑），否则右半边亮暗斑驳、白字压不住。
- **擦除一致性**：秒数刷新要先擦掉旧时间文字再重画。擦除与整屏铺底**必须共用同一个
  `bg_px(x,y)` 采样函数**，否则会留下错位的色块。
- **两种点阵方向不同**（最容易抄错）：
  - 汉字 `cn_font.h`：**行优先**，每行 2 字节，MSB = 最左
  - ASCII `asc2_1608`：**逐列式**，每列 2 字节（上 8 行 / 下 8 行），MSB = 最上
- **双语歌词**：一条记录的正文用 `\x01` 分隔原文与译文，渲染成「原文 32px + 译文 16px」一个块，
  一个块算一个滚动单元（步距 72px，屏上 3 块）；纯中文歌步距 44px，屏上 5 块。
  长句自动降一档字号，避免右边被切。
- **RAM**：别把 N 首歌全解析进 RAM（5 首 × 96 行 × 100B ≈ 48KB），只解当前曲目、换曲重解析，
  实测 72.6KB → 58KB。
- **烧前预览**：用同一批点阵/像素数据 + 同一套版式常量在 PC 上渲染 PNG
  （`Tools/preview_ui.py`），比"烧完再看"省一轮；两边常量要一起改。
