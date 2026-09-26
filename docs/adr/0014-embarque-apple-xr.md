# ADR 0014 — Microcontrôleurs, Apple, XR

- **Statut** : accepté (P4d)

## Microcontrôleurs

- `Kind.FIRMWARE` : compilation freestanding, édition de liens avec **le script de l'utilisateur**, images `.bin`/`.hex`/`.uf2` dérivées par
  des actions du moteur (donc mises en cache), taille flash/RAM lue dans l'ELF et les régions `MEMORY` du script.
- **zig comme compilateur embarqué de secours** : un seul binaire cible Cortex-M (`thumb-freestanding`) et AVR, vérifié pour de vrai ;
  `arm-none-eabi-gcc` et `avr-gcc` sont pris en charge mais seulement testés unitairement (non installés ici).
- **UF2 en Python pur**, exécuté comme action (`python -m charpente.uf2`) : format simple, testable, mis en cache.
- **Flashage = construction de commande** (openocd, pyocd, probe-rs, avrdude, esptool, dfu-util) ; aucun matériel ici. Pas d'ESP-IDF ni de RTOS.

## Apple

- Écrit et testé **sans Mac** : commandes `xcrun`/`clang -target ... -isysroot`, `codesign`, `simctl`, `devicectl`, Info.plist (`plistlib`),
  disposition du bundle et `.ipa`. Niveaux 2/3 et note explicite dans `charpente platforms`. Le SDK Apple n'est jamais téléchargé.

## XR

- Casques Android (Quest, Pico, OpenXR) = profils du manifeste Android (`xr=`), vérifiés par `aapt2` et `apksigner` mais jamais lancés sur un
  casque ; visionOS via Apple (Tier 3). Le chargeur OpenXR et les fonctions optionnelles relèvent du kit XR (P6).
