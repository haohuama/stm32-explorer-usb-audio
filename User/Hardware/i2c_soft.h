#ifndef __I2C_SOFT_H
#define __I2C_SOFT_H
#include "stm32f4xx_hal.h"

/* 软件 I2C（GPIO 模拟）——不依赖具体 I2C 外设，任意 GPIO 都能用。
 * 本板 CODEC 三对候选引脚都在 GPIOB 上，故结构里只放一个 port。 */
typedef struct {
    GPIO_TypeDef *port;   /* SCL / SDA 所在端口（均为 GPIOB） */
    uint16_t scl_pin;
    uint16_t sda_pin;
} soft_i2c_t;

/* 配置 SCL/SDA 为开漏输出 + 上拉，并置空闲高电平 */
void i2c_soft_init(const soft_i2c_t *bus);

/* 只发一个 I2C 地址帧：START + addr(8bit) + 第9拍采样ACK + STOP。
 * 不写任何寄存器，对从机零修改，安全。返回 1=ACK，0=NACK。 */
uint8_t i2c_soft_probe_addr(const soft_i2c_t *bus, uint8_t addr);

/* ---- 以下为「真正写寄存器」用的底层原语（供 WM8978 驱动调用）----
 * 语义说明（与正点原子 xSoftIIC_WriteByte 一致）：
 *   返回 0 = 收到 ACK（成功）；返回 1 = NACK 或总线异常（失败）。 */
void    i2c_soft_start(const soft_i2c_t *bus);
uint8_t i2c_soft_write_byte(const soft_i2c_t *bus, uint8_t byte);   /* 0=ACK, 1=NACK */
void    i2c_soft_stop(const soft_i2c_t *bus);

#endif /* __I2C_SOFT_H */
