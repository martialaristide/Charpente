# Phase P2 — Événements et modules

## Objectifs (du cahier des charges)

Bus d'événements, schémas JSON, sorties `plain/rich/jsonl`, hooks DSL, API de modules v2, manifeste,
capacités, modules officiels (langages et toolchains existants migrés en modules).

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Bus, taxonomie, schémas JSON, docs générées | `events/`, `tools/gen_event_docs.py`, `docs/events/` | `tests/test_events.py` (dont validation de chaque événement contre son schéma) |
| Sorties `plain`, `jsonl`, `rich`, annotations GitHub, journal rejouable | `output/`, `commands/_session.py`, `commands/replay.py` | `tests/test_hooks_output.py`, `tests/test_cli_engine_real.py` |
| Hooks DSL `@ws.on(Event.X)`, `notify()`, scripts `.charpente/hooks/` (avec approbation) | `hooks.py`, `dsl/api.py`, `dsl/trust.py` | `tests/test_hooks_output.py` |
| Manifeste, API de modules 2.0, registre d'extensions | `modules/api.py`, `manifest.py`, `registry.py` | `tests/test_modules_core.py` |
| Capacités gardées (`ctx.process/fs/net/emit`) | `modules/capabilities.py` | idem (traversée, lien symbolique, hôtes, événements) |
| Installation (dossier, zip, URL, registre), mises à jour, magasin | `modules/installer.py`, `store.py`, `core/download.py` | idem + `tests/test_download.py` (reprise, somme de contrôle, budget, hors ligne) |
| Signatures Ed25519 | `modules/signing.py` | `tests/test_signing.py` (vecteurs RFC 8032) |
| Chargement défensif, index de commandes, découverte par le CLI | `modules/loader.py`, `runtime.py`, `cli.py` | idem |
| Toolchains intégrés réécrits en modules | `modules/builtin.py`, `toolchains.detect()` | `tests/test_modules_core.py::test_builtin_toolchain_preference_order_is_unchanged` + les 131 tests d'origine |
| Conformité | `modules/conformance.py`, `charpente module check` | `tests/test_modules_core.py` |
| Module officiel de notifications (desktop, webhook, Discord, Slack, Telegram, e-mail) | `modules/official/` | `tests/test_modules_cli.py` (serveur HTTP local, SMTP simulé) |
| Module tiers d'exemple qui s'installe et fonctionne | `examples/modules/charpente-hello` | `tests/test_modules_core.py` |
| Codes d'erreur CH6xxx/7xxx, semver | `semver.py`, `i18n/` | `tests/test_semver.py`, `tests/test_errors_catalog.py` |

## Bug trouvé par les tests de cette phase

`workspace_finder` cherchait `*.charpente` sans vérifier que c'est un *fichier* : le dossier `.charpente/`
(état, hooks, `notify.toml`, `quality.toml`) correspond au motif et rendait tout projet qui l'utilise
« ambigu » (`CH1003`). Corrigé, avec test de non-régression.

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Toolchains existantes réécrites en modules sans régression | ✔ mêmes six détecteurs, même ordre de préférence, via le point d'extension ; les 131 tests d'origine passent inchangés |
| `--output jsonl` validé contre les schémas | ✔ `test_jsonl_output_is_valid_events` (sortie réelle d'un build) + un événement de chaque type contre le schéma combiné |
| Un module tiers d'exemple s'installe et fonctionne | ✔ installation, chargement, commande, toolchain, événement, conformité |

## Limites et écarts à signaler

- Les capacités sont un **contrat**, pas un bac à sable (ADR 0008, `security.md`).
- **Aucune clé officielle** n'est publiée : tout module tiers est « non signé » aujourd'hui. Pas de
  Sigstore.
- Le registre officiel n'existe pas encore : `module add NOM` demande un registre configuré.
- Le rendu `rich` est testé sur une console simulée ; **pas observé sur un vrai terminal interactif** ici.
- `notify` desktop utilise `powershell`/`osascript`/`notify-send` : testé avec un exécuteur simulé,
  pas d'affichage réel vérifié.
- Les autres langages (Objective-C, shaders…) deviendront des modules dans P4 ; seul le point
  d'extension `language` est réservé.
