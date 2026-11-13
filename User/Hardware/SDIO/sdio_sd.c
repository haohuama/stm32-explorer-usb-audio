/* ============================================================
 * sdio_sd.c —— TF 卡 SDIO 底层（P2.1：轮询读扇区，零 DMA / 零中断）
 *
 * 设计取舍（重要）：
 *   1) 用 HAL_SD_ReadBlocks() 轮询，不用 _DMA / _IT 版本。
 *      → 不占 DMA2_Stream3/6、不占 SDIO_IRQn，与已跑通的
 *        I2S(DMA1_Stream4) 和 USB(OTG_FS_IRQ) 完全隔离。
 *      → 代价是读扇区期间 CPU 忙等；P2.1 只在开机自检时读几个扇区，
 *        且自检放在 USB 与流播放启动之前，不影响任何实时链路。
 *      → P2.2 若证明轮询吞吐不够，再评估启用 SDIO DMA（DMA2，仍不冲突）。
 *   2) HAL_SD_MspInit() 在此提供强符号，覆盖 HAL 库的 __weak 版本。
 *      工程内已有 HAL_UART_MspInit(usart.c) / HAL_PCD_MspInit(usbd_conf.c)，
 *      不存在 HAL_SD_MspInit，不会重复定义。
 *   3) SDIO 时钟来自 PLL48CLK(48MHz)，与 USB 共用，时钟树无需改动。
 *
 * 引脚依据（两个独立来源一致，且为 F407 芯片固定复用）：
 *   MIT LibDriver  project/stm32f407/usr/src/stm32f4xx_hal_msp.c  L322-L339
 *   正点原子实验43 Drivers/BSP/SDIO/sdio_sdcard.c  HAL_SD_MspInit
 * ============================================================ */
#include "sdio_sd.h"

static SD_HandleTypeDef g_sd_handle;
static uint8_t  s_ready = 0;
static uint32_t s_sector_count = 0;
static uint32_t s_sector_size  = 0;
static uint32_t s_last_error   = 0;

/* ------------------------------------------------------------
 * HAL_SD_MspInit：SDIO 底层时钟与 GPIO
 * 注意：这里【故意不】使能 DMA2 时钟、【不】配置 DMA、【不】使能 SDIO_IRQn。
 * ------------------------------------------------------------ */
void HAL_SD_MspInit(SD_HandleTypeDef *hsd)
{
    GPIO_InitTypeDef gpio = {0};
    (void)hsd;

    __HAL_RCC_SDIO_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    /* PC8~PC12: D0/D1/D2/D3/SCK */
    gpio.Pin       = GPIO_PIN_8 | GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 | GPIO_PIN_12;
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_PULLUP;
    gpio.Speed     = GPIO_SPEED_FREQ_HIGH;
    gpio.Alternate = GPIO_AF12_SDIO;
    HAL_GPIO_Init(GPIOC, &gpio);

    /* PD2: CMD */
    gpio.Pin = GPIO_PIN_2;
    HAL_GPIO_Init(GPIOD, &gpio);
}

/* ------------------------------------------------------------
 * 初始化：1-bit 总线（最稳，先跑通再考虑 4-bit）
 * ClockDiv = 4 → 48MHz/(4+2) = 8MHz。
 * 说明：正点原子例程在轮询读时用了 __disable_irq() 防 FIFO 被打断；
 *       本项目【不】关全局中断（会干扰 USB/I2S），改为降低 SD 时钟：
 *       8MHz/1bit = 1MB/s，仍远高于 WAV 的 176400 B/s，P2.1 完全够用。
 *       P2.2 若需更高吞吐再评估 DMA2 或 4-bit（两者均不与 DMA1 冲突）。
 * ------------------------------------------------------------ */
uint8_t sd_init(void)
{
    HAL_StatusTypeDef st;
    HAL_SD_CardInfoTypeDef info;

    if (s_ready) return 0;

    g_sd_handle.Instance                     = SDIO;
    g_sd_handle.Init.ClockEdge               = SDIO_CLOCK_EDGE_RISING;
    g_sd_handle.Init.ClockBypass             = SDIO_CLOCK_BYPASS_DISABLE;
    g_sd_handle.Init.ClockPowerSave          = SDIO_CLOCK_POWER_SAVE_DISABLE;
    g_sd_handle.Init.BusWide                 = SDIO_BUS_WIDE_1B;
    g_sd_handle.Init.HardwareFlowControl     = SDIO_HARDWARE_FLOW_CONTROL_DISABLE;
    g_sd_handle.Init.ClockDiv                = 4u;   /* 48MHz/(4+2)=8MHz，轮询读留余量 */

    st = HAL_SD_Init(&g_sd_handle);
    s_last_error = (uint32_t)st;
    if (st != HAL_OK) return 1;

    st = HAL_SD_GetCardInfo(&g_sd_handle, &info);
    s_last_error = (uint32_t)st;
    if (st != HAL_OK) return 2;

    s_sector_count = info.LogBlockNbr;
    s_sector_size  = info.LogBlockSize;
    s_ready        = 1;
    return 0;
}

/* ------------------------------------------------------------
 * 轮询读扇区（P2.1 唯一的数据入口）
 * ------------------------------------------------------------ */
uint8_t sd_read_blocks(uint32_t sector, uint8_t *buf, uint32_t count)
{
    HAL_StatusTypeDef st;
    uint32_t tick;

    if (!s_ready)      return 3;
    if (buf == 0)      return 4;
    if (count == 0)    return 0;
    if (((uint32_t)buf & 3u) != 0u) return 5;   /* 必须 4 字节对齐 */

    st = HAL_SD_ReadBlocks(&g_sd_handle, buf, sector, count, 5000u);
    s_last_error = (uint32_t)st;
    if (st != HAL_OK) return 6;

    /* 等卡回到 Transfer 状态，避免紧接下一次读被拒 */
    tick = HAL_GetTick();
    while (HAL_SD_GetCardState(&g_sd_handle) != HAL_SD_CARD_TRANSFER) {
        if ((HAL_GetTick() - tick) > 5000u) return 7;
    }
    return 0;
}

uint32_t sd_sector_count(void) { return s_sector_count; }
uint32_t sd_sector_size(void)  { return s_sector_size;  }
uint8_t  sd_is_ready(void)     { return s_ready;        }
uint32_t sd_last_error(void)   { return s_last_error;   }
