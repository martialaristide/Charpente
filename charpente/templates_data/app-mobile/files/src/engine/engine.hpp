#pragma once
#include <string>

namespace @IDENT@ {
// Platform-independent game/app logic. Put your code here; test it on the desktop.
struct Counter {
    int value = 0;
    void tick() { ++value; }
    std::string describe() const;
};

void install();          // installs the lifecycle handler (call before the platform attaches, so Create is delivered)
void start();            // called once by each platform's entry point, after the platform layer is attached
}  // namespace @IDENT@
