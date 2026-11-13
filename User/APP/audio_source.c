/* ============================================================
 * audio_source.c —— P2.0 统一切源状态机实现
 *
 * 边界声明（P2.1）：
 *   - 本文件【不】include i2s_audio.h、【不】调用 audio_stream_* 任何函数。
 *   - src_switch(do_hw_mute=1) 的「静音/停DMA/启」钩子在 P2.7 接入，
 *     目前只做状态切换与可用性检查，因此编译进工程对模块1 零影响。
 *   - playback_ms 由 src_add_consumed_bytes() 累加；P2.2 在 DMA refill
 *     回调里接一行即可，P2.1 不接（自检阶段不播放）。
 * ============================================================ */
#include "audio_source.h"

typedef struct {
    const src_ops_t *ops[SRC_MAX];
    src_mode_t       cur;
    uint64_t         consumed_bytes;   /* 累计被 DMA 消费的 PCM 字节数 */
    int              play_index;
    int              play_total;
} src_state_t;

static src_state_t s;

void src_init(void)
{
    int i;
    for (i = 0; i < SRC_MAX; i++) s.ops[i] = 0;
    s.cur            = SRC_NONE;
    s.consumed_bytes = 0;
    s.play_index     = 0;
    s.play_total     = 0;
}

int src_register(src_mode_t mode, const src_ops_t *ops)
{
    if (mode <= SRC_NONE || mode >= SRC_MAX || ops == 0) return -1;
    s.ops[mode] = ops;
    return 0;
}

static const src_ops_t *cur_ops(void)
{
    return (s.cur > SRC_NONE && s.cur < SRC_MAX) ? s.ops[s.cur] : 0;
}

int src_switch(src_mode_t mode, int do_hw_mute)
{
    const src_ops_t *old = cur_ops();
    const src_ops_t *nw;

    if (mode >= SRC_MAX) return -1;
    nw = (mode > SRC_NONE) ? s.ops[mode] : 0;
    if (mode > SRC_NONE && nw == 0) return -2;      /* 该源未注册 */

    /* ---- 统一切源流程 ---- */
    /* ① 静音 + 停 DMA：P2.7 接入 audio_stream_stop()/WM8978 mute。
          P2.1 的 do_hw_mute=0，此处为空，不碰任何音频外设。 */
    if (do_hw_mute) {
        /* TODO(P2.7): audio_stream_stop(); WM8978_SPKvol_Set(0); */
    }

    /* ② 停旧源 */
    if (old && old->stop) old->stop();

    /* ③ 切源 + 复位播放计数 */
    s.cur            = mode;
    s.consumed_bytes = 0;

    /* ④ 启新源 */
    if (nw && nw->start) {
        if (nw->start() != 0) return -3;
    }

    /* ⑤ 取消静音：P2.7 接入 audio_stream_start() + 恢复音量 */
    if (do_hw_mute) {
        /* TODO(P2.7): WM8978_SPKvol_Set(0x3F); audio_stream_start(); */
    }
    return 0;
}

src_mode_t src_current(void) { return s.cur; }

int src_is_available(void)
{
    const src_ops_t *o = cur_ops();
    return (o && o->is_available) ? o->is_available() : 0;
}

void src_feed(void)
{
    const src_ops_t *o = cur_ops();
    if (o && o->feed) o->feed();      /* 只在主循环调用 */
}

/* ---------- 播放进度：由 DMA 实际消费字节数推算 ---------- */
void src_add_consumed_bytes(uint32_t bytes)
{
    s.consumed_bytes += bytes;
}

void src_reset_playback(void) { s.consumed_bytes = 0; }

uint32_t src_playback_ms(void)
{
    /* 用整数除法避免引入浮点库：bytes * 1000 / 176400
       consumed_bytes 为 uint64_t，乘法提升到 64bit 不会溢出 */
    return (uint32_t)((s.consumed_bytes * 1000u) / AUDIO_BYTES_PER_SEC);
}

uint32_t src_duration_ms(void)
{
    const src_ops_t *o = cur_ops();
    return (o && o->duration_ms) ? o->duration_ms() : 0u;
}

const char *src_current_path(void)
{
    const src_ops_t *o = cur_ops();
    return (o && o->path) ? o->path : "";
}

/* ---------- 播放列表 ---------- */
void src_set_index(int index, int total)
{
    s.play_index = index;
    s.play_total = (total > 0) ? total : 0;
}
int  src_play_index(void) { return s.play_index; }
int  src_play_total(void) { return s.play_total; }

void src_next(void)
{
    if (s.play_total <= 0) return;
    s.play_index = (s.play_index + 1) % s.play_total;
    s.consumed_bytes = 0;
}
void src_prev(void)
{
    if (s.play_total <= 0) return;
    s.play_index = (s.play_index - 1 + s.play_total) % s.play_total;
    s.consumed_bytes = 0;
}
