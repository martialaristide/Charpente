#include <cstdio>
#include "greet.hpp"

int main(int argc, char** argv) {
    std::printf("%s\n", @IDENT@::greet(argc > 1 ? argv[1] : "").c_str());
    return 0;
}
