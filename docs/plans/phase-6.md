# Phase P6 — Kits et modèles

| Élément | Fichiers | Vérifié par |
|---|---|---|
| 10 → 30 recettes (simdjson, stb, miniaudio, cgltf, volk, vma, meshoptimizer, asio, websocketpp, tracy, imgui, glfw, freertos, printf, cmsis, openxr-headers, pybind11, backends ImGui, tinylibc, charpente-mobile) | `pkg/recipes/` | `tests/test_kits.py` + **compilation réelle** |
| Kits (core, app, graphics, xr, game, net, embedded, mobile, android, ohos), `ws.kit`, `charpente kit` | `pkg/kits.py`, `pkg/kits/`, `commands/kit.py` | idem |
| Sources locales `charpente://`, condensés synchronisés | `pkg/localsrc.py`, `tools/sync_kit_digests.py` | idem |
| `ws.package_settings`, `output_prefix/extension`, `platform_settings(name=)` | `dsl/`, `pkg/materialize.py`, `flags.py` | idem |
| 16 modèles, `charpente init --template/--list` | `templates.py`, `templates_data/`, `commands/init.py` | `tests/test_templates.py` + **exécutions réelles** |
| Correction d'empaquetage (`package-data`) | `pyproject.toml` | test statique + **wheel réel** (310 fichiers) |

## Vérification réelle (Windows 10, MinGW, zig, NDK, SDK OpenHarmony, emsdk, émulateur API 30)

- Un programme utilisant fmt, spdlog, json, EnTT, glm, simdjson, meshoptimizer, ImGui, asio, websocketpp, cgltf, stb, Tracy, OpenXR, miniaudio, volk, VMA, CLI11 (via
  les kits) : compilé, lié, exécuté.
- Fenêtre OpenGL réelle avec ImGui/GLFW (modèle `app-gui`), jeu (`jeu-2d`), énumération Vulkan (GPU Intel listé), extension Python importée.
- Application Android construite depuis `app-android` et `app-mobile`, APK signé, **exécutée sur l'émulateur** : `create/start/resume/window-ready`, dossier de données, ressource lue
  dans l'APK. HarmonyOS : bibliothèques natives des deux modèles construites et liées avec le vrai SDK. Firmware STM32, RPi (ELF AArch64), WASI (Node), Emscripten (Node),
  module Charpente (conformité).
- FreeRTOS + printf + tinylibc lié pour Cortex-M3 avec zig.

## Écarts et limites

Voir `docs/kits.md` et `docs/templates.md` : non vérifiés — iOS, ArkTS/hvigor, ESP-IDF, casque OpenXR, X11/Cocoa de GLFW, ports Cortex-M4F/M7 de FreeRTOS (le clang de zig refuse leur assembleur).
