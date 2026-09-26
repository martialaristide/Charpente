/* tinylibc: the memory and string functions freestanding code needs (Charpente kit-embedded, MIT).
 * For toolchains with no C library (zig thumb-freestanding, bare clang). With arm-none-eabi-gcc use newlib instead. */
#ifndef TINYLIBC_STRING_H
#define TINYLIBC_STRING_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
void *memcpy(void *dst, const void *src, size_t n);
void *memmove(void *dst, const void *src, size_t n);
void *memset(void *dst, int c, size_t n);
int memcmp(const void *a, const void *b, size_t n);
void *memchr(const void *s, int c, size_t n);
size_t strlen(const char *s);
size_t strnlen(const char *s, size_t max);
char *strcpy(char *dst, const char *src);
char *strncpy(char *dst, const char *src, size_t n);
char *strcat(char *dst, const char *src);
int strcmp(const char *a, const char *b);
int strncmp(const char *a, const char *b, size_t n);
char *strchr(const char *s, int c);
char *strrchr(const char *s, int c);
#ifdef __cplusplus
}
#endif
#endif
