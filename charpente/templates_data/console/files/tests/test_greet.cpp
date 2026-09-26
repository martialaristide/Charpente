#include <cstdio>
#include "greet.hpp"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAILED: %s (line %d)\n", #cond, __LINE__); ++failures; } } while (0)

int main() {
    CHECK(@IDENT@::greet("Ada") == "Hello, Ada!");
    CHECK(@IDENT@::greet("") == "Hello, world!");
    return failures == 0 ? 0 : 1;
}
