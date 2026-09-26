# Phase P4b — Android

## Objectifs (du cahier des charges)

NDK, construction native, APK signé, `adb`/déploiement, Gradle interop (si raisonnable).

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Découverte du SDK/NDK (env, Android Studio, racine Charpente) | `android.py`, `toolchains.py` | `tests/test_android.py` + machine réelle |
| NDK comme toolchain croisée (`--target=...<api>`) | `android.py`, `cross.py` | idem |
| `Kind.MOBILE_APP`, `native_app_glue`, `stl`, `-fPIC` | `flags.py`, `core/planner.py`, `dsl` | idem + build réel |
| Manifeste, validation des réglages (CH8006) | `android.py` | idem |
| APK : link, bibliothèques stockées, zipalign, signature, vérification | `android.py`, `commands/_android.py`, `commands/package.py` | idem + APK réel |
| Clés : débogage (SDK ou `keytool`), publication (mot de passe par l'environnement) | `android.py` | idem |
| `charpente deploy` (adb install + lancement) | `commands/deploy.py`, `android.py` | idem + émulateur réel |
| Installation des composants du SDK, licence obligatoire (CH8010), SHA-1, XML sûr | `toolchain_install.py`, `core/download.py`, `pkg/fetch.py` | dépôt factice local |
| Codes CH8006–CH8010 (FR+EN) | `i18n/` | catalogue testé |

## Vérification réelle

Windows 10, NDK 28.2.13676358, build-tools 36.1.0, JDK 21, émulateur x86_64 API 30 (lancé sans fenêtre, en lecture seule).
Une application NativeActivity écrite en C++ : construite par Charpente pour `android-arm64` et `android-x64`,
empaquetée en un APK à deux ABI, `zipalign -c -P 16` et `apksigner verify` réussis, `aapt2 dump badging` conforme,
puis `charpente deploy --platform android-x64` : installée, démarrée ; les lignes `android_main started` et
`hello from charpente, window ready` lues dans `logcat`. Avec `stl="shared"` aussi.

## Bogues réels trouvés par cette vérification (corrigés)

- Plantage au chargement (`libc++_shared.so` introuvable) : libc++ statique par défaut.
- Objets de bibliothèque partagée sans `-fPIC`.
- Fichier C de `native_app_glue` compilé en C++ : compilation par fichier avec son propre langage.

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Une appli native se construit, se signe et se lance sur un appareil/émulateur | ✔ émulateur x86_64 ; **arm64 non exécuté** |
| Aucune licence acceptée à la place de l'utilisateur | ✔ `CH8010` |
| Aucune commande par shell, mots de passe jamais en argument | ✔ |

## Écarts et limites

Pas de Java/Kotlin/Gradle/AAR/AAB (voir `docs/android.md`), pas de shaders, pas de téléchargement réel des composants
(fait sur dépôt factice), arm64 non exécuté. Un test du dépôt (`test_editing_a_header_rebuilds...`) a échoué une seule
fois en suite complète pendant qu'un émulateur tournait, sans se reproduire ni isolément (8 essais) ni en relançant la
suite : signalé, à surveiller.
