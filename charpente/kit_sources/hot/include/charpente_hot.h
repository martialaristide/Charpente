/* charpente_hot.h -- the host side of Charpente's hot reload (experimental). C and C++, header only, no dependency.
 *
 * `charpente dev` rebuilds a Kind.PLUGIN target when its sources change and publishes each successful build as a new "generation": a copy of the
 * shared library under a unique name, plus a small manifest naming the newest one. A host program that keeps running loads the plugin through this header:
 *
 *     ch_hot hot;
 *     ch_hot_open(&hot, "build/hot/game.json");                       // loads the current generation, if there is one
 *     typedef int (*update_fn)(int);
 *     update_fn update = (update_fn)ch_hot_symbol(&hot, "update");
 *     for (;;) {
 *         if (ch_hot_poll(&hot) == 1)                                   // a new generation was loaded: resolve the functions again
 *             update = (update_fn)ch_hot_symbol(&hot, "update");
 *         if (update) update(frame++);
 *     }
 *
 * Rules that keep it safe: the new library is loaded *before* the old one is released, and a generation that fails to load is skipped (the old one keeps
 * running). Pointers into the old library are invalid after a reload -- resolve functions again after ch_hot_poll() returns 1, and keep the plugin's state
 * in the host (or serialise it), because the plugin's own globals start fresh in every generation.
 *
 * Not thread-safe: call it from one thread, at a point where no other thread is running plugin code. Debug builds only: this is a development tool.
 */
#ifndef CHARPENTE_HOT_H
#define CHARPENTE_HOT_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
typedef HMODULE ch_hot_handle;
#else
#include <dlfcn.h>
typedef void* ch_hot_handle;
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define CH_HOT_PATH 1024

typedef struct ch_hot {
    char manifest[CH_HOT_PATH];   /* the manifest file `charpente dev` writes */
    char loaded[CH_HOT_PATH];     /* the library currently loaded ("" when none) */
    long generation;              /* its generation number (0 when none) */
    ch_hot_handle handle;
} ch_hot;

/* Read `"generation"` and `"path"` from the manifest (a tiny JSON object). 0 on success. */
static int ch_hot__read(const char* manifest, long* generation, char* path, size_t capacity) {
    FILE* file = fopen(manifest, "rb");
    char text[4096];
    size_t size, i, out = 0;
    const char* at;
    if (!file) return -1;
    size = fread(text, 1, sizeof text - 1, file);
    fclose(file);
    text[size] = 0;
    at = strstr(text, "\"generation\"");
    if (!at || !(at = strchr(at, ':'))) return -1;
    *generation = strtol(at + 1, NULL, 10);
    at = strstr(text, "\"path\"");
    if (!at || !(at = strchr(at, ':')) || !(at = strchr(at, '"'))) return -1;
    for (i = 1; at[i] && at[i] != '"' && out + 1 < capacity; i++) {
        if (at[i] == '\\' && at[i + 1]) i++;              /* \\ and \" and \/ : keep the escaped character */
        path[out++] = at[i];
    }
    path[out] = 0;
    return at[i] == '"' ? 0 : -1;
}

static ch_hot_handle ch_hot__load(const char* path) {
#ifdef _WIN32
    return LoadLibraryA(path);
#else
    return dlopen(path, RTLD_NOW | RTLD_LOCAL);
#endif
}

static void ch_hot__unload(ch_hot_handle handle) {
    if (!handle) return;
#ifdef _WIN32
    FreeLibrary(handle);
#else
    dlclose(handle);
#endif
}

/* Start watching `manifest` and load its current generation. Returns 0 (also when nothing is published yet: poll again later), -1 on bad arguments. */
static int ch_hot_open(ch_hot* hot, const char* manifest) {
    if (!hot || !manifest || strlen(manifest) >= CH_HOT_PATH) return -1;
    memset(hot, 0, sizeof *hot);
    strcpy(hot->manifest, manifest);
    return 0;
}

/* Load a newer generation if one was published. 1: a new library is loaded (resolve symbols again); 0: nothing new; -1: the new one could not be loaded (the
 * previous one, if any, is still in use). */
static int ch_hot_poll(ch_hot* hot) {
    long generation = 0;
    char path[CH_HOT_PATH];
    ch_hot_handle fresh;
    if (!hot || ch_hot__read(hot->manifest, &generation, path, sizeof path) != 0) return 0;
    if (generation == hot->generation) return 0;
    fresh = ch_hot__load(path);
    if (!fresh) {
        hot->generation = generation;                       /* do not retry the same broken generation every poll */
        return -1;
    }
    ch_hot__unload(hot->handle);                            /* only now: the new one is safely loaded */
    hot->handle = fresh;
    hot->generation = generation;
    strcpy(hot->loaded, path);
    return 1;
}

/* The address of `name` in the loaded generation, or NULL. Valid until the next ch_hot_poll() returns 1. */
static void* ch_hot_symbol(ch_hot* hot, const char* name) {
    if (!hot || !hot->handle) return NULL;
#ifdef _WIN32
    return (void*)GetProcAddress(hot->handle, name);
#else
    return dlsym(hot->handle, name);
#endif
}

static long ch_hot_generation(const ch_hot* hot) { return hot ? hot->generation : 0; }

static void ch_hot_close(ch_hot* hot) {
    if (!hot) return;
    ch_hot__unload(hot->handle);
    hot->handle = 0;
    hot->loaded[0] = 0;
    hot->generation = 0;
}

#ifdef __cplusplus
}
#endif

#endif /* CHARPENTE_HOT_H */
