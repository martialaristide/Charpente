#include <cstdio>
#include <@IDENT@/@IDENT@.hpp>

int main() {
    const std::vector<double> values{1.0, 4.0, 2.5};
    std::printf("mean=%.2f argmax=%zu\n", @IDENT@::mean(values), @IDENT@::argmax(values));
    return 0;
}
