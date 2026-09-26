#include <android_native_app_glue.h>
#include <charpente/mobile.hpp>
#include "../engine/engine.hpp"

static void on_cmd(android_app*, int32_t cmd) { charpente::mobile::android_command(cmd); }

void android_main(android_app* app) {
    @IDENT@::install();                                      // handler first, so Event::Create is delivered ...
    charpente::mobile::android_attach(app->activity);        // ... when the activity is attached
    @IDENT@::start();                                        // now assets and the files directory are available
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
