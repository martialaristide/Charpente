# `charpente dev` and hot reload (experimental)

`charpente dev` watches your project, rebuilds what changed, and -- for plugin targets -- publishes every successful build so a **program that is already running** can load the new code without
restarting. It is a development tool: use it with Debug builds.

## Rebuild on change

```bash
charpente dev                         # build now, then rebuild whenever a source, header or the .charpente file changes
charpente dev --target game_logic     # only that target (and what it needs)
charpente dev --no-initial-build      # wait for the first change
charpente dev --poll 0.2 --cycles 3   # check every 0.2 s; stop after 3 rebuilds (useful in scripts and tests)
```

Watching is by **polling** (one `stat` per file every 0.5 s by default): no dependency, the same on every OS, cheap for thousands of files because the engine does the real work -- only what changed
is rebuilt, and unchanged results come from the cache. What is watched is what the build reads: every source of every target, headers in the include directories, and the workspace file.
The watcher starts *before* the first build, so a save made while the first build runs is not lost. A build that fails (a compile error, or a broken `.charpente` file) is reported and the loop keeps
watching; fix the file and it rebuilds. Ctrl+C stops it. Events: `dev.rebuilt` (which files changed, whether the build succeeded), `dev.plugin_published`.

## Hot reload of a plugin

Give the part you want to change while running its own `Kind.PLUGIN` target; the host program stays a normal executable.

```python
import sys
from charpente import *

with Workspace("game") as ws:
    ws.requires("charpente-hot")                 # the header, shipped inside Charpente: no download
    with Target("logic") as logic:
        logic.kind(Kind.PLUGIN)
        logic.standard("c++17")
        logic.sources(["src/logic.cpp"])
    with Target("game") as game:
        game.kind(Kind.EXECUTABLE)
        game.standard("c++17")
        game.sources(["src/main.cpp"])
        game.uses("charpente-hot")
        if sys.platform != "win32":
            game.links(["dl"])                   # dlopen
```

Run `charpente pkg install` once (it installs the header from Charpente itself, without a network). `src/logic.cpp` exports functions with C linkage:

```cpp
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
extern "C" EXPORT int update(int frame) { return frame * 2; }
```

The host, `src/main.cpp`:

```cpp
#include "charpente_hot.h"

int main() {
    ch_hot hot;
    ch_hot_open(&hot, "build/hot/logic.json");            // the manifest `charpente dev` maintains
    typedef int (*update_fn)(int);
    update_fn update = (update_fn)ch_hot_symbol(&hot, "update");
    for (int frame = 0;; frame++) {
        if (ch_hot_poll(&hot) == 1)                       // a newer generation was loaded: look the functions up again
            update = (update_fn)ch_hot_symbol(&hot, "update");
        if (update) update(frame);
        /* ... sleep, render, whatever your loop does ... */
    }
}
```

Run `charpente dev` in one terminal and the host in another. Edit `logic.cpp`, save: a few seconds later the running host is calling the new `update`. It is the same process the whole time.

### How it works

After each **successful** build of a plugin, `charpente dev` copies the shared library to `build/hot/<name>.<generation>.<ext>` (a fresh name every time, because Windows cannot overwrite a loaded DLL) and
atomically replaces `build/hot/<name>.json` with `{"generation": N, "path": "...", "source": "...", "published": ...}`. The three newest generations are kept, older ones are removed.
`--hot-dir DIR` moves the folder. The header's API is five functions: `ch_hot_open`, `ch_hot_poll` (1 = new code loaded, 0 = nothing new, -1 = the new one failed to load), `ch_hot_symbol`, `ch_hot_generation`, `ch_hot_close`.

### The rules that keep it safe (read these)

* **A failed build publishes nothing**: the host keeps running the last good code. Verified: a deliberately broken edit did not disturb the running host, and fixing it produced the next generation.
* The new library is loaded *before* the old one is released; a generation that fails to load is skipped, not retried in a loop, and the old one keeps running.
* **Pointers into the old library are invalid after a reload.** Resolve functions again when `ch_hot_poll` returns 1, and never keep a function pointer, a vtable or a string literal from the plugin across a reload.
* **The plugin's globals start fresh in every generation.** Keep state in the host (pass it in), or serialise it. Changing the layout of a struct the host and plugin share requires restarting the host.
* Not thread-safe: call `ch_hot_poll` from one thread, when no other thread is running plugin code.
* C++ exceptions and RTTI do not cross the plugin boundary reliably; use a C interface.

### What is verified, and what is not

Verified on Windows with MinGW-w64: a real host process kept running (same PID) while three generations were published and picked up, including a broken edit in the middle. **Not verified**: Linux (`dlopen`)
and macOS (`dlopen`) paths, MSVC, plugins that hold threads or global state, and hot reload of *Android* or *HarmonyOS* apps (not supported; use `charpente deploy`).
