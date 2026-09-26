#pragma once
#include <string>

namespace @IDENT@ {
// The logic lives in a library so the program and its tests share it.
std::string greet(const std::string& who);
}  // namespace @IDENT@
