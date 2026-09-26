// Android entry point (NativeActivity + the NDK's native_app_glue).
#include <android_native_app_glue.h>
#include <charpente/mobile.hpp>

void app_install_handler();
void app_start();

static void on_cmd(android_app*, int32_t cmd) { charpente::mobile::android_command(cmd); }

void android_main(android_app* app) {
    app_install_handler();                                   // before attach, so Event::Create is delivered
    charpente::mobile::android_attach(app->activity);
    app_start();
    app->onAppCmd = on_cmd;
    while (true) {
        int events;
        android_poll_source* source;
        while (ALooper_pollOnce(-1, nullptr, &events, reinterpret_cast<void**>(&source)) >= 0) {
            if (source) source->process(app, source);
            if (app->destroyRequested) return;
        }
    }
}
