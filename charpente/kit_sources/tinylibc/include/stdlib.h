/* tinylibc: the parts of <stdlib.h> that need no operating system. There is deliberately no malloc/free:
 * embedded projects choose their allocator (FreeRTOS heap_4, a pool...). */
#ifndef TINYLIBC_STDLIB_H
#define TINYLIBC_STDLIB_H
#include <stddef.h>
#define EXIT_SUCCESS 0
#define EXIT_FAILURE 1
#ifdef __cplusplus
extern "C" {
#endif
int abs(int v);
long labs(long v);
int atoi(const char *s);
long strtol(const char *s, char **end, int base);
void abort(void) __attribute__((noreturn));
#ifdef __cplusplus
}
#endif
#endif
