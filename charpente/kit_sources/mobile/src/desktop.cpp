// charpente-mobile on the desktop (and anywhere without a mobile backend): stderr logging, files under ./ and ./assets.
// Handy for developing the app's logic on a PC before deploying to a device.
#include <charpente/mobile.hpp>

#include <cstdio>
#include <cstdlib>

namespace charpente {
namespace mobile {

namespace detail {
void write_log(LogLevel level, const char *tag, const char *line) {
    static const char *const names[] = {"D", "I", "W", "E"};
    std::fprintf(stderr, "%s/%s: %s\n", names[static_cast<int>(level)], tag, line);
}
}  // namespace detail

const char *platform_name() { return "desktop"; }

std::string data_dir() {
    const char *override_dir = std::getenv("CHARPENTE_MOBILE_DATA_DIR");
    return override_dir != nullptr ? override_dir : ".";
}

bool read_asset(const char *path, std::vector<unsigned char> &out) {
    for (const std::string &base : {std::string("assets/"), std::string("")}) {
        std::FILE *file = std::fopen((base + path).c_str(), "rb");
        if (file == nullptr) continue;
        out.clear();
        unsigned char chunk[4096];
        std::size_t got;
        while ((got = std::fread(chunk, 1, sizeof chunk, file)) > 0) out.insert(out.end(), chunk, chunk + got);
        std::fclose(file);
        return true;
    }
    return false;
}

}  // namespace mobile
}  // namespace charpente
