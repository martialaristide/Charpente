#include "greet.hpp"

namespace @IDENT@ {
std::string greet(const std::string& who) { return "Hello, " + (who.empty() ? std::string("world") : who) + "!"; }
}  // namespace @IDENT@
