# ADR 0011 — Plateformes et compilation croisée

- **Statut** : accepté (P4a)

## Décisions

- **La plateforme est une donnée** (`platforms.py`) : nom `os-arch`, niveau de support (1/2/3), triplets par ABI,
  ce qu'il faut installer. Les niveaux disent ce que *le projet* vérifie ; `charpente platforms` dit aussi ce que
  *cette machine* peut construire maintenant. Aucune promesse implicite.
- **Une toolchain déclare ce qu'elle sait cibler** (`Toolchain.targets`) et se *spécialise* (`cross.specialise`) :
  pour zig, `zig c++ -target <triplet>`. Le moteur, les clés d'action et `flags.py` ne changent pas : la
  spécialisation n'est que des arguments après l'exécutable (`c_args`, `cxx_args`, `ar_args`, `ld_args`) plus un
  environnement (`env`) — ils font donc partie de la clé d'action et du cache, gratuitement.
- **Pas de repli silencieux** : `--platform X` sans toolchain capable est l'erreur `CH8002` qui dit quoi installer ;
  jamais une compilation native à la place.
- **Répertoires et enregistrements par plateforme** : `build/<Config>-<plateforme>/` et identifiants d'action
  préfixés `<plateforme>/`. Passer d'une plateforme à l'autre ne reconstruit rien ; le cache par contenu est
  partagé. Les builds natifs gardent exactement leurs chemins et identifiants (rétrocompatibilité).
- **zig comme fournisseur de compilation croisée** : un seul binaire (~100 Mo), toutes les libc embarquées,
  distribuable sans droits administrateur. Installé sur demande (`toolchain install zig`) dans
  `~/.charpente/toolchains/`, SHA-256 vérifié avant extraction (l'index est servi en HTTPS par l'éditeur ; les
  signatures minisign de zig ne sont pas encore vérifiées — limite documentée).
- **Emscripten via emsdk** (git + python) plutôt qu'un téléchargement propre : emsdk gère ses propres
  composants (1,5 Go) ; on s'appuie sur ses contrôles d'intégrité et on le dit. Toolchain `cross_only` : jamais
  le choix par défaut d'un build natif.
- **Exécution de binaires étrangers** (`runners.py`) : direct si le CPU/OS le permet (x64 sur arm64 Windows/macOS),
  wasmtime ou Node (WASI) pour WebAssembly, sinon `CH8004`. Rien n'est émulé silencieusement.
- **Sorties annexes déclarées** (`side_outputs`) : `app.js` d'Emscripten s'accompagne de `app.wasm`, déclaré comme
  sortie de l'action pour que le cache le restaure (vérifié : suppression des deux fichiers puis restauration).
- **Langages** : assembleur et Objective-C passent par le pilote GNU (langage déduit du suffixe) ; MSVC refuse
  (`CH3007`). Les fichiers `.c` d'une cible C++ restent compilés en C++ (comportement v0.1.0 conservé).

## Bogues réels trouvés en vérifiant

- Un GCC MinGW donnait `libX.so` pour une bibliothèque partagée Windows ; c'est maintenant `X.dll`.
- Les lanceurs d'emsdk récents sont des `.exe` (et non `.bat`) sous Windows.
- Un outil qui échoue sans rien écrire (assembleur GNU sous MSYS) donnait « build failed » sans détail ; le message
  nomme maintenant l'outil et le code de sortie.

## Non fait dans cette phase

Modules C++20, shaders, sélection de l'ABI musl, MSVC croisé, exécution sous QEMU/Wine, signatures minisign de zig.
