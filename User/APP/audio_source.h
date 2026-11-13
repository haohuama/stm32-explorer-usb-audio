/* ============================================================
 * audio_source.h —— P2.0 统一切源接口契约（模块1/2/3 共用）
 *
 * 为什么先做这一层：
 *   规划文档把「切源状态机」放在 P2.7，但模块1 已经要求补
 *   src_start/stop 与可用性检测接口，模块3 也要接入同一套。
 *   若先把 TF 播放写死在 main 里，到 P2.7 一定返工。
 *   本文件只定契约与状态机数据结构，不改动任何已冻结的音频代码。
 *
 * 核心不变量（文档「贯穿原则」）：
 *   - 三模式共用同一输出链：audio_stream_push() → 环形 → DMA → I2S → WM8978
 *   - 切源统一流程：静音 → 停 DMA → 切源 → 启新源 → 取消静音
 *   - UI/动效只读播放状态，不反向控制音频
 *   - playback_ms 由 DMA 实际消费字节数推算（176400 B/s），不用 HAL_GetTick
 * ============================================================ */
#ifndef __AUDIO_SOURCE_H
#define __AUDIO_SOURCE_H

#include <stdint.h>

#define AUDIO_BYTES_PER_SEC   176400u   /* 44100Hz * 2ch * 2byte */

typedef enum {
    SRC_NONE = 0,        /* 未选源 / 静音 */
    SRC_USB_CDC,         /* 模式1：电脑经 USB CDC 推 PCM（已交付） */
    SRC_TF_WAV,          /* 模式2：TF 卡 f_read 拉 PCM（模块2） */
    SRC_BT_LINEIN,       /* 模式3：蓝牙模拟 LINE-IN，MCU 不参与音频 */
    SRC_MAX
} src_mode_t;

/* 每个数据源必须实现的操作集；不用的可置 NULL */
typedef struct {
    int      (*start)(void);           /* 启动，0=成功 */
    void     (*stop)(void);            /* 停止并释放资源 */
    int      (*is_available)(void);    /* 源是否可用/有数据，1=可用 */
    void     (*feed)(void);            /* 主循环里给环形缓冲补数据（禁入中断） */
    uint32_t (*duration_ms)(void);     /* 当前曲目总长，无则 0 */
    const char *path;                  /* 当前曲目路径（TF 模式有效） */
} src_ops_t;

/* ---------- 状态机 ---------- */
void       src_init(void);
int        src_register(src_mode_t mode, const src_ops_t *ops);

/* 切换数据源：按「静音→停→切→启→取消静音」顺序执行。
   P2.1 阶段 do_hw_mute 传 0（不碰音频），仅做状态切换，零风险。 */
int        src_switch(src_mode_t mode, int do_hw_mute);

src_mode_t src_current(void);
int        src_is_available(void);
void       src_feed(void);             /* 主循环调用，禁止在 DMA 中断里调用 */

/* ---------- 播放进度（供 LRC / 列表 / 封面只读） ---------- */
/* 由 DMA 双缓冲 refill 累加：每消费 1 字节调用一次计数 */
void       src_add_consumed_bytes(uint32_t bytes);
void       src_reset_playback(void);
uint32_t   src_playback_ms(void);      /* = consumed / 176.4 */
uint32_t   src_duration_ms(void);
const char *src_current_path(void);

/* ---------- 播放列表状态（P2.2/P2.3 使用，此处先占位） ---------- */
void       src_set_index(int index, int total);
int        src_play_index(void);
int        src_play_total(void);
void       src_next(void);
void       src_prev(void);

#endif
