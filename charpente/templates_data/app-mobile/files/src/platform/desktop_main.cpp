#include <cstdio>
#include "../engine/engine.hpp"

int main() {
    @IDENT@::start();
    @IDENT@::Counter c;
    c.tick();
    std::printf("%s\n", c.describe().c_str());
    return 0;
}
