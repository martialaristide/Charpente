# Project templates

```
charpente init --list
charpente init MyApp --template app-android [--dir PATH] [--install]
```

A template is a folder in `charpente/templates_data/` (or `.charpente/templates/` in your project, or a module's `template` extension): a `template.toml`
and a `files/` tree. `@NAME@`, `@IDENT@` (a C identifier), `@TITLE@` and `@PACKAGE@` (`dev.example.<ident>`: **change it**) are replaced in file contents
and names. Hidden files are stored as `dot_gitignore` and written as `.gitignore` (packaging tools skip dot-files). A template refuses to overwrite files.
`charpente init NAME` without `--template` is unchanged from v0.1.0.

| Template | What you get | Verified here |
|---|---|---|
| `console` | a program with a tested core library | built, tested, run |
| `bibliotheque` | a library with a public header, example, tests | built, tested, run |
| `app-gui` | Dear ImGui on GLFW/OpenGL 3, `--frames N` for smoke tests | real window rendered frames (Windows) |
| `jeu-2d` | breakout: GLFW + OpenGL, rules unit-tested separately | built, tested, real window run (Windows) |
| `jeu-3d-vulkan` | Vulkan bootstrap (volk, GLFW, instance, GPU list); **no rendering** | run: listed the GPU |
| `vr-openxr` | OpenXR runtime probe (desktop) + Quest/Pico APK profile | desktop run reports "no loader"; Quest APK built, manifest accepted, signed. **No headset** |
| `app-android` | NativeActivity app on the mobile kit, signed APK | **run on an emulator** (lifecycle, logcat, asset) |
| `app-harmonyos` | ArkTS/hvigor project + C++ Node-API library | native library builds/links with the real SDK. **ArkTS project never built** |
| `app-mobile` | one C++ engine, entry points for Android, HarmonyOS, iOS, desktop | desktop tests+run; Android on an emulator; HarmonyOS library links. **iOS not compiled** |
| `web-wasm` | Emscripten program + HTML page | built and run under Node; page not opened in a browser |
| `wasi-plugin` | a WASI command | built with zig, run under Node |
| `plugin-python` | a pybind11 extension (`.pyd`/`.so`) | built and imported from Python (Windows) |
| `firmware-stm32` | Cortex-M4 startup, linker script, LED blink | built (ELF/bin/hex); **never flashed** |
| `firmware-esp32` | an ESP-IDF blink project | **nothing verified**; Charpente does not drive `idf.py` |
| `linux-embarque-rpi` | a 64-bit ARM Linux program | cross-built with zig (ELF AArch64); never run on a board |
| `module-charpente` | a Charpente module with its manifest | passes `charpente module check` |

Each template's `template.toml` repeats what was verified and what was not; `charpente init --list` marks templates that verify nothing.

Not provided (yet): `ar-mobile` (ARCore/AR Engine/ARKit need Gradle, Java or Xcode integration), `jeu-harmonyos` (XComponent + Vulkan/GLES rendering),
`firmware-esp32` that builds (ESP-IDF delegation), a Kotlin/Java UI for `app-android`.

## Writing a template

```
mytemplate/
  template.toml          # [template] name, description, kits, platforms, verified, unverified, install, next
  files/
    @NAME@.charpente
    src/main.cpp
    dot_gitignore
```

Register it in a module with `registry.add_template(obj)` (an object with `name`, `description`, `generate(destination, project_name)`).
