# ADR 0013 — HarmonyOS : compiler nous-mêmes, déléguer l'emballage

- **Statut** : accepté (P4c)

## Décisions

- **Pilotage direct de clang du SDK natif** (sysroot musl, triplets `*-linux-ohos`), sans CMake, avec les réglages du fichier
  officiel `ohos.toolchain.cmake` (lu sur le SDK réel, pas deviné : ma première version comportait de mauvais drapeaux ARM).
  `charpente doctor` compare ces hypothèses au fichier du SDK installé (`ohos.alignment`) pour détecter une dérive quand le SDK change.
- **Délégation à hvigor** pour l'application (règle générale du cahier des charges : quand un écosystème impose son outil, on compile
  le C/C++ puis on lui délègue l'emballage). Charpente place les `.so` dans `<projet>/<module>/libs/<abi>/`, lance `hvigorw assembleHap`
  et rapporte le résultat ; il ne réécrit ni ArkCompiler ni la signature HAP.
- **Installation du SDK OpenHarmony public** (Apache-2.0, sans licence à accepter) : archive complète téléchargée avec reprise, SHA-256
  publié à côté vérifié, seule la composante `native` extraite. Les outils HarmonyOS propriétaires ne sont jamais téléchargés.
- **`Kind.MOBILE_APP` = bibliothèque native du HAP** (`libentry.so`), cohérent avec Android.
- **Non vérifié ici** (pas de hvigor/hdc/appareil) : dit clairement dans la documentation et les tests (exécuteur enregistreur).
