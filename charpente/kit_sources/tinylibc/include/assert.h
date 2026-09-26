/* tinylibc: assert() that calls abort() (define NDEBUG to remove it). */
#ifndef TINYLIBC_ASSERT_H
#define TINYLIBC_ASSERT_H
#include <stdlib.h>
#ifdef NDEBUG
#define assert(expr) ((void)0)
#else
#define assert(expr) ((expr) ? (void)0 : abort())
#endif
#endif
