/* Vector table and reset handler: copies .data from flash, zeroes .bss, then calls main(). */
#include <stdint.h>

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
extern int main(void);

void Reset_Handler(void) {
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss;) *dst++ = 0;
    main();
    for (;;) {}
}

static void Default_Handler(void) { for (;;) {} }

__attribute__((section(".isr_vector"), used))
const void *const vector_table[] = {
    &_estack, Reset_Handler,                                   /* initial stack pointer, reset */
    Default_Handler, Default_Handler, Default_Handler, Default_Handler, Default_Handler,   /* NMI, faults */
    0, 0, 0, 0, Default_Handler, Default_Handler, 0, Default_Handler, Default_Handler,     /* SVC, PendSV, SysTick */
};
