/* ============================================================
 * usbd_conf.c —— USB 设备库硬件适配层（HAL 版）
 *
 * 把 ST 官方 USB 设备库绑定到 STM32F407ZGT6 的 USB_OTG_FS：
 *   - 实现全部 USBD_LL_* 底层函数（调用 HAL_PCD）
 *   - 重写 HAL_PCD_MspInit/MspDeInit（PA11/PA12 引脚 + 时钟 + NVIC）
 *   - 重写 HAL_PCD_*Callback（把 PCD 事件转交 USBD 层）
 *
 * 注意：本文件直接 include "usbd_core.h"（它内部会 include usbd_def.h
 * 和 usbd_conf.h），从而拿到 USBD_LL_* 的声明、USBD_StatusTypeDef 等类型，
 * 以及本工程的描述符宏。不要反过来让 usbd_conf.h include usbd_core.h，
 * 否则循环包含会让 usbd_def.h 在 uint8_t 尚未可见时被解析（全工程报错）。
 * ============================================================ */
#include "usbd_core.h"

/* USBD 句柄在 usb_device.c 定义 */
extern USBD_HandleTypeDef hUsbDeviceFS;

PCD_HandleTypeDef hpcd_USB_OTG_FS;

/* ------------------------------------------------------------
 * HAL_PCD_MspInit —— 引脚 / 时钟 / 中断（HAL 回调）
 * ------------------------------------------------------------ */
void HAL_PCD_MspInit(PCD_HandleTypeDef *pcdHandle)
{
    GPIO_InitTypeDef gpio = {0};

    if (pcdHandle->Instance != USB_OTG_FS) return;

    /* PA11 = USB_DM, PA12 = USB_DP，AF10，超高速 */
    __HAL_RCC_GPIOA_CLK_ENABLE();
    gpio.Pin       = GPIO_PIN_11 | GPIO_PIN_12;
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    gpio.Alternate = GPIO_AF10_OTG_FS;
    HAL_GPIO_Init(GPIOA, &gpio);

    /* USB_OTG_FS 时钟 */
    __HAL_RCC_USB_OTG_FS_CLK_ENABLE();

    /* 全局中断：抢占优先级 0（高于 DMA/串口） */
    HAL_NVIC_SetPriority(OTG_FS_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(OTG_FS_IRQn);
}

void HAL_PCD_MspDeInit(PCD_HandleTypeDef *pcdHandle)
{
    if (pcdHandle->Instance != USB_OTG_FS) return;

    __HAL_RCC_USB_OTG_FS_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_11 | GPIO_PIN_12);
    HAL_NVIC_DisableIRQ(OTG_FS_IRQn);
}

/* ------------------------------------------------------------
 * USBD_LL_* 底层绑定（USBD Core 调用，这里落到 HAL_PCD）
 * ------------------------------------------------------------ */
USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *pdev)
{
    hpcd_USB_OTG_FS.Instance              = USB_OTG_FS;
    hpcd_USB_OTG_FS.Init.dev_endpoints    = 4;
    hpcd_USB_OTG_FS.Init.speed            = PCD_SPEED_FULL;
    hpcd_USB_OTG_FS.Init.dma_enable       = DISABLE;       /* OTG_FS 无 DMA */
    hpcd_USB_OTG_FS.Init.phy_itface       = PCD_PHY_EMBEDDED;
    hpcd_USB_OTG_FS.Init.Sof_enable       = ENABLE;
    hpcd_USB_OTG_FS.Init.low_power_enable = DISABLE;
    hpcd_USB_OTG_FS.Init.lpm_enable       = DISABLE;
    hpcd_USB_OTG_FS.Init.vbus_sensing_enable = DISABLE;    /* 本板无 VBUS 检测脚 */
    hpcd_USB_OTG_FS.Init.use_dedicated_ep1   = DISABLE;

    if (HAL_PCD_Init(&hpcd_USB_OTG_FS) != HAL_OK) return USBD_FAIL;

    /* FIFO 分配：RX=0x60(96字) + EP0=0x10 + EP1=0x40 + EP2 CMD=0x10 = 0xE0(224) ≤ 0x140(320) */
    HAL_PCD_SetRxFiFo(&hpcd_USB_OTG_FS, 0x60);
    HAL_PCD_SetTxFiFo(&hpcd_USB_OTG_FS, 0, 0x10);
    HAL_PCD_SetTxFiFo(&hpcd_USB_OTG_FS, 1, 0x40);
    HAL_PCD_SetTxFiFo(&hpcd_USB_OTG_FS, 2, 0x10);

    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *pdev)
{
    (void)pdev;
    if (HAL_PCD_DeInit(&hpcd_USB_OTG_FS) != HAL_OK) return USBD_FAIL;
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *pdev)
{
    (void)pdev;
    HAL_PCD_Start(&hpcd_USB_OTG_FS);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *pdev)
{
    (void)pdev;
    HAL_PCD_Stop(&hpcd_USB_OTG_FS);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr,
                                  uint8_t ep_type, uint16_t ep_mps)
{
    (void)pdev;
    HAL_PCD_EP_Open(&hpcd_USB_OTG_FS, ep_addr, ep_mps, ep_type);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    HAL_PCD_EP_Close(&hpcd_USB_OTG_FS, ep_addr);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    HAL_PCD_EP_Flush(&hpcd_USB_OTG_FS, ep_addr);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    HAL_PCD_EP_SetStall(&hpcd_USB_OTG_FS, ep_addr);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    HAL_PCD_EP_ClrStall(&hpcd_USB_OTG_FS, ep_addr);
    return USBD_OK;
}

uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    PCD_EPTypeDef *ep = (ep_addr & 0x80) ? &hpcd_USB_OTG_FS.IN_ep[ep_addr & 0xF]
                                         : &hpcd_USB_OTG_FS.OUT_ep[ep_addr & 0xF];
    return (ep->is_stall) ? 1U : 0U;
}

USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *pdev, uint8_t dev_addr)
{
    (void)pdev;
    HAL_PCD_SetAddress(&hpcd_USB_OTG_FS, dev_addr);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *pdev, uint8_t ep_addr,
                                    uint8_t *pbuf, uint32_t size)
{
    (void)pdev;
    HAL_PCD_EP_Transmit(&hpcd_USB_OTG_FS, ep_addr, pbuf, size);
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *pdev, uint8_t ep_addr,
                                         uint8_t *pbuf, uint32_t size)
{
    (void)pdev;
    HAL_PCD_EP_Receive(&hpcd_USB_OTG_FS, ep_addr, pbuf, size);
    return USBD_OK;
}

uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    (void)pdev;
    return HAL_PCD_EP_GetRxCount(&hpcd_USB_OTG_FS, ep_addr);
}

void USBD_LL_Delay(uint32_t Delay)
{
    HAL_Delay(Delay);
}

/* 注：USBD_LL_SetSpeed / Reset / SetupStage / DataOutStage / DataInStage /
 *     SOF / Suspend / Resume / IsoINIncomplete / IsoOUTIncomplete /
 *     DevConnected / DevDisconnected 已在 usbd_core.c 中实现，
 *     此处【不可重复定义】，否则链接报 multiple definition。
 *     下面 HAL_PCD_*Callback 直接调用这些 core 版 USBD_LL_* 即可。 */

/* ------------------------------------------------------------
 * HAL_PCD_*Callback —— 把 PCD 中断事件转交 USBD 层
 * （这些是 __weak，这里提供强定义）
 * ------------------------------------------------------------ */
void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_SetupStage(&hUsbDeviceFS, (uint8_t *)hpcd->Setup);
}

void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_DataOutStage(&hUsbDeviceFS, epnum, hpcd->OUT_ep[epnum].xfer_buff);
}

void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_DataInStage(&hUsbDeviceFS, epnum, hpcd->IN_ep[epnum].xfer_buff);
}

void HAL_PCD_SOFCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_SOF(&hUsbDeviceFS);
}

void HAL_PCD_ResetCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_SetSpeed(&hUsbDeviceFS, USBD_SPEED_FULL);
    USBD_LL_Reset(&hUsbDeviceFS);
}

void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_Suspend(&hUsbDeviceFS);
}

void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_Resume(&hUsbDeviceFS);
}

void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_DevConnected(&hUsbDeviceFS);
}

void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *hpcd)
{
    (void)hpcd;
    USBD_LL_DevDisconnected(&hUsbDeviceFS);
}
