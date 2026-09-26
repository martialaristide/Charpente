#include "xr_probe.hpp"

#include <cstring>

#include <openxr/openxr.h>

#if defined(_WIN32)
#include <windows.h>
static void* open_library() { return reinterpret_cast<void*>(LoadLibraryA("openxr_loader.dll")); }
static void* find_symbol(void* lib, const char* name) { return reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(lib), name)); }
#else
#include <dlfcn.h>
static void* open_library() {
    for (const char* name : {"libopenxr_loader.so.1", "libopenxr_loader.so"}) {
        if (void* lib = dlopen(name, RTLD_NOW)) return lib;
    }
    return nullptr;
}
static void* find_symbol(void* lib, const char* name) { return dlsym(lib, name); }
#endif

XrProbeResult probe_openxr() {
    XrProbeResult result;
    void* lib = open_library();
    if (lib == nullptr) {
        result.text = "no OpenXR loader found (install a runtime: SteamVR, Meta Link, Monado; on a headset the loader ships with the system)";
        return result;
    }
    auto create = reinterpret_cast<PFN_xrCreateInstance>(find_symbol(lib, "xrCreateInstance"));
    auto destroy = reinterpret_cast<PFN_xrDestroyInstance>(find_symbol(lib, "xrDestroyInstance"));
    auto properties = reinterpret_cast<PFN_xrGetInstanceProperties>(find_symbol(lib, "xrGetInstanceProperties"));
    if (create == nullptr || destroy == nullptr || properties == nullptr) {
        result.text = "the OpenXR loader is missing entry points";
        return result;
    }

    XrInstanceCreateInfo info{XR_TYPE_INSTANCE_CREATE_INFO};
    std::strncpy(info.applicationInfo.applicationName, "@NAME@", XR_MAX_APPLICATION_NAME_SIZE - 1);
    info.applicationInfo.applicationVersion = 1;
    std::strncpy(info.applicationInfo.engineName, "charpente", XR_MAX_ENGINE_NAME_SIZE - 1);
    info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    XrInstance instance = XR_NULL_HANDLE;
    const XrResult created = create(&info, &instance);
    if (XR_FAILED(created)) {
        result.text = "an OpenXR loader is present but no runtime could start (xrCreateInstance returned " + std::to_string(created) +
                      "): is a headset connected and an active runtime selected?";
        return result;
    }
    XrInstanceProperties props{XR_TYPE_INSTANCE_PROPERTIES};
    properties(instance, &props);
    result.ok = true;
    result.text = std::string("OpenXR runtime: ") + props.runtimeName;
    destroy(instance);
    return result;
}
