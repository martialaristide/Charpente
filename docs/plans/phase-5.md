# Phase P5 — Qualité et Git

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Portail, niveaux, config, événements, `--fix`, `--changed`, enregistrements | `quality/gate.py`, `quality/model.py`, `commands/check.py` | `tests/test_quality.py` + exécution réelle |
| Vérifications : build, format, dsl-lint, secrets, taille, warnings, tidy, cppcheck, tests/flaky, sanitizers, couverture, plateformes, audit, licences, SBOM | `quality/checks_*.py`, `variants.py` | idem |
| Hooks Git, `--no-verify` tracé | `vcs/hooks.py`, `commands/vcs.py` | vrais dépôts temporaires |
| `status`, `commit` (Conventional Commits, brouillon, IA optionnelle), `push`, `pr` | `vcs/git.py`, `vcs/pr.py`, `commands/vcs.py` | dépôts réels + faux `gh`/API |
| `ci init` | `vcs/ci.py`, `commands/release.py` | structure de données + émetteur YAML testés |
| `release` : version, changelog, paquets, sommes, signature, provenance SLSA, tag | `vcs/release.py`, `vcs/vault.py`, `commands/release.py` | **release complète réelle** dans un dépôt temporaire |

## Vérification réelle

- `charpente check --level strict` sur un vrai projet C++ : build, secrets (une clé AWS factice détectée, valeur masquée), warnings (variable inutilisée dans le
  fichier modifié seulement), tests, **couverture gcov réelle** (66,7 % de 6 lignes), build de **trois plateformes croisées** (linux-arm64, wasm32-wasi, android-arm64),
  SBOM SPDX+CycloneDX ; sanitizers **refusés proprement** sous MinGW ; format/tidy/cppcheck ignorés (outils absents) et dit.
- Release de bout en bout dans un dépôt Git temporaire avec un vrai compilateur : version 0.1.0 → 0.1.1, CHANGELOG, zip, SBOM, `SHA256SUMS`, signature vérifiée avec la
  clé publique, provenance DSSE vérifiée, commit + tag, et rien de publié.

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Aucun commit/push sans portail (sauf `--no-verify`, tracé) | ✔ hooks + `commit`/`push` ; commits sans enregistrement signalés dans la PR |
| Chaque échec est un diagnostic localisé | ✔ événements `diagnostic.emitted` |
| Tests instables détectés | ✔ `--retries` → `flaky` |

## Écarts

Voir l'ADR 0015 : pas d'exécution contre GitHub, pas de couverture de branches, pas de MSVC pour certaines vérifications.
