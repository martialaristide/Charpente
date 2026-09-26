# Phase P9 — Interopérabilité, reproductibilité, boucle de développement, finitions

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Budgets (`ws.budget`, `t.budget`, `--no-budget`, événements `budget.*`) | `units.py`, `budgets.py`, `commands/build.py`, `dsl/api.py` | `tests/test_budgets.py` (42) — builds réels |
| Builds reproductibles, `verify-reproducible` | `variants.reproducible`, `repro.py`, `commands/verify.py` | `tests/test_reproducible.py` (14) — deux dossiers, octets identiques (MinGW) |
| Clés de cache relocatables (`@ROOT@`, identité d'outil portable) | `core/engine`, `core/toolid.py`, `core/cache.py` | `tests/test_shared_cache.py` |
| Cache partagé HTTP (serveur, client, signatures HMAC, jeton, échec ouvert) | `core/cache_server.py`, `core/remote.py`, `commands/cache.py` | `tests/test_shared_cache.py` (24) — deux dossiers, sorties identiques |
| `import cmake` (File API) | `importers/cmake.py`, `commands/imports.py` | `tests/test_import_cmake.py` (14) — CMake 3.22.1 réel : import, build, exécution |
| `generate` : compile-commands, ninja, cmake, vs | `generators/{ninja,cmake,vs}.py`, `commands/generate.py` | `tests/test_generate.py` (12) — Ninja 1.10.2 et CMake 3.22.1 réels ; **Visual Studio non ouvert** ; **Xcode non fait** |
| Rechargement à chaud (`charpente dev`, `charpente_hot.h`, recette `charpente-hot`) | `dev.py`, `commands/dev.py`, `kit_sources/hot/`, `pkg/recipes/charpente-hot-1.0.0.toml` | `tests/test_dev_hot.py` (8) — hôte réel qui charge 3 générations sans redémarrer |
| `charpente docs` (extracteur, Mermaid, SVG, Doxygen) | `docsgen.py`, `commands/docs.py` | `tests/test_docs.py` (12) |
| Ressources : mémoire, disque, batterie, chaleur, mode éco, reprise | `resources.py`, `builder.py`, `commands/_session.py` | `tests/test_resources.py` (10) — dont un build tué puis repris |
| Déploiement multi-appareils, journaux fusionnés | `multideploy.py`, `commands/deploy.py` | `tests/test_multideploy.py` (14) — **vrai APK, faux `adb`** |
| `charpente setup`, préférences (`settings.py`), `charpente self uninstall` | `onboarding.py`, `settings.py`, `selfmanage.py`, `commands/{setup,selfcmd}.py` | `tests/test_setup_self.py` (15) — dont un lien de type jonction Windows |
| Paquet PyPI prêt (wheel + sdist, `twine check`, installation dans un venv propre) | `pyproject.toml` | construit et installé ; **rien n'a été publié** |
| Codes CH1026, CH8024–CH8028 | `i18n/`, `docs/errors.md` | catalogue |
| Événements `budget.*`, `resource.*`, `dev.*`, `deploy.device_*`/`deploy.log` | `events/types.py`, `docs/events/` | schémas régénérés et testés |
| ADR 0019, `docs/{shared-cache,reproducible-and-budgets,import-and-generate,hot-reload,api-docs,resources,multi-device,setup-and-uninstall,stability,guide}.md` | | |

## Vérification réelle (Windows 10, MinGW-w64, CMake 3.22.1, Ninja 1.10.2, NDK, émulateur Android x86_64)

Deux dossiers différents produisent des exécutables identiques octet pour octet ; un second dossier obtient toutes ses actions du cache partagé ; un projet CMake est importé puis construit et exécuté (`answer=42`) ;
un `build.ninja` généré est construit par Ninja et se reconstruit sur un changement d'en-tête ; un `CMakeLists.txt` généré est configuré, construit et testé par CMake ; un hôte réel qui tourne charge trois générations d'un plugin
(même PID), dont une modification volontairement cassée entre deux ; un build tué en plein milieu reprend sans refaire les compilations terminées ; un vrai APK multi-ABI est construit pour `--device all`.

## Bugs trouvés par ces vérifications (et corrigés)

Modification faite pendant le premier build de `charpente dev` perdue (surveillance créée trop tard) ; sortie de `dev` non vidée quand elle est redirigée ; comptage des actions exécutées faux dans les tests de cache (adressage par contenu : un commentaire d'en-tête ne recompile que ce qui change réellement) ;
`verify-reproducible` sans chemin de sortie dans `target.finished` (déduit des événements d'actions) ; un test du moteur dépendait de la mémoire libre de la machine (les mesures sont maintenant figées par `conftest.py`, sauf pour `test_resources.py`) ;
un budget de taille sur une cible sans fichier de sortie passait sans rien dire (il est maintenant signalé `[budget skipped]`).

## Écarts et limites

REAPI et exécution hybride **non faits** (voir ADR 0019) ; projet Xcode **non fait** ; Visual Studio **jamais ouvert** ; appareils multiples **simulés** (un vrai APK, un faux `adb`) ; pas de TLS dans le serveur de cache ;
sondes de batterie/mémoire/chaleur non exécutées hors Windows ; rechargement à chaud vérifié sur Windows seulement ; aucune intégration continue, donc la version reste 0.x ; le paquet PyPI n'est **pas publié**.
