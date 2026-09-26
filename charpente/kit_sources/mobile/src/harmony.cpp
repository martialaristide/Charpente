// charpente-mobile on HarmonyOS / OpenHarmony: hilog, the app's files directory, rawfile resources.
#include <charpente/mobile.hpp>

#include <hilog/log.h>
#include <rawfile/raw_file.h>
#include <rawfile/raw_file_manager.h>

namespace charpente {
namespace mobile {

namespace {
NativeResourceManager *g_resources = nullptr;
std::string g_files_dir;
constexpr unsigned int kLogDomain = 0x3200;   // any value in 0x0..0xFFFF; apps normally choose their own
}  // namespace

namespace detail {
void write_log(LogLevel level, const char *tag, const char *line) {
    static const ::LogLevel levels[] = {LOG_DEBUG, LOG_INFO, LOG_WARN, LOG_ERROR};   // hilog's enum, not ours
    OH_LOG_Print(LOG_APP, levels[static_cast<int>(level)], kLogDomain, tag, "%{public}s", line);
}
}  // namespace detail

const char *platform_name() { return "harmonyos"; }

void harmony_attach(void *native_resource_manager, const char *files_dir) {
    g_resources = static_cast<NativeResourceManager *>(native_resource_manager);
    g_files_dir = files_dir != nullptr ? files_dir : "";
}

std::string data_dir() { return g_files_dir; }

bool read_asset(const char *path, std::vector<unsigned char> &out) {
    if (g_resources == nullptr) return false;
    RawFile *file = OH_ResourceManager_OpenRawFile(g_resources, path);
    if (file == nullptr) return false;
    const long size = OH_ResourceManager_GetRawFileSize(file);
    out.resize(static_cast<std::size_t>(size));
    const int got = OH_ResourceManager_ReadRawFile(file, out.data(), static_cast<std::size_t>(size));
    OH_ResourceManager_CloseRawFile(file);
    if (got != size) {
        out.clear();
        return false;
    }
    return true;
}

}  // namespace mobile
}  // namespace charpente
