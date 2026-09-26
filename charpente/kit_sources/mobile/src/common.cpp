// charpente-mobile: the platform-independent part (event dispatch, names, formatting).
#include <charpente/mobile.hpp>

#include <cstdarg>
#include <cstdio>

namespace charpente {
namespace mobile {

namespace {
EventHandler g_handler = nullptr;
void *g_user = nullptr;
}  // namespace

void set_handler(EventHandler handler, void *user) {
    g_handler = handler;
    g_user = user;
}

void dispatch(Event event) {
    if (g_handler != nullptr) g_handler(event, g_user);
}

const char *event_name(Event event) {
    switch (event) {
        case Event::Create: return "create";
        case Event::Start: return "start";
        case Event::Resume: return "resume";
        case Event::Pause: return "pause";
        case Event::Stop: return "stop";
        case Event::Destroy: return "destroy";
        case Event::LowMemory: return "low-memory";
        case Event::WindowReady: return "window-ready";
        case Event::WindowLost: return "window-lost";
    }
    return "unknown";
}

namespace detail {
// The platform files implement `write_log`; this formats once so each backend only forwards a finished line.
void write_log(LogLevel level, const char *tag, const char *line);
void write_log_formatted(LogLevel level, const char *tag, const char *format, va_list args) {
    char buffer[1024];
    std::vsnprintf(buffer, sizeof buffer, format, args);
    write_log(level, tag, buffer);
}
}  // namespace detail

void log(LogLevel level, const char *tag, const char *format, ...) {
    va_list args;
    va_start(args, format);
    detail::write_log_formatted(level, tag, format, args);
    va_end(args);
}

}  // namespace mobile
}  // namespace charpente
