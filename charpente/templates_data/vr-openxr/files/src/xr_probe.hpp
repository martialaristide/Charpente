#pragma once
// Loads the OpenXR loader at run time (so the program builds and starts everywhere) and tries to create an instance.
// Returns a human-readable description of what happened; `ok` says whether an instance could be created.
#include <string>

struct XrProbeResult {
    bool ok = false;
    std::string text;
};

XrProbeResult probe_openxr();
