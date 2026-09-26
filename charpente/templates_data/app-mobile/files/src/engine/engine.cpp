#include "engine.hpp"

#include <charpente/mobile.hpp>

namespace mobile = charpente::mobile;

namespace @IDENT@ {
std::string Counter::describe() const { return "counter=" + std::to_string(value); }

static void on_event(mobile::Event event, void*) {
    mobile::log(mobile::LogLevel::Info, "@IDENT@", "lifecycle: %s", mobile::event_name(event));
}

void install() { mobile::set_handler(on_event, nullptr); }

void start() {
    install();
    mobile::log(mobile::LogLevel::Info, "@IDENT@", "running on %s", mobile::platform_name());
    std::vector<unsigned char> bytes;
    if (mobile::read_asset("hello.txt", bytes)) {
        mobile::log(mobile::LogLevel::Info, "@IDENT@", "asset: %.*s", static_cast<int>(bytes.size()),
                    reinterpret_cast<const char*>(bytes.data()));
    }
}
}  // namespace @IDENT@
