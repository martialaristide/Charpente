#include <android/log.h>
#include <android_native_app_glue.h>

#include "xr_probe.hpp"

void android_main(android_app* app) {
    const XrProbeResult result = probe_openxr();
    __android_log_print(result.ok ? ANDROID_LOG_INFO : ANDROID_LOG_WARN, "@IDENT@", "%s", result.text.c_str());
    while (true) {
        int events;
        android_poll_source* source;
        while (ALooper_pollOnce(-1, nullptr, &events, reinterpret_cast<void**>(&source)) >= 0) {
            if (source) source->process(app, source);
            if (app->destroyRequested) return;
        }
    }
}
