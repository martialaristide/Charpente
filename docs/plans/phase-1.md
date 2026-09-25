# Phase P1 — Moteur

## Objectifs (du cahier des charges)

Graphe d'actions, clés par contenu, suivi des en-têtes, parallélisme, cache local, `why`,
historique, `compile_commands.json`, banc d'essai.

## Ce qui a été construit

| Élément | Fichiers | Vérifié par |
|---|---|---|
| Graphe d'actions, chemin critique | `core/actions.py`, `core/graph.py`, `core/planner.py` | `tests/test_core_hashing_graph.py`, `tests/test_planner.py` |
| Clés par contenu (BLAKE3 / blake2b) | `core/hashing.py` | idem |
| Suivi exact des en-têtes | `core/depscan.py`, `flags.py` (`-MMD -MF`, `/showIncludes`) | `tests/test_core_depscan.py`, `tests/test_engine.py`, **compilateur réel** dans `tests/test_cli_engine_real.py` |
| Cache local par contenu + manifestes | `core/cache.py` | `tests/test_core_state_cache.py`, `tests/test_engine.py` |
| Ordonnanceur parallèle, priorité chemin critique | `core/engine.py` | `tests/test_engine.py` (concurrence mesurée) |
| État persistant, mémo de hachage, règle « racily clean » | `core/state.py`, `core/statcache.py` | `tests/test_core_state_cache.py` |
| Identité des outils (version + empreinte du binaire) | `core/toolid.py` | idem |
| `why` (prédictif et `--last`) | `commands/why.py`, `Engine.plan` | `tests/test_engine.py`, `tests/test_cli_engine_real.py` |
| Historique, `history`, `diff-build` | `core/history.py`, `commands/history.py` | `tests/test_cli_engine_real.py` |
| `compile_commands.json` | `core/compdb.py` | idem |
| Bus d'événements, schémas JSON, `--output jsonl`, journal rejouable | `events/`, `output/`, `commands/_session.py`, `commands/replay.py` | `tests/test_events.py` (+ validation des schémas), `tests/test_cli_engine_real.py` |
| Chemin rapide « rien à faire » | `core/fastpath.py` | `tests/test_fastpath.py` |
| Analyse du coût des en-têtes, conseils | `core/analysis.py`, `commands/headers.py` | `tests/test_analysis.py` |
| Globber sur `scandir` | `core/globber.py` | `tests/test_globber.py` (comparé à `pathlib`) |
| Tests instables (`test --retries`) | `commands/test.py` | `tests/test_cli_engine_real.py` |
| Banc d'essai | `bench/noop_build.py` | ADR 0010 |

## Bugs de la v0.1.0 corrigés au passage (trouvés par la conception, pas par accident)

- Deux sources de même nom dans des dossiers différents partageaient un objet (`obj/util.o`) : l'une
  écrasait l'autre en silence. Les objets reflètent maintenant l'arborescence.
- `include_dirs(["include"])` était relatif au *répertoire courant du shell*, pas à celui du
  workspace : `charpente build --file ../x.charpente` cassait. Les actions s'exécutent avec le
  dossier du workspace comme répertoire courant.
- Une bibliothèque modifiée ne relançait pas l'édition de liens de l'exécutable qui la lie
  (la bibliothèque n'était pas une entrée de l'action). Corrigé.
- Une archive `.a` conservait les membres des sources supprimées (`ar rcs` ajoute sans retirer) :
  les sorties sont supprimées avant exécution.
- Les avertissements d'une compilation réussie étaient perdus ; ils sont affichés (et rejoués
  depuis le cache).

## Critères d'acceptation

| Critère | Résultat |
|---|---|
| Modifier un en-tête recompile exactement les dépendants | ✔ testé avec un compilateur réel (`test_editing_a_header_rebuilds_exactly_its_dependents…`) et avec le faux compilateur (en-tête partagé / non partagé / supprimé / avec espaces) |
| No-op build < 300 ms sur 10 000 fichiers (sinon ADR + cœur Rust) | ✔ **242 ms** (Windows). ADR 0010 : cœur Python conservé, décision motivée par les mesures |
| `why` explique chaque recompilation | ✔ chaque action périmée porte au moins une raison (en-tête / entrée / commande / outil / environnement / sortie / amont) ; tests |

## Limites connues (voir aussi ADR 0006, 0007, 0010)

- Un build incrémental d'un projet de 10 000 fichiers coûte encore ~6 s (planification + évaluation
  complètes dès qu'un fichier change).
- Chemin `/showIncludes` (MSVC, clang-cl) : analyseur testé sur des sorties d'exemple, **jamais exécuté
  contre un vrai `cl.exe`** (indisponible ici). La CI Windows dispose de clang-cl ; à confirmer au premier push.
- Mesures faites sur une seule machine (Windows). Linux/macOS : à ajouter en CI.
- Le chemin de reprise `KeyboardInterrupt` est testé par simulation dans le thread principal, pas avec
  un vrai Ctrl+C sur un terminal.
