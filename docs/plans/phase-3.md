# Phase P3 — DSL v2 et paquets

## Objectifs (du cahier des charges)

`.uses`, propagation public/privé, options, `Rule`, `charpente.toml`, lint du DSL, Charpente Pkg
(recettes, lockfile, cache binaire, vendor, miroir, audit, SBOM), `migrate`.

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| `uses`/`uses_public`, propagation `public_*`/`interface_*`, liaison transitive | `dsl/api.py`, `dsl/resolve.py`, `core/planner.py` | `tests/test_dsl_v2.py` (sans compilateur) + build réel |
| Nouveaux `Kind` (HEADER_ONLY, PLUGIN construits ; les autres refusés en `CH3007`) | `dsl/model.py`, `core/planner.py`, `flags.py` | `tests/test_dsl_v2.py` |
| Conditions `on_config`/`on_platform`/`on_toolchain`/`when`, paramètres de plateforme | `dsl/api.py`, `dsl/resolve.py` | idem |
| Options typées, `--opt`, `charpente options` | `dsl/api.py`, `commands/` | `tests/test_dsl_v2.py`, `tests/test_lint_migrate.py` |
| `Rule` (actions utilisateur, cache) | `dsl/api.py`, `core/planner.py` | `tests/test_dsl_v2.py` (rejouée seulement si une entrée change) |
| `charpente.toml` déclaratif (sans confiance requise) | `dsl/toml_loader.py` | `tests/test_dsl_v2.py` |
| Lint statique, exécuté avant chargement ; `migrate` | `lint.py`, `migrate.py`, `commands/lint.py` | `tests/test_lint_migrate.py` |
| Recettes, index, résolveur avec retour arrière | `pkg/recipe.py`, `index.py`, `resolver.py` | `tests/test_pkg.py` |
| Lockfile, installation, extraction sûre, correctifs, matérialisation en cibles | `pkg/lock.py`, `install.py`, `fetch.py`, `materialize.py` | idem + **dix paquets réels** (voir ci-dessous) |
| Hors-ligne : `vendor`, miroir HTTP avec `Range` | `pkg/vendor.py`, `pkg/mirror.py` | idem |
| Audit OSV, SBOM SPDX/CycloneDX | `pkg/audit.py`, `pkg/sbom.py` | idem (validation contre les schémas officiels) |
| Dix recettes livrées, vérifiées | `pkg/recipes/*.toml` | vérification manuelle réelle + test de forme |
| Téléchargements reprenables/vérifiés/plafonnés (livrés en P2) | `core/download.py` | `tests/test_download.py` |

## Vérification réelle (pas seulement des tests unitaires)

Sur cette machine (Windows 10, MinGW GCC 16, réseau disponible) :

1. `charpente pkg install` avec **dix** paquets (fmt, spdlog, nlohmann_json, glm, CLI11, entt, doctest,
   vulkan-headers, tomlplusplus, magic_enum) : téléchargés, SHA-256 vérifiés, verrouillés.
2. Un programme qui les utilise **tous** compile (31 s), se lie et s'exécute avec la sortie attendue.
3. `charpente pkg vendor` (21 Mo) puis, dans un dossier vierge, avec un **magasin de paquets vide** et
   `CHARPENTE_OFFLINE=1` : `pkg check` OK, build complet, exécution correcte, le magasin n'a jamais été créé.
   `pkg vendor --verify` : OK. `charpente sbom` produit les deux formats.

## Bogues réels trouvés par cette vérification (corrigés)

- L'extraction d'archives échouait sur les chemins de plus de 260 caractères de Windows (données de test de
  nlohmann_json, exemples de doctest) et faisait fuir une trace Python brute. Extraction réécrite membre par
  membre (préfixe `\\?\`, vérification lexicale des chemins) ; toute exception non prévue est maintenant
  rapportée en `CH9002` au format Charpente (`CHARPENTE_DEBUG=1` restaure la trace).
- `vendor` copiait des arbres entiers (tests, docs, exemples) : trop gros et hors limite de chemins. Il ne copie
  plus que ce qui sert au build (plus les licences).
- `charpente run` prenait les paquets pour des cibles ambiguës ; les paquets ne sont jamais la cible par défaut
  et `charpente build` ne construit que ceux réellement utilisés.
- Une recette indentée n'était pas re-pointée par `mirror populate` (expression régulière trop stricte) : corrigé.

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Tous les fichiers v0.1.0 passent | ✔ les 131 tests d'origine, inchangés, à travers le nouveau planificateur |
| Un projet utilisant 10 paquets se construit hors-ligne après `vendor` | ✔ vérifié réellement (ci-dessus) |
| SBOM valide SPDX et CycloneDX | ✔ validés contre les JSON Schemas officiels (SPDX 2.3, CycloneDX 1.5) |

## Écarts et limites (voir ADR 0009 et `docs/packages.md`)

- **Recettes en TOML et non « dans le DSL »** (décision argumentée dans l'ADR 0009).
- **Cache binaire téléchargeable** : non livré. Le cache par contenu du moteur assure « compilé une fois,
  réutilisé », mais aucun binaire précompilé n'est téléchargé d'un registre.
- **Ponts** vcpkg / Conan / pkg-config / CMake : non livrés. `charpente import cmake` reste prévu en P9.
- **Options de recette**, **recettes/registres signés** : non livrés.
- Le lint ne voit que les littéraux ; les noms calculés sont ignorés, pas devinés.
- Vérifié uniquement sous Windows/MinGW ; MSVC et clang-cl ne sont pas disponibles ici.
