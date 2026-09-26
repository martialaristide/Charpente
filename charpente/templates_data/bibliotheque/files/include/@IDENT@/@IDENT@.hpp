#pragma once
#include <cstddef>
#include <vector>

namespace @IDENT@ {
// Mean of the values; 0 for an empty list.
double mean(const std::vector<double>& values);
// Index of the largest value; std::size_t(-1) for an empty list.
std::size_t argmax(const std::vector<double>& values);
}  // namespace @IDENT@
