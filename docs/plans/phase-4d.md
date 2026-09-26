# Phase P4d — Microcontrôleurs, iOS/visionOS, XR

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Firmware : réglages, drapeaux GCC/zig, `.bin`/`.hex`/`.uf2`, taille, flashage | `embedded.py`, `uf2.py`, `commands/firmware.py` | `tests/test_embedded.py` + **zig réel** |
| Plateformes Cortex-M0/M3/M4/M7/M33, AVR | `platforms.py`, `toolchains.py` | idem |
| iOS/visionOS : toolchain Xcode, bundle, signature, ipa, simulateur | `apple.py`, `commands/_apple.py` | `tests/test_apple_xr.py` (**sans Mac**) |
| XR Android : manifestes openxr/quest/pico | `android.py` | `tests/test_apple_xr.py` + **aapt2 réel** |

Vérification réelle : firmware Cortex-M4 (ELF ARM, vecteurs lus dans le `.bin`), M0, M7, AVR (ELF machine 83), image `.uf2` relue ; APK
XR (profil Quest) accepté par `aapt2`, signé et vérifié. Rien exécuté sur matériel ni sur casque ; rien exécuté sur un Mac.
Bogue trouvé : zig ne sait pas écrire de fichier map (`-Map` refusé) : plus demandé avec zig.

Non fait : ESP-IDF, Zephyr/west, moniteur série, RISC-V embarqué, Swift, `xcodebuild`, notarisation, OpenXR loader (kit P6).
