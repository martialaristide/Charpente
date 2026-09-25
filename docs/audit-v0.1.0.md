# Audit du dépôt — état v0.1.0

Réalisé au début de la phase P0, avant toute modification. Chiffres mesurés,
pas estimés.

## Mesures

| Élément | Valeur |
|---|---|
| Code source (`charpente/`) | ~1 900 lignes Python, 0 dépendance obligatoire (hors `colorama` sous Windows) |
| Tests | 131 tests, tous verts (Windows 10, Python 3.12, MinGW gcc 15) |
| Versions Python visées | 3.9 → 3.12 (CI : 3.9 et 3.12 × Windows/Linux/macOS) |
| Compilateurs réellement exercés | MinGW gcc (local) ; clang-cl et gcc/clang en CI |
| Outils de qualité configurés | aucun (`ruff`, `mypy`, couverture : absents) |
| Publication | non publié sur PyPI |

## Ce qui est solide (à préserver)

- **Séparation pur / effets** : `flags.py` et `installer.py` ne lancent aucun
  processus ; `builder.py` reçoit `run` par injection. C'est ce qui rend les
  131 tests possibles sans compilateur.
- **Sécurité** : jamais `shell=True` (vérifié par recherche), noms validés à la
  construction (`safe_name`), confiance par empreinte SHA-256.
- **Honnêteté** : le repli silencieux n'existe pas (un installeur absent produit
  le script + la commande manuelle, jamais un faux résultat).

## Écarts par rapport au cahier des charges

| # | Constat | Emplacement | Phase |
|---|---|---|---|
| A1 | `subprocess` appelé depuis 5 modules (`builder`, `run`, `test`, `package`, `ai`) au lieu d'une seule couche | `builder.py`, `commands/*.py` | P0 |
| A2 | Erreurs sans code stable ; messages en anglais seulement ; 3 hiérarchies d'exceptions différentes (`CommandError`, `WorkspaceLoadError`, `NoToolchainFoundError`…) | partout | P0 |
| A3 | Pas de `charpente explain`, pas d'i18n | — | P0 |
| A4 | CI sans `ruff`, `mypy`, couverture ; pas de workflow de publication | `.github/workflows/tests.yml` | P0 |
| A5 | Incrémental par horodatage seulement : un en-tête modifié ne recompile rien (limite n° 1) | `builder._needs_rebuild` | P1 |
| A6 | Compilation strictement séquentielle, pas de cache, pas de graphe | `builder.build_target` | P1 |
| A7 | `Kind` limité à 4 valeurs, `OS` à 3 ; pas de notion de plateforme/triplet | `dsl/model.py` | P3/P4 |
| A8 | Lecture de `.charpente` : `exec` sans analyse statique préalable | `dsl/loader.py` | P3 |
| A9 | `pyproject.toml` : pas de `[tool.ruff]`/`[tool.mypy]`, pas d'extra `fast` | — | P0 |
| A10 | Tous les compilateurs sont codés en dur dans `toolchains.py` (pas d'extension possible sans toucher au cœur) | `toolchains.py` | P2 |

## Risques identifiés avant de commencer

1. **Compatibilité 3.9** : `tomllib` n'existe qu'à partir de 3.11 → dépendance
   conditionnelle `tomli`. Pas de `match`, pas de `X | Y` évalué à l'exécution.
2. **BLAKE3** n'est pas dans la bibliothèque standard → extra optionnel avec
   repli `hashlib.blake2b` (préfixe d'algorithme dans chaque clé : un cache
   n'est jamais corrompu par un mélange d'algorithmes, il rate simplement).
3. **Portée** : le cahier des charges couvre plusieurs années de travail. Ce
   dépôt ne peut être vérifié ici que sur Windows + MinGW gcc (+ zig via PyPI
   pour la compilation croisée). Tout ce qui exige un matériel ou un SDK
   absent (Android réel, HarmonyOS, casque XR, macOS/iOS) sera livré comme
   *code + tests unitaires du calcul pur*, et marqué **non testé sur
   matériel réel** dans chaque rapport de phase.
4. **PyPI** : la publication est irréversible et exige un compte. Elle sera
   *préparée* (`sdist` + `wheel` validés, workflow de publication par « trusted
   publishing ») mais pas exécutée sans ordre explicite.
