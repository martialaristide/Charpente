#include <cstdio>
#include "../src/engine/engine.hpp"

int main() {
    @IDENT@::Counter c;
    c.tick();
    c.tick();
    if (c.describe() != "counter=2") { std::printf("FAILED: %s\n", c.describe().c_str()); return 1; }
    return 0;
}
