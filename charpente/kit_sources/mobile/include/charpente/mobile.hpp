// charpente-mobile: one small C++ API for the parts of an app that differ between Android, HarmonyOS, iOS and the desktop
// (lifecycle, logging, files, assets). MIT. Part of the Charpente kits (kit-mobile, kit-android, kit-ohos).
//
//   #include <charpente/mobile.hpp>
//   namespace mobile = charpente::mobile;
//
//   mobile::set_handler([](mobile::Event e, void*) { if (e == mobile::Event::Pause) save(); }, nullptr);
//   mobile::log(mobile::LogLevel::Info, "game", "starting on %s", mobile::platform_name());
//   std::vector<unsigned char> bytes;
//   if (mobile::read_asset("level1.bin", bytes)) { ... }
//
// Each platform tells the library about its host once, with the *_attach call below; everything else is the same code.
#ifndef CHARPENTE_MOBILE_HPP
#define CHARPENTE_MOBILE_HPP

#include <cstdint>
#include <string>
#include <vector>

namespace charpente {
namespace mobile {

enum class Event {
    Create, Start, Resume, Pause, Stop, Destroy,   // the app's lifecycle
    LowMemory,                                     // release caches
    WindowReady, WindowLost,                       // a surface to draw on exists / is gone
};

enum class LogLevel { Debug, Info, Warn, Error };

using EventHandler = void (*)(Event event, void *user);

// Lifecycle ---------------------------------------------------------------------------------------------------------
// One handler for the app. Events raised before a handler is set are dropped.
void set_handler(EventHandler handler, void *user);
// Called by the platform glue (below); apps may also call it to simulate an event in tests.
void dispatch(Event event);
const char *event_name(Event event);

// Logging: logcat on Android, hilog on HarmonyOS, NSLog on iOS, stderr on the desktop. printf-style.
void log(LogLevel level, const char *tag, const char *format, ...)
#if defined(__GNUC__) || defined(__clang__)
    __attribute__((format(printf, 3, 4)))
#endif
    ;

// Files -------------------------------------------------------------------------------------------------------------
const char *platform_name();                          // "android", "harmonyos", "ios", "desktop"
std::string data_dir();                               // a writable directory private to the app ("" if unknown yet)
// Reads a file packaged with the app (Android assets, HarmonyOS rawfile, the iOS bundle, ./assets on the desktop).
bool read_asset(const char *path, std::vector<unsigned char> &out);

// Platform glue -----------------------------------------------------------------------------------------------------
#if defined(__ANDROID__)
// Call once from android_main() with `app->activity` (an ANativeActivity*, passed as void* so this header needs no
// Android include). Gives the library the asset manager and the files directory, and raises Event::Create.
void android_attach(void *native_activity);
// Call from your android_app::onAppCmd with the command; returns true when it was a lifecycle command.
bool android_command(int32_t command);
#endif

#if defined(__OHOS__)
// Call from your Node-API module init with the NativeResourceManager and, when known, the app's files directory.
void harmony_attach(void *native_resource_manager, const char *files_dir);
#endif

#if defined(__APPLE__)
// iOS/visionOS: call from your UIApplicationDelegate methods; `notify` maps them to Events.
void ios_notify(Event event);
#endif

}  // namespace mobile
}  // namespace charpente

#endif
