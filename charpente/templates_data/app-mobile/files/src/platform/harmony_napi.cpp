// HarmonyOS entry point: a Node-API module the ArkTS UI imports as `libentry.so`.
#include <charpente/mobile.hpp>
#include <napi/native_api.h>
#include <rawfile/raw_file_manager.h>
#include "../engine/engine.hpp"

// entry.start(resourceManager, filesDir): hands the platform objects to the mobile layer and starts the engine.
static napi_value Start(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value args[2] = {nullptr, nullptr};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    char dir[512] = "";
    size_t length = 0;
    if (argc > 1) napi_get_value_string_utf8(env, args[1], dir, sizeof dir, &length);
    NativeResourceManager* resources = argc > 0 ? OH_ResourceManager_InitNativeResourceManager(env, args[0]) : nullptr;
    charpente::mobile::harmony_attach(resources, dir);
    @IDENT@::start();
    return nullptr;
}

EXTERN_C_START
static napi_value Init(napi_env env, napi_value exports) {
    napi_property_descriptor desc[] = {{"start", nullptr, Start, nullptr, nullptr, nullptr, napi_default, nullptr}};
    napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
    return exports;
}
EXTERN_C_END

static napi_module entryModule = {1, 0, nullptr, Init, "entry", nullptr, {0}};
extern "C" __attribute__((constructor)) void RegisterEntryModule(void) { napi_module_register(&entryModule); }
