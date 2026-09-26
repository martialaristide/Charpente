#include <cmath>
#include <cstdio>
#include <@IDENT@/@IDENT@.hpp>

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAILED: %s (line %d)\n", #cond, __LINE__); ++failures; } } while (0)

int main() {
    CHECK(std::fabs(@IDENT@::mean({1.0, 2.0, 3.0}) - 2.0) < 1e-12);
    CHECK(@IDENT@::mean({}) == 0.0);
    CHECK(@IDENT@::argmax({1.0, 9.0, 3.0}) == 1);
    CHECK(@IDENT@::argmax({}) == static_cast<std::size_t>(-1));
    return failures == 0 ? 0 : 1;
}
