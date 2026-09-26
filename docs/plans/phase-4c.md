# Phase P4c — HarmonyOS / OpenHarmony

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Détection du SDK natif (env, DevEco, dossier Charpente) | `ohos.py`, `toolchains.py` | `tests/test_ohos.py` + SDK réel |
| Toolchain croisée alignée sur `ohos.toolchain.cmake`, dérive signalée par `doctor` | `ohos.py`, `commands/doctor.py` | idem |
| Installation du SDK public, empreinte SHA-256 | `toolchain_install.py` | dépôt factice + **téléchargement réel de 2,6 Go** |
| `Kind.MOBILE_APP` → `libentry.so`, STL, `--no-undefined`/`--gc-sections` | `flags.py`, `core/planner.py` | idem |
| Emballage par délégation à hvigor, déploiement hdc, squelette Node-API | `harmony.py`, `commands/_harmony.py`, `deploy.py` | exécuteur enregistreur (**non exécuté**) |

## Vérification réelle

SDK OpenHarmony 5.0.0.71 (API 12) téléchargé par `charpente toolchain install ohos` (résumable, SHA-256 vérifié). Une bibliothèque
partagée et un exécutable C++ (`std::string`, exceptions) construits pour arm64, arm et x64 ; en-têtes ELF lus : AArch64 / ARM / x86-64,
interpréteur musl. Aucune dérive entre les drapeaux de Charpente et le fichier du SDK. Bogue trouvé : mes drapeaux ARM initiaux
(`-mfloat-abi=softfp...`) étaient faux, corrigés d'après le fichier officiel.

## Critères et limites

Bibliothèques natives : ✔ construites avec le vrai SDK. **HAP, hvigor, hdc, appareil/émulateur : non vérifiés** (voir `docs/harmonyos.md`).
