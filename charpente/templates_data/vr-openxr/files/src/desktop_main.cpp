#include <cstdio>

#include "xr_probe.hpp"

int main() {
    const XrProbeResult result = probe_openxr();
    std::printf("%s\n", result.text.c_str());
    return result.ok ? 0 : 1;
}
