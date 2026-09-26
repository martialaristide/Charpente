/* Blinks the LED on PD12 (the green one on STM32F4-Discovery boards) with a busy-wait delay. Register addresses are from
 * the STM32F407 reference manual (RM0090): RCC_AHB1ENR, GPIOD MODER/ODR. */
#include <stdint.h>

#define RCC_AHB1ENR (*(volatile uint32_t *)0x40023830u)
#define GPIOD_MODER (*(volatile uint32_t *)0x40020C00u)
#define GPIOD_ODR   (*(volatile uint32_t *)0x40020C14u)

static void delay(volatile uint32_t n) { while (n--) {} }

int main(void) {
    RCC_AHB1ENR |= (1u << 3);                     /* clock for GPIOD */
    GPIOD_MODER = (GPIOD_MODER & ~(3u << 24)) | (1u << 24);   /* PD12 as output */
    for (;;) {
        GPIOD_ODR ^= (1u << 12);
        delay(500000);
    }
}
