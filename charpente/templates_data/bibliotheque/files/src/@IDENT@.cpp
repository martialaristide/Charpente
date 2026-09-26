#include <@IDENT@/@IDENT@.hpp>

namespace @IDENT@ {
double mean(const std::vector<double>& values) {
    if (values.empty()) return 0.0;
    double sum = 0.0;
    for (double v : values) sum += v;
    return sum / static_cast<double>(values.size());
}

std::size_t argmax(const std::vector<double>& values) {
    if (values.empty()) return static_cast<std::size_t>(-1);
    std::size_t best = 0;
    for (std::size_t i = 1; i < values.size(); ++i) {
        if (values[i] > values[best]) best = i;
    }
    return best;
}
}  // namespace @IDENT@
