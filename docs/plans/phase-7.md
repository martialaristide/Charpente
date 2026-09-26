# Phase P7 — Studio A : serveur, IDE, terminal

| Élément | Fichiers | Vérifié par |
|---|---|---|
| JSON-RPC 2.0 (cadrage, répartiteur, stdio) | `serve/rpc.py` | `tests/test_serve.py` |
| WebSocket RFC 6455 (boucle locale, jeton, Origin) | `serve/ws.py` | idem, exemple de clé du RFC, serveur réel |
| État du serveur, BSP 2.1 + `charpente/*` | `serve/state.py`, `serve/bsp.py` | idem + processus réel stdio et WebSocket |
| `charpente serve [--stdio, --ws, --bsp-install]` | `commands/serve.py` | idem |
| `charpente shell` | `shellenv.py`, `commands/shell.py` | `tests/test_shell_tui.py` |
| `charpente tui` | `tui.py`, `commands/tui.py` | idem, Textual `run_test` (builds réels) |
| Extension VS Code | `vscode-charpente/` | 23 tests `node --test` (client réel + faux module `vscode`), `.vsix` construit |
| Codes CH8017–CH8018 | `i18n/`, `docs/errors.md` | catalogue |
| Enfants capturés sans stdin | `core/process.py` | test dédié + session réelle |

## Vérification réelle (Windows 10, MinGW)

Conversation BSP complète sur un vrai projet C++ : initialize, cibles, sources, cppOptions, compile (erreur → diagnostic publié → correction → diagnostic effacé), run
(sortie du programme), check, explain, shutdown/exit. Extension : activée dans Node contre un vrai serveur.

## Écarts et limites

Extension jamais chargée dans un VS Code réel (rendu, icônes) ; pas de client BSP tiers ; pas d'annulation ; pas de DAP (P8) ; `vsce` n'a produit qu'un `.vsix` local (rien publié).
