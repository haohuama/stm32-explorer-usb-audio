#include "i2c_soft.h"

/* 软件 I2C 半周期延时（≈100kHz 量级；HCLK=168MHz 下 120 拍约几微秒，可调）。
 * 探测对时序要求宽松，慢一点也行。 */
static void i2c_delay(void)
{
    for (volatile uint32_t i = 0; i < 120; i++);
}

void i2c_soft_init(const soft_i2c_t *bus)
{
    GPIO_InitTypeDef g = {0};
    if (bus->port == GPIOB) __HAL_RCC_GPIOB_CLK_ENABLE();

    g.Pin   = bus->scl_pin;
    g.Mode  = GPIO_MODE_OUTPUT_OD;   /* 开漏：I2C 必须 */
    g.Pull  = GPIO_PULLUP;           /* 板载已有 4.7k 上拉，内部上拉冗余但无害 */
    g.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(bus->port, &g);

    g.Pin   = bus->sda_pin;
    HAL_GPIO_Init(bus->port, &g);

    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
}

/* START + 8bit 地址(MSB 先) + 第9拍采样ACK + STOP。
 * 关键：全程只产生地址帧，绝不写寄存器数据 → 对从机零副作用。 */
uint8_t i2c_soft_probe_addr(const soft_i2c_t *bus, uint8_t addr)
{
    /* ---- START：SCL 高时 SDA 由高变低 ---- */
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_RESET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
    i2c_delay();

    /* ---- 8 位地址，MSB 先发 ---- */
    for (uint8_t i = 0; i < 8; i++) {
        HAL_GPIO_WritePin(bus->port, bus->sda_pin,
            (addr & (0x80u >> i)) ? GPIO_PIN_SET : GPIO_PIN_RESET);
        i2c_delay();
        HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
        i2c_delay(); i2c_delay();
        HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
        i2c_delay();
    }

    /* ---- 第9拍：释放 SDA（上拉成高），SCL 脉冲，采样从机应答 ---- */
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay(); i2c_delay();
    uint8_t ack = (HAL_GPIO_ReadPin(bus->port, bus->sda_pin) == GPIO_PIN_RESET) ? 1 : 0;
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
    i2c_delay();

    /* ---- STOP：SCL 高时 SDA 由低变高 ---- */
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_RESET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    i2c_delay();

    return ack;   /* 1 = ACK，0 = NACK */
}

/* ================================================================
 *  以下为「真正写寄存器」所需的总线原语
 *  （START / 写一字节并读 ACK / STOP）
 * ================================================================ */

/* START：SCL 高电平期间 SDA 由高变低 */
void i2c_soft_start(const soft_i2c_t *bus)
{
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_RESET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
    i2c_delay();
}

/* 写 1 字节（MSB 先），随后第 9 拍读从机 ACK。
 * 返回 0 = ACK 成功，1 = NACK 失败。 */
uint8_t i2c_soft_write_byte(const soft_i2c_t *bus, uint8_t byte)
{
    uint8_t i;

    for (i = 0; i < 8; i++) {
        HAL_GPIO_WritePin(bus->port, bus->sda_pin,
            (byte & (0x80u >> i)) ? GPIO_PIN_SET : GPIO_PIN_RESET);
        i2c_delay();
        HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
        i2c_delay(); i2c_delay();
        HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
        i2c_delay();
    }

    /* 第 9 拍：释放 SDA，SCL 脉冲，采样 ACK */
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay(); i2c_delay();
    uint8_t nack = (HAL_GPIO_ReadPin(bus->port, bus->sda_pin) == GPIO_PIN_SET) ? 1 : 0;
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_RESET);
    i2c_delay();

    return nack;
}

/* STOP：SCL 高电平期间 SDA 由低变高 */
void i2c_soft_stop(const soft_i2c_t *bus)
{
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_RESET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->scl_pin, GPIO_PIN_SET);
    i2c_delay();
    HAL_GPIO_WritePin(bus->port, bus->sda_pin, GPIO_PIN_SET);
    i2c_delay();
}
