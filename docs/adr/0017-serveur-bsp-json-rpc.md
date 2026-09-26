# ADR 0017 — Serveur, protocole et clients (P7)

- **Statut** : accepté (P7)

## Décisions

- **Un seul état, plusieurs clients** : `serve/state.py` (`ServerState`) porte tout ce qu'un client peut demander (charger, décrire, compiler, lancer, vérifier). Le
  serveur BSP, l'API WebSocket, `charpente tui` et l'extension VS Code passent par lui : pas de logique dupliquée dans les clients.
- **JSON-RPC 2.0 écrit à la main** (`serve/rpc.py`, ~190 lignes) plutôt qu'une bibliothèque : cadrage `Content-Length`, répartiteur, serveur stdio. Peu de code, zéro dépendance,
  testable par flux mémoire. Les requêtes s'exécutent sur un pool de threads (un build long ne bloque jamais la lecture) ; un seul build à la fois (`-32000`).
- **BSP 2.1 + extension C/C++** pour les IDE existants (`buildTarget/cppOptions`), plus des méthodes `charpente/*` pour ce que BSP ne dit pas (graphe, portail qualité, `why`,
  événements, base de compilation). Même répartiteur sur les deux transports.
- **WebSocket sur la boucle locale uniquement**, jeton aléatoire par exécution (comparaison à temps constant) + contrôle de `Origin`, pas de TLS (le trafic ne quitte pas la
  machine). Un serveur qui peut lancer du code ne doit accepter ni un autre utilisateur local ni une page web qui devine le port.
- **`buildTarget/run` : `arguments` = arguments du programme** (BSP) ; l'option de build va dans `data`. Le premier essai mélangeait les deux (`--config Debug` coupé en deux) —
  trouvé en exerçant l'extension contre un vrai serveur.
- **`canDebug: false`** et `$/cancelRequest` ignoré : dit dans la doc, pas simulé.
- **Extension VS Code : TypeScript minimal, testé contre un vrai serveur** et contre un faux module `vscode` (la logique de l'extension est vérifiée, pas le rendu de VS Code).
  Espace de travail non fiable = non supporté (un `.charpente` est du code). Rien n'est installé dans le VS Code de l'utilisateur ni publié.
- **`charpente shell`** : environnement pur (`shellenv.py`), commande exécutée en liste d'arguments (jamais `shell=True`), recherche du programme dans le PATH du shell.
- **`charpente tui`** : Textual, optionnel (`CH8018` sans lui).

## Bogues réels trouvés en vérifiant

- **Un enfant capturé héritait de stdin** : le serveur parle sur stdin/stdout ; `charpente run`/`check` lancés depuis le serveur pouvaient lire ou garder ouvert le canal (réponse
  jamais renvoyée, portail qualité figé). Corrigé à la racine dans `core/process.py` : un enfant dont la sortie est capturée n'a plus de stdin (`DEVNULL`), sauf `input=` explicite.
- Un en-tête `Content-Length` invalide laissait la ligne vide dans le flux : deux erreurs pour un message ; l'en-tête est désormais lu jusqu'au bout.
- Les erreurs de chargement de l'espace de travail n'avaient pas leur code `CHxxxx` dans le message (seulement dans `data`) : le client ne pouvait pas proposer « Expliquer ».
- Le module `shellenv` importait `subprocess` (interdit hors de la couche processus, le test d'architecture l'a signalé) : la mise en forme Windows passe par `process.windows_command_line`.

## Non fait

Annulation d'un build en cours, débogage (P8), authentification au-delà du jeton, serveur distant (P9), test avec un client BSP tiers, rendu de l'extension dans un VS Code réel.
