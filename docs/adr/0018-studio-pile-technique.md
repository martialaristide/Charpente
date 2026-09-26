# ADR 0018 — Charpente Studio : pile technique (P8)

- **Statut** : accepté (P8)

## Contexte

Le cahier des charges demande une application de bureau « Tauri 2 + Monaco + clangd + xterm.js/portable-pty + DAP », et un ADR comparant Tauri, Qt et une distribution basée sur Code-OSS. Contraintes réelles de cet environnement : pas de chaîne Rust, pas de Mac, pas de moyen de signer des installeurs ; en revanche Node, Edge (Chromium), gdb 17, clangd, clang-format sont présents et ont servi à vérifier pour de vrai.

## Comparaison

| | **Tauri 2** | **Qt** | **Code-OSS (fork)** |
|---|---|---|---|
| Poids | quelques Mo (webview du système) | dizaines de Mo, dépend des modules | ≈ 300 Mo (Electron) |
| Interface | web (HTML/JS) : la même que dans un navigateur | C++/QML à écrire, sans rapport avec le serveur | déjà complète (éditeur, terminal, débogueur) |
| Langage du cœur | Rust (mince) + JS | C++ | TypeScript |
| Licence | MIT/Apache-2.0 | LGPL ou commerciale : contraintes de liaison pour des installeurs signés | MIT pour le code ; **binaire officiel, Marketplace et adaptateur de débogage C++ de Microsoft sous licences propriétaires** |
| Coût de maintenance | faible (le web fait le travail) | élevé (deux UI à maintenir) | très élevé (suivre la branche amont à chaque version, sans le Marketplace) |
| Vérifiable ici | non (pas de Rust) | non | non |

## Décisions

1. **Studio est d'abord une application web locale** (`charpente studio`) : le serveur de P7 sert des pages statiques sur la boucle locale et parle JSON-RPC/WebSocket. Elle marche dans tout navigateur récent, sans installation ni réseau, et c'est **la seule interface écrite** : le paquet de bureau n'en est qu'une fenêtre.
2. **Enveloppe de bureau : Tauri 2** (recommandé). Qt est écarté (une seconde interface à écrire et à tenir à jour, licence contraignante) ; un fork de Code-OSS est écarté (charge de maintenance disproportionnée, et l'extension VS Code couvre déjà ceux qui veulent VS Code). `studio-desktop/` contient un **squelette non compilé** (lance `charpente studio --json` et ouvre l'adresse dans une fenêtre) : dit comme tel, aucun installeur signé n'existe.
3. **Éditeur maison plutôt que Monaco.** Monaco pèse plusieurs Mo, demande un empaqueteur ou un chargeur AMD et une politique CSP qui autorise des workers/`eval` ; Studio se veut sans étape de construction et sa CSP interdit l'exécution dynamique. L'éditeur (`editor.js`, ≈ 300 lignes : `<textarea>` au-dessus d'un `<pre>` coloré) donne l'édition réelle (annulation, IME, accessibilité du navigateur) et se branche sur **clangd** par un relais LSP générique. Manques assumés : multi-curseurs, repli, minimap, recherche/remplacement. L'interface de la classe est petite : Monaco pourrait la remplacer plus tard.
4. **clangd, pas de LSP maison** : le serveur écrit une base de compilation à partir des arguments exacts du moteur (`flags.compile_args`) et relaie les messages (`serve/relay.py`, réutilisé pour le DAP). Les diagnostics, la complétion, la définition et le renommage sont ceux de clangd — vérifiés avec clangd 22.
5. **Débogage : DAP natif** (`gdb --interpreter=dap`, `lldb-dap`) derrière un adaptateur mince qui construit la cible avant `launch` (`debug.py`). Pas de débogueur ré-implémenté, pas d'adaptateur Microsoft.
6. **Terminal sans pty** pour l'instant : commandes en liste d'arguments, environnement du projet, flux de sortie. `xterm.js` + `portable-pty` sont pour l'enveloppe Tauri.
7. **IA à deux temps** : `charpente/ai/context` construit et montre le contexte exact (secrets remplacés) sans rien envoyer ; `charpente/ai/send` n'envoie que ce contexte-là, sur action de l'utilisateur. Un correctif est un diff vérifié, appliqué par `charpente/ai/apply` qui reconstruit, restaure en cas d'échec et relance le portail.
8. **Sécurité** : jeton dans l'URL (retiré de la barre d'adresse), vérifié par le seul WebSocket ; `Origin` et `Host` contrôlés ; CSP stricte ; les pages statiques sont publiques (le code est ouvert) — un cookie aurait été envoyé à toute page du même hôte, quel que soit le port.

## Bogues réels trouvés en vérifiant

- L'ensemble des tests de bout en bout dans un vrai Edge a trouvé : le profil ne montrait pas les builds lancés par Studio (aucun historique n'était écrit), et prenait pour « dernier build » une session `run` où tout était à jour ; le journal de build ne contenait pas le texte des erreurs du compilateur (seulement les diagnostics) ; un état « réussi » du build précédent restait affiché ; un nouveau fichier dans un dossier replié n'apparaissait pas dans l'explorateur ; la coloration d'un commentaire `/* … */` sur plusieurs lignes s'arrêtait à la fin de la première ligne (`$` en mode multiligne) ; `offsetOf` dépassait la fin du texte ; la complétion de `std::mov` coupait le mot.
- Le formatage à l'enregistrement réécrivait tout en style LLVM par défaut : il n'agit plus que si le projet a un `.clang-format`.
- **Installer clang (pour clangd) a révélé que `clang-cl` était choisi comme compilateur par défaut sur Windows alors qu'il ne peut rien compiler sans les en-têtes MSVC** : il n'est plus proposé qu'après avoir compilé un petit fichier avec la bibliothèque standard (`toolchains.clang_cl_works`).
- Un enfant dont la sortie est capturée héritait de stdin (voir ADR 0017) ; la mise en attente d'un `Page.navigate` de Chromium quand la page réécrit son adresse (contournée dans le pilote de test, pas dans Studio).

## Non fait

Enveloppe Tauri compilée, installeurs signés, mises à jour automatiques, terminal à pty, Monaco, annulation de build, chronologie (flamegraph) des actions, débogage distant (`adb`, SSH), Firefox/Safari, sessions multi-utilisateurs.
