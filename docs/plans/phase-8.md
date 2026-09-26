# Phase P8 — Studio B : application, débogage, IA

| Élément | Fichiers | Vérifié par |
|---|---|---|
| `charpente studio` (serveur statique + WebSocket, jeton, Origin, Host, CSP) | `commands/studio.py`, `serve/webapp.py`, `serve/ws.py` | `tests/test_studio_web.py` |
| Méthodes des panneaux (fichiers, Git, appareils, paquets, options, terminal, profil, en-têtes, schéma du DSL, formatage) | `serve/studio.py`, `serve/insight.py`, `dsl/edit.py` | `tests/test_studio_api.py` |
| Relais LSP (clangd) et DAP | `serve/relay.py`, `serve/lsp.py` | idem, **clangd et gdb réels** |
| Application web (éditeur, panneaux, FR/EN, clair/sombre) | `studio_web/` | 33 tests `node --test` + 23 tests de bout en bout dans **Edge réel** |
| Débogage : `charpente debug`, `debug-adapter`, panneau, extension VS Code | `debug.py`, `commands/debug.py`, `studio_web/js/dap.js`, `panels/debug.js`, `vscode-charpente/` | `tests/test_debug.py` (gdb 17 réel), E2E |
| IA : `fix`, `ai tests`, `ai migrate`, contexte affiché, filtrage des secrets | `ai/`, `commands/fix.py`, `commands/ai.py`, `serve/ai_api.py` | `tests/test_ai_assist.py` (fournisseur factice), E2E (serveur OpenAI factice) |
| Processus longs (flux de lignes, duplex) ; enfants capturés sans stdin | `core/process.py` | idem |
| Correctif : `clang-cl` proposé seulement s'il compile | `toolchains.py` | test dédié + vérification réelle |
| Codes CH8019–CH8023 | `i18n/` | catalogue |
| ADR 0018, `docs/studio.md`, `debugging.md`, `ai.md` | | |

## Vérification réelle (Windows 10, MinGW, Edge, gdb 17.2, clangd 22, clang-format)

Un vrai navigateur pilote un vrai `charpente studio` sur un vrai projet C++ : construire, lancer, voir apparaître puis disparaître une erreur de compilation, compléter du code, résoudre un conflit d'enregistrement, indexer un seul bloc dans Git puis valider, lancer et arrêter une commande, ajouter un paquet, obtenir les diagnostics et la définition de clangd, **poser un point d'arrêt, s'arrêter dessus, lire la pile et les variables, évaluer une expression, avancer d'un pas, continuer jusqu'à la sortie du programme**, et vérifier qu'un secret du code ne part jamais vers le fournisseur d'IA.

## Écarts et limites

Pas de Tauri compilé (squelette `studio-desktop/` non construit), pas d'installeurs signés, pas de terminal à pty, éditeur maison (pas Monaco), pas de lldb-dap ni de Linux/macOS vérifiés, aucun fournisseur d'IA réel appelé, Edge seulement, annulation de build absente.
