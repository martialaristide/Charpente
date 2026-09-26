# Phase P4a — Plateformes desktop/web et compilation croisée

## Objectifs (du cahier des charges)

Modèle de plateformes avec niveaux, compilation croisée (zig), toolchains installables, Linux/macOS/Windows
x64+arm64, WASI et Emscripten, FreeBSD, langages asm/ObjC, `charpente doctor`.

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Table de plateformes, niveaux, avertissements Tier 3 | `platforms.py`, `commands/platforms.py` | `tests/test_cross.py` |
| Sélection/spécialisation de toolchain, `--platform`/`--toolchain` | `cross.py`, `commands/_common.py`, `_session.py` | idem + builds réels |
| Fournisseur zig + `toolchain install/remove` (SHA-256) | `toolchains.py`, `toolchain_install.py`, `commands/toolchain.py` | idem + installation réelle de zig 0.16.0 |
| Fournisseur Emscripten + `install emsdk` | idem | idem + emsdk 6.0.10 réel |
| Répertoires/identifiants par plateforme, env de toolchain | `core/planner.py`, `builder.py` | idem |
| Noms de sortie par OS, sorties annexes (`.wasm`) | `flags.py` | idem |
| Exécution de binaires étrangers | `runners.py` | idem + exécution WASI réelle |
| Assembleur, Objective-C | `flags.py` | asm réel (zig et MinGW) ; ObjC : tests unitaires |
| `charpente doctor` | `commands/doctor.py` | idem |
| Codes CH8001–CH8005 (FR+EN) | `i18n/` | catalogue testé |

## Vérification réelle

Machine : Windows 10 x64, MinGW GCC 16, zig 0.16.0 (installé par `charpente toolchain install zig`, 2 min),
emsdk 6.0.10. Un projet (bibliothèque statique + exécutable) construit pour **linux-x64, linux-arm64,
linux-riscv64, windows-arm64, macos-x64, macos-arm64, freebsd-x64, wasm32-wasi, wasm32-emscripten** et
nativement. Les en-têtes des binaires ont été lus : ELF (machine 62/183/243), PE 0xAA64, Mach-O (cpu x64/arm64),
wasm. Le programme WASI et le programme Emscripten **ont été exécutés** (sous Node) et affichent la bonne plateforme ;
`charpente run --platform linux-arm64` refuse proprement (`CH8004`) ; un second build est instantané ; la
suppression de `app.js` et `app.wasm` suivie d'un build restaure les deux depuis le cache.

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Un même `.charpente` se construit pour au moins 3 plateformes depuis une machine | ✔ 9 plateformes depuis Windows |
| Rien ne change pour les builds natifs | ✔ tests d'origine inchangés (sauf l'ordre de détection, qui gagne zig/emscripten en dernier) |
| Pas de repli silencieux | ✔ CH8002/CH8003/CH8004 |
| Binaires croisés exécutés | ✔ WASI et Emscripten seulement ; les autres : format vérifié, **non exécutés** |

## Écarts et limites

Voir `docs/platforms.md` (section « Limites ») et l'ADR 0011 : pas de modules C++20, pas de shaders, pas
d'ABI musl sélectionnable, pas de MSVC croisé, pas d'exécution sous QEMU/Wine. Les niveaux « Tier 1 » de
Linux/macOS supposent l'exécution en CI sur de vrais runners, qui n'a pas eu lieu ici.
