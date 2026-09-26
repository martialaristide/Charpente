/* tinylibc stdlib.h implementation (no allocator: see the header). */
#include <stdlib.h>

int abs(int v) { return v < 0 ? -v : v; }
long labs(long v) { return v < 0 ? -v : v; }

long strtol(const char *s, char **end, int base) {
    const char *p = s;
    long sign = 1, value = 0;
    while (*p == ' ' || (*p >= '\t' && *p <= '\r')) ++p;
    if (*p == '-') { sign = -1; ++p; } else if (*p == '+') { ++p; }
    if ((base == 0 || base == 16) && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { p += 2; base = 16; }
    else if (base == 0) { base = (p[0] == '0') ? 8 : 10; }
    for (;; ++p) {
        int digit;
        if (*p >= '0' && *p <= '9') digit = *p - '0';
        else if (*p >= 'a' && *p <= 'z') digit = *p - 'a' + 10;
        else if (*p >= 'A' && *p <= 'Z') digit = *p - 'A' + 10;
        else break;
        if (digit >= base) break;
        value = value * base + digit;
    }
    if (end) *end = (char *)p;
    return sign * value;
}

int atoi(const char *s) { return (int)strtol(s, 0, 10); }

void abort(void) {
    for (;;) {}
}
