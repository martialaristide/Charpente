#include <cstdio>
#include <emscripten/emscripten.h>

extern "C" {
// Callable from JavaScript: Module.ccall("add_numbers", "number", ["number", "number"], [2, 3])
EMSCRIPTEN_KEEPALIVE int add_numbers(int a, int b) { return a + b; }
}

int main() {
    std::printf("hello from @NAME@ in WebAssembly: 2 + 3 = %d\n", add_numbers(2, 3));
    return 0;
}
