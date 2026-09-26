// charpente-mobile on Android (NativeActivity): logcat, the app's files directory, assets from the APK.
#include <charpente/mobile.hpp>

#include <android/asset_manager.h>
#include <android/log.h>
#include <android/native_activity.h>

namespace charpente {
namespace mobile {

namespace {
ANativeActivity *g_activity = nullptr;
std::string g_data_dir;
}  // namespace

namespace detail {
void write_log(LogLevel level, const char *tag, const char *line) {
    static const int priorities[] = {ANDROID_LOG_DEBUG, ANDROID_LOG_INFO, ANDROID_LOG_WARN, ANDROID_LOG_ERROR};
    __android_log_write(priorities[static_cast<int>(level)], tag, line);
}
}  // namespace detail

const char *platform_name() { return "android"; }

void android_attach(void *native_activity) {
    g_activity = static_cast<ANativeActivity *>(native_activity);
    g_data_dir = (g_activity != nullptr && g_activity->internalDataPath != nullptr) ? g_activity->internalDataPath : "";
    dispatch(Event::Create);
}

// The values are the NDK's APP_CMD_* enumeration (android_native_app_glue.h), listed by number so this file needs no
// glue include; the Charpente template asserts them against the real header at compile time.
bool android_command(int32_t command) {
    switch (command) {
        case 1: dispatch(Event::WindowReady); return true;    // APP_CMD_INIT_WINDOW
        case 2: dispatch(Event::WindowLost); return true;     // APP_CMD_TERM_WINDOW
        case 9: dispatch(Event::LowMemory); return true;      // APP_CMD_LOW_MEMORY
        case 10: dispatch(Event::Start); return true;         // APP_CMD_START
        case 11: dispatch(Event::Resume); return true;        // APP_CMD_RESUME
        case 13: dispatch(Event::Pause); return true;         // APP_CMD_PAUSE
        case 14: dispatch(Event::Stop); return true;          // APP_CMD_STOP
        case 15: dispatch(Event::Destroy); return true;       // APP_CMD_DESTROY
        default: return false;
    }
}

std::string data_dir() { return g_data_dir; }

bool read_asset(const char *path, std::vector<unsigned char> &out) {
    if (g_activity == nullptr || g_activity->assetManager == nullptr) return false;
    AAsset *asset = AAssetManager_open(g_activity->assetManager, path, AASSET_MODE_BUFFER);
    if (asset == nullptr) return false;
    const off_t size = AAsset_getLength(asset);
    out.resize(static_cast<std::size_t>(size));
    const int got = AAsset_read(asset, out.data(), static_cast<std::size_t>(size));
    AAsset_close(asset);
    if (got != size) {
        out.clear();
        return false;
    }
    return true;
}

}  // namespace mobile
}  // namespace charpente
