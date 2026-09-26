// The shared part of the app: identical on every platform. Platform entry points call app_start().
#include <charpente/mobile.hpp>

namespace mobile = charpente::mobile;

static void on_event(mobile::Event event, void*) {
    mobile::log(mobile::LogLevel::Info, "@IDENT@", "lifecycle: %s", mobile::event_name(event));
}

void app_start() {
    mobile::log(mobile::LogLevel::Info, "@IDENT@", "running on %s; data dir '%s'", mobile::platform_name(),
                mobile::data_dir().c_str());
    std::vector<unsigned char> bytes;
    if (mobile::read_asset("hello.txt", bytes)) {
        mobile::log(mobile::LogLevel::Info, "@IDENT@", "asset: %.*s", static_cast<int>(bytes.size()),
                    reinterpret_cast<const char*>(bytes.data()));
    }
}

void app_install_handler() { mobile::set_handler(on_event, nullptr); }
