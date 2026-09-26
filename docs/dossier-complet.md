# Charpente — Dossier complet (version 0.13.0)

Fonctionnement, utilité, utilisation et lignes de commande ; rapport de développement ; guide de maintenance ; guide utilisateur ; nouveautés de cette version.

> **Ce dossier est un document de synthèse.** Il regroupe et relie les pages détaillées de `docs/` (dont il donne les chemins) ; en cas de doute sur un détail d'option, `charpente <commande> --help` fait foi.
> Il dit, partout, ce qui est **vérifié**, **testé seulement**, **expérimental** ou **non fait** (définitions en section 12).

## Table des matières

1. [Présentation : qu'est-ce que Charpente, à quoi ça sert](#1-présentation)
2. [Fonctionnement : l'architecture](#2-fonctionnement)
3. [Guide utilisateur](#3-guide-utilisateur)
4. [Référence des lignes de commande](#4-référence-des-lignes-de-commande)
5. [Charpente Studio](#5-charpente-studio)
6. [Les autres composants : serveur, VS Code, shell, TUI, débogage, IA](#6-les-autres-composants)
7. [Packages, kits, modèles, modules, plateformes](#7-packages-kits-modèles-modules-plateformes)
8. [Rapport de développement](#8-rapport-de-développement)
9. [Nouveautés de la version 0.13.0](#9-nouveautés-de-la-version-0130)
10. [Guide de maintenance](#10-guide-de-maintenance)
11. [Variables d'environnement, fichiers et codes d'erreur](#11-variables-fichiers-et-codes-derreur)
12. [État de vérification et limites, sans détour](#12-état-de-vérification-et-limites)

---

## 1. Présentation

### 1.1 Ce que c'est

**Charpente** est un système de build pour C et C++, écrit en Python, sous licence Apache-2.0. On décrit le projet dans un fichier `.charpente` (syntaxe Python, mais c'est une *description* : cibles, sources, dépendances) ; Charpente le compile, le teste, l'empaquette, pour Windows, Linux, macOS, mais aussi Android, HarmonyOS, le web (WebAssembly), les microcontrôleurs, etc.

Il est devenu, au fil des phases P0 à P9, un **écosystème** en quatre parties :

| Partie | Rôle | Où |
|---|---|---|
| **Engine** (moteur) | Builds incrémentaux exacts, cache adressé par le contenu (local et partageable), builds reproductibles, flux d'événements pour les outils | `charpente/core/`, `builder.py`, `events/` |
| **Pkg** | Gestionnaire de paquets (recettes, résolution, fichier de verrouillage, SBOM, audit) et **kits** (ensembles de bibliothèques choisies) | `charpente/pkg/` |
| **Kits et modèles** | 10 kits, 31 recettes, 16 modèles de projet prêts à l'emploi | `pkg/kits/`, `pkg/recipes/`, `templates_data/` |
| **Studio** | Application web locale, extension VS Code, serveur de build (BSP/JSON-RPC), débogage (DAP), assistance IA optionnelle | `serve/`, `studio_web/`, `vscode-charpente/`, `debug.py`, `ai/` |

### 1.2 À quoi ça sert (utilité)

- **Remplacer CMake/Make** par un fichier court et lisible, sans générer de fichiers intermédiaires : `charpente build` suffit.
- **Aller vite et juste** : une reconstruction ne recompile que ce qui doit l'être (décidé d'après le *contenu*, pas les horodatages), avec un cache qui rend instantané un retour en arrière ou un clone neuf, et qu'une équipe peut partager.
- **Faire confiance au résultat** : builds reproductibles vérifiables (`verify-reproducible`), budgets de taille et de temps, portail qualité (format, secrets, avertissements, tests, sanitizers, licences, SBOM), versions signées.
- **Viser beaucoup de plateformes** avec les mêmes commandes (`--platform linux-arm64`, `android-arm64`, `wasm32-wasi`…), Android sans Gradle, HarmonyOS, firmware.
- **S'intégrer** aux éditeurs (VS Code, tout client BSP), à clangd, à gdb/lldb, et **importer/exporter** vers CMake, Ninja, Visual Studio.
- **Rester honnête et sûr** : erreurs à code stable `CHxxxx` expliquées en français et en anglais (`charpente explain`), aucune commande passée par un shell (toujours des listes d'arguments), consentement avant d'exécuter un `.charpente`, rien de publié ni de poussé sans demande explicite.

### 1.3 Ce qui le distingue (principes de conception)

Compatibilité ascendante avec les fichiers de la v0.1.0 ; aucun repli silencieux (une fonction impossible donne une erreur codée, pas un comportement approximatif) ; code original ; fonctions pures d'abord (planification, options de compilation, politique de ressources), donc testables sans machine particulière ; tout est testé ; niveaux de vérification annoncés par fonction ; sécurité par défaut (boucle locale, jetons dans l'environnement, jamais dans un fichier) ; fonctionnement hors ligne d'abord ; jamais d'acceptation d'une licence de fournisseur à la place de l'utilisateur.

---

## 2. Fonctionnement

### 2.1 Le parcours d'un `charpente build`

```
 fichier .charpente ──► confiance (consentement) ──► exec() ──► Workspace (modèle de données)
        │
        ▼
 résolution par (configuration, plateforme, chaîne d'outils) : recouvrements, `uses`, options, paquets
        │
        ▼
 planification : Workspace ──► ActionGraph (actions = commande + entrées + sorties + environnement + outil)
        │
        ▼
 chemin rapide « rien n'a changé » (métadonnées seules, ~0,25 s pour 10 000 fichiers)  ─ sinon ─►
        │
        ▼
 moteur : pour chaque action, fraîcheur (contenu) ► cache (local, puis partagé) ► exécution (parallèle)
        │
        ▼
 événements (bus typé) ► sorties : texte, Rich, JSON Lines, annotations GitHub, journal de session, historique SQLite
```

### 2.2 Les briques

| Brique | Rôle | Fichiers |
|---|---|---|
| Modèle et DSL | `Workspace`, `Target`, `Rule`, `Kind`, conditions (`on_config`, `on_platform`, `on_toolchain`), options, `uses`, `charpente.toml` (forme déclarative) | `dsl/` |
| Chaînes d'outils | Détection (GCC, Clang, MSVC, clang-cl, MinGW, zig, Emscripten, NDK, OpenHarmony…), options de compilation pures | `toolchains.py`, `flags.py`, `toolchains/`, `cross.py` |
| Planificateur | Modèle → graphe d'actions | `core/planner.py`, `core/graph.py` |
| Moteur | Fraîcheur par contenu, ordonnanceur parallèle, reprise | `core/engine.py`, `core/state.py` (SQLite) |
| En-têtes | Découverte exacte (`-MMD`, `/showIncludes`) : modifier un en-tête recompile *exactement* les fichiers qui l'incluent | `core/depscan.py` |
| Cache local | Adressé par le contenu (BLAKE3, repli blake2b), avec manifestes d'en-têtes | `core/cache.py`, `core/hashing.py` |
| Cache partagé | Serveur HTTP + client, entrées signées HMAC, échec ouvert | `core/cache_server.py`, `core/remote.py` |
| Couche processus | **Seul** endroit où un processus est lancé ; jamais de shell | `core/process.py` |
| Événements | Bus typé, schémas JSON générés (51), mode strict en test | `events/` |
| Modules | Extensions signées (Ed25519), capacités gardées, approbation | `modules/` |
| Serveur | JSON-RPC 2.0, BSP 2.1, WebSocket, relais LSP/DAP | `serve/` |
| Studio | Application web (ES modules, sans étape de build) | `studio_web/` |
| Qualité et Git | Portail, hooks, PR, versions signées | `quality/`, `vcs/` |

### 2.3 Le cache et la reproductibilité

- **Clé d'action** = empreinte de tout ce qui détermine le résultat (commande, contenu des entrées et des en-têtes lus, identité de l'outil : chemin + version + empreinte du binaire, environnement). Une entrée périmée ne peut donc jamais être servie.
- **Local** : `~/.charpente/cache` (variable `CHARPENTE_CACHE_DIR`), partagé entre tous les projets.
- **Partagé** : ordre de recherche *local, puis distant* ; un accès distant réussi est copié en local (vérifié) ; si le serveur est indisponible, le build continue en local avec un avertissement. Les clés ne sont *relocatables* (indépendantes du dossier et du chemin du compilateur) que dans la saveur reproductible.
- **Reproductible** (`--reproducible`) : dossier du projet réécrit en `/src`, horloge figée, pas d'horodatage ni de build-id à l'édition de liens, archives déterministes. Chaînes de style GNU seulement (MSVC refusé).

### 2.4 Sécurité en bref

Consentement avant d'exécuter un `.charpente` (`CHARPENTE_TRUST_ALL=1` pour la CI de confiance) ; aucune commande n'est passée par un shell ; noms validés (pas d'injection de chemin) ; serveurs sur la boucle locale avec jeton + contrôle `Origin`/`Host` + CSP stricte ; jetons et phrases secrètes uniquement par l'environnement ou une invite ; IA jamais automatique, contexte montré avant envoi, secrets masqués ; téléchargements vérifiés par SHA-256 ; téléchargements de chaînes d'outils uniquement sur demande. Détails : `docs/security.md`.

---

## 3. Guide utilisateur

### 3.1 Installation

```bash
git clone https://github.com/martialaristide/Charpente.git && cd Charpente
pip install -e .                     # Python 3.9+ ; PyPI : pas encore publié
pip install -e ".[tui,ai,fast,rich]" # extras optionnels
charpente --version                  # charpente 0.13.0
charpente setup                      # premier lancement guidé
charpente doctor                     # ce que la machine sait construire
```

Il faut un compilateur C/C++ : Visual Studio Build Tools, LLVM ou MSYS2/MinGW (Windows) ; `gcc`/`clang` (Linux) ; Xcode Command Line Tools (macOS). Sans compilateur : `charpente toolchain install zig` (aucun droit administrateur, rien n'est ajouté au PATH).

### 3.2 Premier projet en cinq minutes

```bash
charpente init hello --template console
cd hello
charpente build
charpente run --target hello -- Ada        # Hello, Ada!
charpente test
```

La première fois, Charpente demande s'il peut exécuter le `.charpente` (c'est du code). Le fichier :

```python
from charpente import *

with Workspace("hello") as ws:
    ws.configurations(["Debug", "Release"])
    ws.requires("fmt")                       # paquet externe (puis `charpente pkg install`)
    ws.budget(build_time="90s")              # nouveauté 0.13

    with Target("core") as core:
        core.kind(Kind.STATIC_LIBRARY)
        core.sources(["src/core/*.cpp"])
        core.public_include_dirs(["include"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("core", "fmt")              # ordre de build + édition de liens + réglages publics
        app.budget(size="2MB")               # nouveauté 0.13
        with app.on_config("Release") as c:
            c.defines(["NDEBUG"])
```

### 3.3 Le DSL en un tableau

| Élément | Exemples |
|---|---|
| Espace de travail | `Workspace("nom", version="1.0.0")`, `ws.configurations([...])`, `ws.platforms([...])`, `ws.requires("pkg")`, `ws.kit("kit-core")`, `ws.option("nom", default=…, choices=[…])`, `ws.budget(...)`, `@ws.on(Event.X)` |
| Cible | `Target("nom")`, `.kind(Kind.EXECUTABLE / STATIC_LIBRARY / SHARED_LIBRARY / TEST / HEADER_ONLY / PLUGIN / MOBILE_APP / …)`, `.language()`, `.standard()`, `.sources([globs])`, `.exclude()`, `.include_dirs()`, `.public_include_dirs()`, `.defines()`, `.links()`, `.uses()`, `.uses_public()`, `.compile_flags()`, `.link_flags()`, `.budget(size=…)` |
| Conditions | `.on_config("Release")`, `.on_platform("linux-*")`, `.on_toolchain("msvc")`, `.when(config=…, platform=…)` |
| Règles | `Rule("nom")` avec `.command([liste])`, `.inputs()`, `.outputs()` : étapes de build maison, mises en cache |
| Déclaratif | `charpente.toml` (forme purement données) |

Référence complète : `docs/dsl-reference.md`. `charpente lint` analyse un fichier sans l'exécuter ; `charpente migrate` réécrit les idiomes v0.1.0 en DSL v2.

### 3.4 Au quotidien

| Je veux… | Commande |
|---|---|
| construire / en Release | `charpente build` / `charpente build --config Release` |
| voir pourquoi une recompilation a eu lieu | `charpente build -v`, `charpente why FICHIER_OU_CIBLE` |
| reconstruire à chaque enregistrement | `charpente dev` |
| lancer / tester | `charpente run --target T -- args`, `charpente test` |
| comprendre une erreur | `charpente explain CH1009 --lang fr` |
| trouver les en-têtes coûteux | `charpente headers --top 10` |
| comparer avec le build précédent | `charpente history`, `charpente diff-build` |
| nettoyer | `charpente clean` |
| compiler pour une autre plateforme | `charpente toolchain install zig` puis `charpente build --platform linux-arm64` |
| vérifier la qualité avant de valider | `charpente check --level standard` ; `charpente commit -m "…"` |
| équipe : partager le cache | `charpente cache serve` + `CHARPENTE_REMOTE_CACHE` (voir 4.6) |
| tout retirer de la machine | `charpente self uninstall` (essai à blanc), puis `--yes` |

### 3.5 Scénarios complets

**Android sans Gradle** : `charpente init phone --template app-android --install`, puis `charpente toolchain install ndk --accept-android-license` (vous tapez l'acceptation, Charpente ne le fait jamais), `charpente deploy --platform android-x64` (APK signé installé et lancé), ou `charpente deploy --device all --logs` pour tous les appareils connectés.

**Web** : `charpente init web --template web-wasm`, `charpente toolchain install emsdk`, `charpente build --platform wasm32-emscripten`.

**Équipe/CI** : un serveur `charpente cache serve --host 0.0.0.0 --token-env CACHE_TOKEN` derrière un proxy TLS ; les clients définissent `CHARPENTE_REMOTE_CACHE`, `CHARPENTE_REMOTE_CACHE_TOKEN`, `CHARPENTE_CACHE_SIGNING_KEY` et construisent avec `--reproducible`.

**Depuis CMake** : `charpente import cmake chemin/du/projet` ; **vers un autre outil** : `charpente generate ninja|cmake|vs|compile-commands`.

**Boucle de développement avec rechargement à chaud** : `charpente dev` dans un terminal, l'hôte dans un autre (voir `docs/hot-reload.md`).

### 3.6 Dépannage rapide

1. `charpente doctor` (compilateurs, outils, plateformes constructibles).
2. `charpente build -v` (chaque commande et sa raison).
3. `charpente explain CHxxxx` (cause et remède, en français ou anglais).
4. `CHARPENTE_DEBUG=1` affiche la trace complète d'une erreur interne (code CH9002).
5. `docs/troubleshooting.md` classe les messages courants.

---

## 4. Référence des lignes de commande

Options communes aux commandes qui construisent (`build`, `run`, `test`, `package`, `deploy`, `dev`, `fix`, `generate`, `size`, `flash`) : `--file F.charpente`, `--config Debug|Release`, `-j N`, `--no-cache`, `-v`, `--opt NOM=VALEUR`, `--platform OS-ARCH`, `--sanitize address,undefined`, `--coverage`, `--eco`, `--reproducible`, `--toolchain NOM`, `--output auto|plain|rich|jsonl`.
Sans `--file`, Charpente cherche le seul `.charpente` du dossier courant puis de ses parents.

### 4.1 Construire, lancer, tester, empaqueter

| Commande | Ce qu'elle fait | Options propres |
|---|---|---|
| `charpente init [NOM]` | Crée un projet minimal, ou depuis un modèle | `--dir D`, `--template T`, `--list`, `--install` |
| `charpente build` | Compile le workspace, dans l'ordre des dépendances | `--keep-going`, `--no-budget`, `--ai-diagnose` |
| `charpente run` | Construit (si besoin) et lance une cible | `--target T`, `--no-build`, puis `-- arguments du programme` |
| `charpente test` | Construit et lance les cibles de test | `--retries N` (un test qui échoue puis passe est signalé instable) |
| `charpente package` | Empaquette la sortie | `--target`, `--output`, `--format zip\|installer\|apk\|app\|ipa\|hap\|har\|hsp`, `--version`, `--maintainer`, `--keystore`, `--key-alias` |
| `charpente clean` | Supprime la sortie de build | |
| `charpente dev` | Reconstruit à chaque changement ; publie les plugins pour le rechargement à chaud (expérimental) | `--target`, `--hot-dir`, `--poll S`, `--cycles N`, `--no-initial-build` |
| `charpente deploy` | Construit une appli Android, l'installe et la lance | `--target`, `--device SERIE\|all`, `--logs`, `--log-seconds N`, `--log-filter TEXTE`, `--no-launch`, `--keystore`, `--key-alias` |
| `charpente size` / `charpente flash` | Firmware : mémoire flash/RAM ; programmation de la carte | `flash` : `--tool openocd\|pyocd\|probe-rs\|avrdude\|esptool\|dfu-util`, `--dry-run` |

### 4.2 Comprendre et diagnostiquer

| Commande | Ce qu'elle fait |
|---|---|
| `charpente why SUJET [--last]` | Explique pourquoi une cible ou un fichier est (ou a été) reconstruit |
| `charpente history [--limit N]` | Sessions de build récentes |
| `charpente diff-build [A [B]]` | Compare deux sessions : temps, actions, taille des binaires, avertissements apparus/disparus |
| `charpente headers [--top N]` | Classe les en-têtes selon le travail qu'ils déclenchent |
| `charpente replay [SESSION] [--output plain\|jsonl]` | Rejoue un build depuis son journal d'événements |
| `charpente explain [CODE] [--lang en\|fr] [--list]` | Explique un code d'erreur (125 codes) |
| `charpente doctor [--json]` | Diagnostic de la machine : compilateurs, outils, débogueurs, plateformes constructibles |
| `charpente platforms [--json] [--family …]` | Les 30 plateformes, leur niveau, et si cette machine peut les construire |
| `charpente options [--opt …]` | Liste les options déclarées par `ws.option()` |
| `charpente lint [--strict]` / `migrate [--write]` | Analyse statique d'un `.charpente` / réécriture v0.1.0 → v2 |

### 4.3 Chaînes d'outils, plateformes, paquets, kits, modules

| Commande | Sous-commandes / options |
|---|---|
| `charpente toolchain` | `list` · `install zig[@V] \| emsdk[@V] \| ohos[@V] \| ndk \| build-tools \| platform \| platform-tools` (Android : `--accept-android-license`) · `remove NOM[@V]` |
| `charpente pkg` | `install` · `list` · `check` · `info` · `search` · `vendor` · `audit` (OSV) · `registry` · `mirror` |
| `charpente sbom` | `--format spdx\|cyclonedx\|both`, `--output` |
| `charpente kit` | `list` · `show NOM` · `add NOM` |
| `charpente module` | `list` · `info` · `add` · `remove` · `enable` · `disable` · `approve` · `update` · `check` · `new` · `keygen` · `sign` · `trust-key` · `registry` |
| `charpente cache` | `stats` · `dir` · `clear` · `gc [--max-size]` · `serve` (`--dir --host --port --token-env --readonly --max-blob`) · `remote` |

### 4.4 Qualité, Git, versions

| Commande | Ce qu'elle fait |
|---|---|
| `charpente check` | Portail qualité. `--level rapide\|standard\|strict`, `--changed`, `--fix`, `--only C`, `--skip C`, `--platform`, `--json`, `--list`, `--init`. Contrôles : *rapide* build, format, dsl-lint, secrets, file-size ; *standard* warnings, clang-tidy, cppcheck, tests ; *strict* sanitizers, coverage, platforms, audit, licences, sbom |
| `charpente status [--json]` | État Git, dernier build, dernier résultat du portail |
| `charpente commit [-m MSG] [-a] [--level …] [--no-verify] [--ai]` | Portail sur ce qui a changé, puis commit |
| `charpente push [--set-upstream] [--force-with-lease] [remote]` | Portail standard, puis push |
| `charpente pr [--base --title --summary --draft --sbom --push --dry-run]` | Ouvre une pull request avec le résumé et le résultat du portail |
| `charpente hooks install\|uninstall\|status` | Installe des hooks Git qui lancent le portail |
| `charpente ci init` | Écrit un workflow GitHub Actions |
| `charpente sign init\|list\|public\|verify` | Clés de version Ed25519 (chiffrées) |
| `charpente release [--bump --platforms --key --no-sign --dry-run --publish --remote]` | Prépare une version signée (sommes de contrôle, provenance SLSA) ; **ne publie qu'avec `--publish`** |

### 4.5 Interopérabilité et reproductibilité (P9)

| Commande | Ce qu'elle fait |
|---|---|
| `charpente verify-reproducible [--config --platform --keep --json]` | Construit deux fois dans deux dossiers et compare octet par octet |
| `charpente import cmake [DOSSIER] [--out --force --build-dir --cmake --cmake-arg --print]` | Écrit un `.charpente` à partir d'un projet CMake, en interrogeant CMake (File API) |
| `charpente generate [compile-commands\|ninja\|cmake\|vs\|xcode] [--out --force --list]` | Fichiers de projet pour d'autres outils (`xcode` : non implémenté) |
| `charpente docs [--out D] [--doxygen]` | Pages d'API en Markdown à partir des commentaires, graphe Mermaid/SVG |

### 4.6 Studio, serveur, terminal, débogage, IA

| Commande | Ce qu'elle fait |
|---|---|
| `charpente studio [--root --file --port --no-browser --json]` | Ouvre Charpente Studio dans le navigateur |
| `charpente serve [--stdio \| --ws] [--port] [--root] [--file] [--bsp-install]` | Le moteur comme serveur JSON-RPC/BSP |
| `charpente shell [--platform --toolchain --config --print-env --format sh\|powershell\|cmd\|json] [-- CMD]` | Shell avec la chaîne d'outils du projet dans le PATH, `CC/CXX/AR` définis |
| `charpente tui [--root --file --config]` | Interface Textual (`pip install "charpente[tui]"`) |
| `charpente debug [CIBLE] [-- ARGS]` · `debug --list` | Construit puis débogue sous gdb/lldb |
| `charpente debug-adapter [--root --file --debugger gdb\|lldb-dap]` | Adaptateur DAP sur stdio pour les éditeurs et Studio |
| `charpente fix [--show-context --dry-run --yes --apply]` | Propose un correctif (diff à approuver) pour un build en échec |
| `charpente ai status\|tests\|migrate` · `charpente ask "question"` | Assistance IA optionnelle |

### 4.7 Installation et désinstallation (P9)

| Commande | Ce qu'elle fait |
|---|---|
| `charpente setup [--yes] [--lang en\|fr]` | Premier lancement guidé : propose ce qui manque, demande avant chaque téléchargement, n'accepte jamais de licence pour vous, mémorise la langue |
| `charpente` (seul) · `charpente menu` | **Ajout après la 0.13.0** : menu guidé dans le terminal (créer, construire, lancer, tester, plateforme, diagnostic, Git, cache), avec la commande équivalente affichée avant chaque action. Flèches, raccourcis, Échap ; numéros + Entrée sans terminal interactif. `CHARPENTE_CONSOLE=off` rend l'aide simple. Voir `docs/console.md` |
| `charpente self uninstall [--only GROUPE] [--keys] [--yes]` | Retire ce que Charpente stocke (cache, chaînes d'outils, paquets, modules, keystore de debug Android, confiance, préférences). **Essai à blanc sans `--yes`** ; les **clés de signature** ne sont retirées qu'avec `--keys` ; les projets ne sont jamais touchés |

---

## 5. Charpente Studio

### 5.1 Utilité

Studio est l'espace de travail graphique du projet, **dans le navigateur**, servi localement (`127.0.0.1`) : rien à installer en plus de Charpente, aucun accès réseau nécessaire. Il parle au même serveur que les éditeurs, donc ce qu'il montre est exactement ce que fait la ligne de commande.

### 5.2 Lancement

```bash
cd mon-projet
charpente studio                       # ouvre http://127.0.0.1:PORT/?token=…
charpente studio --no-browser --json   # imprime l'adresse en JSON (scripts, enveloppe de bureau)
```

L'adresse contient un **jeton privé** : quiconque l'a peut construire et exécuter du code dans le projet. Ne la partagez pas. Ctrl+C arrête Studio.

### 5.3 Les zones

| Zone | Fonctions |
|---|---|
| **Explorateur** | Fichiers (arbre paresseux, nouveau fichier) ; Cibles (construire/lancer, dépendances, dernier résultat) ; Options (`ws.option`, enregistrées dans `.charpente/options.toml`) ; Paquets (recherche, ajout/retrait de `ws.requires`, installation) |
| **Éditeur** | Onglets, coloration (C/C++, Python, `.charpente`, JSON, TOML, Markdown, CMake, shell, YAML, GLSL), complétion (schéma du DSL ; **clangd** pour C/C++), diagnostics, définition (F12), renommage, formatage à l'enregistrement (clang-format, seulement avec un `.clang-format`), détection de conflit d'enregistrement |
| **Build** | Progression en direct depuis les événements, sortie du compilateur avec liens `fichier:ligne`, conseils, bouton **Expliquer** pour les codes `CHxxxx` |
| **Problèmes** | Diagnostics du compilateur et de clangd, regroupés par fichier, disparaissent quand on corrige |
| **Graphe** | Graphe des dépendances entre cibles, **chemin critique** du dernier build mis en évidence |
| **Profil** | Temps par cible, actions les plus lentes, en-têtes les plus coûteux |
| **Git** | État, indexation par fichier et **par bloc**, diff, commit derrière le portail qualité, historique |
| **Appareils** | Android (`adb`) et HarmonyOS (`hdc`) : déploiement, journaux en direct |
| **Débogage** | Points d'arrêt (F9), gdb/lldb-dap, continuer, pas à pas, pile, variables, expressions surveillées |
| **Terminal** | Onglets ; commandes dans l'environnement du projet ; sortie avec liens `fichier:ligne` |
| **Assistant** | IA optionnelle : vous voyez exactement ce qui serait envoyé (secrets masqués) et vous cliquez *Envoyer* ; un correctif est un diff à relire |

Interface en **français et anglais** (suit le navigateur, commutable), thèmes clair/sombre/système. Raccourcis : `Ctrl+Maj+P` palette de commandes, `F7` construire, `F5` lancer/continuer, `Ctrl+F5` déboguer, `F9` point d'arrêt, `F10/F11` pas à pas, `Ctrl+S` enregistrer, `Alt+1…9` panneaux.

### 5.4 Sécurité de Studio

Boucle locale uniquement ; jeton aléatoire par exécution vérifié en temps constant ; contrôle de `Origin` et `Host` (autres sites, *DNS rebinding*) ; CSP stricte (ni script en ligne ni `eval`) ; aucun accès hors du projet ; `.git` jamais écrit.

### 5.5 Limites de Studio, dites franchement

- Éditeur maison (~300 lignes), **pas Monaco** : pas de multi-curseurs, repli, minimap ni rechercher/remplacer. Pour un éditeur complet, utiliser VS Code.
- Terminal **sans pty** : une commande à la fois, pas de programme interactif.
- **Pas d'application de bureau** : `studio-desktop/` (Tauri) est un squelette **jamais compilé** ; aucun installeur.
- Vérifié dans **Edge seulement** (Chromium headless piloté par CDP, 23 tests de bout en bout) ; Firefox et Safari non essayés.
- Pas d'annulation de build ; débogage seulement pour les programmes locaux ; le profil est un classement, pas une frise chronologique.

---

## 6. Les autres composants

### 6.1 `charpente serve` (serveur de build)

Deux transports pour un seul répartiteur : `--stdio` (JSON-RPC 2.0, en-têtes `Content-Length`, pour éditeurs/IDE et `.bsp/charpente.json`) et `--ws` (un message par trame WebSocket, boucle locale, jeton, `Origin`). Méthodes BSP 2.1 (`workspace/buildTargets`, `buildTarget/compile|test|run|sources|cppOptions`…) et méthodes `charpente/*` (workspace, graphe, toolchains, build, compileCommands, check, explain, why, history, subscribe, fichiers, Git, appareils, paquets, options, terminal, LSP, DAP, IA). Il ne demande jamais rien (stdin est le protocole) et ne publie ni ne pousse jamais rien. Détails : `docs/serve.md`. **Non vérifié** : compatibilité avec un client BSP tiers (IntelliJ, Bloop…).

### 6.2 Extension VS Code (`vscode-charpente/`)

Vue des cibles (construire/lancer), panneau Problèmes, barre d'état, tâches `charpente` avec problem matcher, `compile_commands.json` pour clangd, *Expliquer un code*, coloration des `.charpente`, type de débogage `charpente`. Installation depuis les sources : `npm install`, `npm test` (26 tests), `npm run package` → `charpente-0.13.0.vsix`, puis `code --install-extension …` (par vous). **Jamais chargée dans un VS Code réel** ; non publiée sur le Marketplace.

### 6.3 `charpente shell` et `charpente tui`

`shell` ouvre un shell (ou exécute une commande après `--`) avec la chaîne d'outils du projet dans le PATH et `CC`, `CXX`, `AR`, `CHARPENTE_ROOT`… ; `--print-env` pour `eval`. `tui` (Textual) : cibles à gauche, journal du moteur à droite ; touches `b` (construire), `a` (tout), `r` (lancer), `t` (tests), `c` (portail), `l` (recharger), `q`.

### 6.4 Débogage

Charpente n'implémente pas de débogueur : il construit la cible puis pilote **gdb ≥ 14** (`--interpreter=dap`) ou **lldb-dap**. `charpente debug-adapter` transmet les messages DAP tels quels, sauf un `launch` qui nomme une *cible*. Vérifié avec **gdb 17.2** sous Windows/MinGW ; **lldb-dap jamais exécuté** ; pas de débogage distant.

### 6.5 Assistance IA (optionnelle)

Fournisseurs : `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` ou `CHARPENTE_AI_URL` (serveur local compatible OpenAI). Règles : vous voyez ce qui est envoyé *avant* l'envoi ; contexte minimal ; secrets masqués ; rien d'appliqué sans accord, et le correctif est vérifié puis annulé si le build échoue. **Aucun vrai fournisseur n'a été appelé** (fournisseurs factices en test).

---

## 7. Packages, kits, modèles, modules, plateformes

- **Pkg** : `ws.requires("nom")`, recettes TOML (données seulement, jamais exécutées), sommes SHA-256, fichier `charpente.lock`, `vendor`, `mirror`, `audit` (OSV : n'envoie que les URL de paquets et versions), SBOM SPDX/CycloneDX. 31 recettes (dont `charpente-hot`, fournie dans Charpente).
- **Kits** (10) : `kit-core` (fmt, spdlog, nlohmann_json, simdjson, CLI11, doctest), `kit-app`, `kit-graphics`, `kit-game`, `kit-embedded`, `kit-mobile`, `kit-android`, `kit-ohos`, `kit-net`, `kit-xr`.
- **Modèles** (16) : `console`, `bibliotheque`, `app-gui`, `app-android`, `app-harmonyos`, `app-mobile`, `jeu-2d`, `jeu-3d-vulkan`, `vr-openxr`, `web-wasm`, `wasi-plugin`, `plugin-python`, `firmware-stm32`, `firmware-esp32` (non intégré), `linux-embarque-rpi`, `module-charpente`.
- **Modules** : extensions (commandes, contrôles qualité, notificateurs, chaînes d'outils) signées Ed25519, avec capacités gardées ; désactivées tant qu'elles ne sont pas approuvées.
- **Plateformes** (30) : niveau 1 Windows/Linux/macOS x64, macOS arm64, Android, Emscripten ; niveau 2 les architectures croisées, HarmonyOS, iOS, WASI, Cortex-M, AVR ; niveau 3 le reste. Le niveau dit ce que le *projet* vérifie, pas ce que *votre machine* peut faire (`charpente platforms` montre les deux). Sur la machine de développement, beaucoup de builds croisés sont **construits mais pas exécutés** (voir `docs/platforms.md`).

---

## 8. Rapport de développement

### 8.1 Demande et méthode

La seule instruction : *tout développer, ne pas s'arrêter avant d'avoir fini, ne pas faire d'erreur ni de bug, et documenter*, à partir du cahier des charges `PROMPT_CHARPENTE_v1`. Méthode suivie à chaque phase : plan (`docs/plans/phase-N.md`), décisions structurantes en ADR (`docs/adr/`), code avec fonctions pures d'abord, tests automatisés, **vérification réelle** dès qu'un outil réel existait (compilateurs, zig, NDK, émulateur, Edge, gdb, clangd, CMake, Ninja), correction de chaque bug trouvé, CHANGELOG, et énoncé honnête de ce qui n'est pas vérifié.

### 8.2 Chronologie (branche `dev/roadmap`)

| Phase | Contenu | Commit |
|---|---|---|
| Point de départ | v0.1.0 : DSL, chargeur avec confiance, `init/build/run/clean/test/package/ask`, installeurs, diagnostic IA | `293a4aa`…`82ff53c` |
| Audit + P0 | Audit de la v0.1.0, ADR, codes d'erreur `CHxxxx` FR/EN, couche processus unique, CI (ruff, mypy strict, couverture) | `e6768e4`…`54685eb` |
| P1 | Moteur : graphe d'actions, cache par contenu, en-têtes exacts, ordonnanceur parallèle, chemin rapide, `why/history/diff-build/headers/cache/replay` | `46e270a`, `cb124c7` |
| P2 | Système de modules, signatures, hooks, notifications, sorties Rich/GitHub | `8887fde` |
| P3 | DSL v2 (`uses`, recouvrements, options, règles, `charpente.toml`, lint, migrate) ; **Charpente Pkg** | `2b6bfb2`, `7229352` |
| P4a–P4d | Plateformes et niveaux, zig/Emscripten, `toolchain install`, `doctor` ; Android (NDK, APK signé sans Gradle, `deploy`) ; HarmonyOS, firmware, Apple, XR | `7d4f01e`, `f218f93`, `14d6ec4` |
| P5 | Portail qualité, Git/GitHub, versions signées | `14d6ec4` |
| P6 | Kits, kits livrés dans Charpente, 16 modèles | `7cc3ffe` (v0.10.0) |
| P7 | `charpente serve` (BSP 2.1, JSON-RPC, WebSocket), extension VS Code, `shell`, `tui` | `945cc0a` (v0.11.0) |
| P8 | Studio web, débogage DAP, assistance IA | `b9080c3` (v0.12.0) |
| P9 | Budgets, reproductibilité, cache partagé, import CMake, générateurs, rechargement à chaud, `docs`, ressources, déploiement multi-appareils, `setup`, `self uninstall` | `d443c5e`, `2b7d6a7`, `c6d3e5a` (v0.13.0) |

### 8.3 Chiffres (au 26 septembre 2026)

| Mesure | Valeur |
|---|---|
| Fichiers source Python (hors modèles et kits) | 195 (~28 000 lignes) |
| Tests Python | 68 fichiers, ~17 000 lignes ; **1719 tests réussis, 4 ignorés** |
| Tests JavaScript (Studio) / TypeScript (extension) | 33 / 26 réussis |
| Studio (JS, sans étape de build) / extension (TS) | ~3 400 / ~700 lignes |
| Codes d'erreur | 125 (catalogue FR et EN) |
| Schémas d'événements JSON | 51 |
| Plateformes / recettes / kits / modèles | 30 / 31 / 10 / 16 |
| Contrôles statiques | `ruff` propre ; `mypy --strict` : 0 erreur sur 195 fichiers |
| Commits | 33 |

### 8.4 Ce qui a été vérifié pour de vrai

Windows 10, MinGW-w64 : builds et cache, reproductibilité (deux dossiers, octets identiques), budgets, cache partagé (deux dossiers, sorties identiques), reprise d'un build tué en cours de route, rechargement à chaud avec un hôte réel (même PID, trois générations, une modification cassée au milieu). Avec des outils réels : CMake 3.22.1 (import puis build puis exécution ; `CMakeLists.txt` généré configuré, construit et testé), Ninja 1.10.2 (`build.ninja` généré, suivi des en-têtes), clangd 22 et gdb 17.2 (Studio), Edge headless (Studio de bout en bout), zig 0.16 (builds croisés, **sans exécution** sauf WASI), NDK 28.2 et **émulateur x86_64 API 30** (APK signé installé, lancé, journal lu ; `deploy --device all --logs` avec un vrai appareil), SDK OpenHarmony 5.0.0 (construit, non exécuté), Emscripten (construit et exécuté sous Node). Le paquet PyPI se construit, passe `twine check` et s'installe dans un environnement vierge.

### 8.5 Bugs trouvés par ces vérifications (tous corrigés)

Une sélection représentative : un processus enfant capturé héritait de stdin (blocage de `buildTarget/run` sur le protocole) ; un `Content-Length` invalide produisait deux erreurs ; arrêt bloqué d'un serveur jamais démarré ; `clang-cl` choisi comme compilateur Windows par défaut alors qu'inutilisable ; historique vide pour les builds lancés par le serveur, et erreurs de compilation absentes du journal ; coloration de commentaires multi-lignes qui s'arrêtait à la première ligne ; formatage à l'enregistrement qui réécrivait tout en style LLVM ; parseur de diff IA gardant une ligne de contexte fantôme et perdant les espaces de fin ; `verify-reproducible` sans chemin de sortie exploitable ; modification perdue pendant le premier build de `charpente dev` (surveillance créée trop tard) ; sortie de `dev` non vidée en redirection ; un test du moteur qui dépendait de la mémoire libre de la machine ; un budget de taille non mesurable qui passait en silence.

### 8.6 Décisions d'architecture majeures (ADR 0001–0019)

Couche processus unique (0001) ; codes d'erreur i18n (0002) ; hachage BLAKE3 avec repli (0004) ; bus d'événements (0005) ; clés d'action et cache (0006) ; chemin rapide (0007) ; modules et capacités (0008) ; DSL v2 et paquets (0009) ; cœur en Python ou Rust (0010) ; plateformes et compilation croisée (0011) ; Android natif (0012) ; HarmonyOS par délégation (0013) ; embarqué, Apple, XR (0014) ; portail qualité et Git (0015) ; kits et modèles (0016) ; serveur BSP/JSON-RPC (0017) ; pile technique de Studio (0018) ; **reproductibilité, cache partagé, interopérabilité, boucle de développement (0019)**.

### 8.7 Ce qui n'est pas fait (annoncé, non livré)

Exécution distante (REAPI) et exécution hybride ; projet Xcode ; TLS dans le serveur de cache (à mettre derrière un proxy TLS) ; reproductibilité MSVC ; application de bureau Studio compilée et installeurs ; Monaco, terminal à pty ; lldb-dap ; fournisseur IA réel ; iOS/visionOS sans Mac ; vérification sous Linux et macOS ; publication PyPI et Marketplace. Liste vivante : `docs/idees.md`.

---

## 9. Nouveautés de la version 0.13.0

*(Phase P9.)* Détail : `CHANGELOG.md`, `docs/plans/phase-9.md`, ADR 0019.

| Domaine | Nouveauté | Doc |
|---|---|---|
| Fiabilité | **Builds reproductibles** `--reproducible` et `charpente verify-reproducible` | `docs/reproducible-and-budgets.md` |
| Fiabilité | **Budgets** : `ws.budget(build_time, total_size)`, `t.budget(size)` ; un budget dépassé fait échouer le build (CH8024) ; `--no-budget` ; un budget non mesurable est signalé | idem |
| Équipe | **Cache partagé** : `charpente cache serve`, `cache remote`, `CHARPENTE_REMOTE_CACHE` ; jeton, entrées signées HMAC, échec ouvert ; refus des configurations dangereuses (CH8028) ; modèle de menace | `docs/shared-cache.md` |
| Interopérabilité | `charpente import cmake` (via la File API de CMake) | `docs/import-and-generate.md` |
| Interopérabilité | `charpente generate compile-commands\|ninja\|cmake\|vs` (`xcode` non implémenté) | idem |
| Développement | `charpente dev` + **rechargement à chaud** de cibles `Kind.PLUGIN` (`charpente_hot.h`, recette `charpente-hot`) — expérimental | `docs/hot-reload.md` |
| Développement | `charpente docs` : pages d'API Markdown, graphe Mermaid et SVG, option Doxygen | `docs/api-docs.md` |
| Ressources | Surveillance de la mémoire et du disque, `--eco`/`CHARPENTE_ECO` (batterie, chaleur), reprise d'un build interrompu | `docs/resources.md` |
| Appareils | `charpente deploy --device all` : un APK pour toutes les ABI, installation en parallèle, échecs isolés, `--logs` fusionnés et étiquetés | `docs/multi-device.md` |
| Premier lancement | `charpente setup` (guidé, langue mémorisée dans `~/.charpente/settings.json`) | `docs/setup-and-uninstall.md` |
| Désinstallation | `charpente self uninstall` (essai à blanc, clés protégées, liens jamais suivis) | idem |
| Distribution | Paquet PyPI prêt (wheel + sdist, `twine check`) — **non publié** | idem |
| Documentation | Guides complets FR/EN ; page de stabilité par fonction ; ce dossier | `docs/guide.md`, `docs/guide.fr.md`, `docs/stability.md` |
| Erreurs et événements | Codes CH1026, CH8024 à CH8028 ; événements `budget.*`, `resource.*`, `dev.*`, `deploy.device_*`, `deploy.log` | `docs/errors.md`, `docs/events/` |

Corrigé au passage : voir 8.5 (surveillance de `dev`, sortie non vidée, test dépendant de la mémoire, budget non mesurable, `verify-reproducible`).

**Depuis la v0.9/v0.10** (pour situer) : v0.10.0 kits et modèles ; v0.11.0 serveur, extension VS Code, shell, TUI ; v0.12.0 Studio, débogage, IA.

---

## 10. Guide de maintenance

### 10.1 Environnement de développement

```bash
git clone https://github.com/martialaristide/Charpente.git && cd Charpente
pip install -e ".[dev]"            # pytest, ruff, mypy, jsonschema, rich, blake3, textual, build, twine
```

Machine de développement actuelle : Windows 10, Python 3.12 (**seule version utilisée** ; le code déclare 3.9+), MinGW-w64 (MSYS2 `ucrt64`), zig 0.16 et emsdk dans `~/.charpente/toolchains/`, SDK Android + NDK 28.2 + AVD `Pixel_test_api30`, gdb 17.2, clangd/clang-format/clang-tidy 22, Edge, Node. **CMake 3.22.1 et Ninja 1.10.2** ne se trouvent que dans `%LOCALAPPDATA%\Android\Sdk\cmake\3.22.1\bin` : les ajouter au PATH pour ne pas ignorer leurs tests.

### 10.2 Lancer toutes les vérifications

```bash
ruff check .                                          # doit afficher « All checks passed! »
python -m mypy --strict charpente                     # 0 erreur
export PATH="…/Android/Sdk/cmake/3.22.1/bin:$PATH"
python -m pytest -q                                   # ~7 min ; 1719 réussis, 4 ignorés
cd charpente/studio_web && node --test ../../tests/studio_js/*.mjs    # 33 tests
cd vscode-charpente && npm test                       # compile + 26 tests
python tools/gen_error_docs.py && python tools/gen_event_docs.py     # doivent ne rien changer au dépôt
```

Les tests de bout en bout utilisent de vrais compilateurs et sont ignorés automatiquement si l'outil manque. `tests/conftest.py` isole `CHARPENTE_HOME`, fixe la langue en anglais et **fige les mesures de ressources** (sauf `test_resources.py`) : un test ne doit jamais dépendre de la machine.

### 10.3 Carte du dépôt

```
charpente/            code (voir docs/architecture.md pour le détail module par module)
  commands/           un fichier par commande : execute(args) -> int ; _common.py, _session.py partagés
  core/               moteur (process, graph, planner, engine, cache, remote, cache_server…)
  dsl/  pkg/  modules/  serve/  ai/  quality/  vcs/  events/  i18n/  studio_web/  templates_data/  kit_sources/
  builder.py  dev.py  docsgen.py  resources.py  multideploy.py  budgets.py  repro.py  units.py
  onboarding.py  settings.py  selfmanage.py  debug.py  shellenv.py  tui.py
tests/                pytest (test_*.py), tests/studio_js/ (node), tests/browser.py, tests/dap.py
docs/                 pages utilisateur (EN), ADR et plans (FR), events/ et errors.md générés
tools/                gen_error_docs.py, gen_event_docs.py, sync_kit_digests.py
vscode-charpente/     extension (TypeScript)      studio-desktop/   squelette Tauri (non compilé)
bench/  examples/  .github/workflows/  (tests.yml, release.yml)
```

### 10.4 Recettes de maintenance

| Je dois… | Marche à suivre |
|---|---|
| **Ajouter une commande** | Créer `charpente/commands/x.py` avec `execute(args) -> int` (argparse, erreurs par `CommandError("CHxxxx", …)`), l'importer et l'enregistrer dans `commands/__init__.py` (`COMMANDS`), la documenter dans `docs/cli-reference.md`, écrire les tests |
| **Ajouter un code d'erreur** | Ajouter l'entrée (`title`, `message`, `cause`, `fix`) dans **`i18n/en.py` et `i18n/fr.py`** (un test vérifie la parité et les clés), puis `python tools/gen_error_docs.py` |
| **Ajouter un événement** | Le déclarer dans la table de `events/types.py` (champs typés), puis `python tools/gen_event_docs.py` (schémas) ; en test, `CHARPENTE_EVENTS_STRICT=1` refuse un événement mal formé |
| **Ajouter une recette** | `charpente/pkg/recipes/nom-version.toml` (données seulement) ; pour une source livrée (`charpente://…`), placer les fichiers dans `kit_sources/` puis `python tools/sync_kit_digests.py` ; ajouter au kit voulu (`pkg/kits/`) ; tests `test_pkg.py`/`test_kits.py` (idéalement compiler pour de bon) |
| **Ajouter un modèle** | Dossier `templates_data/<nom>/` avec `template.toml` et `files/` ; fichiers cachés stockés `dot_NOM` ; le déclarer dans les tests de `test_templates.py` |
| **Ajouter une plateforme** | `platforms.py` (`_p(nom, os, arch, niveau, triples…)`) ; la chaîne d'outils correspondante ; doc `docs/platforms.md` |
| **Ajouter un panneau Studio** | Fichier dans `studio_web/js/panels/`, méthodes serveur dans `serve/studio.py`, **mêmes clés FR et EN** dans les traductions (un test l'impose), test unitaire node et scénario E2E |
| **Changer le serveur** | Méthode dans `serve/` ; couvrir dans `test_serve.py`/`test_studio_api.py` ; mettre à jour `docs/serve.md` |
| **Modifier une option de compilation** | Uniquement dans `flags.py` (fonctions pures) ; jamais construire une commande ailleurs ; lancer aussi `test_flags.py` |

### 10.5 Règles à ne pas enfreindre

1. **Un processus se lance uniquement par `core/process.py`**, avec une **liste d'arguments** — jamais `shell=True`, jamais de chaîne de commande.
2. **Pas de repli silencieux** : si on ne sait pas faire, erreur `CHxxxx` (et une phrase dans la doc), pas un comportement approximatif.
3. **Secrets** (jetons, phrases secrètes, clés) : environnement ou invite seulement, jamais un fichier, jamais la ligne de commande.
4. **Rien de publié ni de poussé sans demande explicite** (`release --publish`, PyPI, Marketplace).
5. **Aucune licence de fournisseur acceptée à la place de l'utilisateur** (CH8010).
6. **Fonction pure d'abord** (modèle → décision), effets ensuite ; toute règle doit se tester sans machine particulière.
7. **Compatibilité v0.1.0** : un ancien `.charpente` doit continuer à charger (`test_dsl_v2.py`).
8. **Ne jamais marquer une fonction « stable »** sans CI verte sur toutes les plateformes annoncées ; la version reste en `0.x`.
9. Un bug corrigé reçoit **un test qui l'aurait attrapé**, de préférence avec un vrai compilateur.

### 10.6 Publier une version (liste de contrôle)

1. Toutes les vérifications de 10.2 vertes ; `git status` propre.
2. Monter la version **partout** : `charpente/_version.py`, `vscode-charpente/package.json` (+ `package-lock.json` lignes 3 et 9) et `src/client.ts` (chaîne de version), `studio-desktop/src-tauri/Cargo.toml` et `tauri.conf.json`, `docs/vscode.md` (nom du `.vsix`).
3. Écrire l'entrée de `CHANGELOG.md`, la page `docs/plans/phase-N.md`, l'ADR si une décision structurante a été prise ; relancer les générateurs de docs.
4. `python -m build` puis `python -m twine check dist/*` ; essai d'installation dans un venv vierge (`charpente --version`, `init`, `build`, `run`).
5. **Pousser la branche et lire le résultat de la CI** (Windows, Linux, macOS × Python 3.9, 3.12) : c'est la première fois que ce travail y passera.
6. Étiquette Git ; **publication PyPI (`twine upload`) seulement sur décision explicite du mainteneur**.

### 10.7 Pièges connus de cet environnement

- L'outil shell mange les antislashs dans les documents ici (heredocs) : préférer les outils d'édition de fichiers pour tout texte contenant `\n` ou des guillemets.
- `glob("*.charpente")` matche aussi le **dossier** `.charpente/` : filtrer `is_file()`.
- `write_text` sous Windows convertit `\n` en CRLF : écrire des octets quand un test compare du texte.
- Les outils de packaging ignorent les fichiers cachés : `dot_NOM` dans les modèles ; tout fichier de données doit être listé dans `[tool.setuptools.package-data]` (`studio_web/**/*`, `kit_sources/**/*`, `templates_data/**/*`…). `tests/test_packaging.py` le surveille.
- Chromium : `Page.navigate` peut ne jamais répondre quand la page réécrit son URL ; `tests/browser.py` attend `Page.loadEventFired`.
- Un test (`test_editing_a_header_rebuilds_exactly…`) a échoué **une fois** sous forte charge, sans jamais se reproduire.
- Un processus enfant capturé doit avoir `stdin=DEVNULL` (sinon il lit le canal de protocole d'un serveur).
- La machine a ~3,7 Go de mémoire libre : les vrais builds affichent « running 5 job(s) instead of 8 » (comportement voulu).

### 10.8 Dette technique et prochaines étapes suggérées (par priorité)

1. **Pousser `dev/roadmap` et faire tourner la CI** (Windows/Linux/macOS, Python 3.9 et 3.12) : rien de P1 à P9 n'a été exécuté hors de cette machine.
2. Vérifier sur Linux et macOS : sondes de ressources, rechargement à chaud (`dlopen`), builds croisés *exécutés* (QEMU/Wine), chemins `/showIncludes` avec un vrai `cl.exe`.
3. Ouvrir les projets Visual Studio générés ; implémenter Xcode sur un Mac.
4. Essayer `deploy --device all` sur plusieurs vrais appareils ; lldb-dap ; un vrai fournisseur IA ; Studio sous Chrome et Firefox ; l'extension dans un vrai VS Code.
5. Cache partagé : TLS (ou guide de proxy testé), test de charge.
6. REAPI/exécution distante (demande des actions hermétiques : voir ADR 0019).
7. Compiler l'enveloppe Tauri et produire des installeurs ; publier sur PyPI/Marketplace (décisions du mainteneur).
8. Clarifier l'adresse e-mail d'auteur de `pyproject.toml` (`martialaristideb02@…`) face à celle de Git (`martialaristidebarra02@…`).

---

## 11. Variables, fichiers et codes d'erreur

### 11.1 Variables d'environnement

| Variable | Rôle |
|---|---|
| `CHARPENTE_HOME` / `CHARPENTE_CONFIG_DIR` | Dossier de configuration (défaut `~/.charpente`) |
| `CHARPENTE_CACHE_DIR` | Emplacement du cache local |
| `CHARPENTE_LANG` | `en` ou `fr` (l'emporte sur le réglage mémorisé et sur `LANG`) |
| `CHARPENTE_TRUST_ALL=1` | Ne pas demander confirmation avant d'exécuter un `.charpente` (CI de confiance) |
| `CHARPENTE_OFFLINE` | Aucun téléchargement |
| `CHARPENTE_DEBUG=1` | Trace complète en cas d'erreur interne |
| `CHARPENTE_ECO` | `on`, `auto` ou `off` (mode éco) |
| `CHARPENTE_CONSOLE` | `off` : un `charpente` seul affiche l'aide simple ; `plain` : menu sans flèches ni couleurs |
| `CHARPENTE_THEME` | Thème de la bannière et des lignes de build : `bois` (défaut), `neon`, `foret`, `ocean` |
| `CHARPENTE_NO_BANNER=1` | Pas de bannière |
| `CHARPENTE_COLOR` | `auto`, `always`, `never` (`NO_COLOR` l'emporte sur tout ; `FORCE_COLOR` 1/2/3 = 16/256/24 bits) |
| `CHARPENTE_ASCII=1` | Dessin en ASCII seulement |
| `CHARPENTE_SYMBOLS` | `modern` ou `safe` : jeu de symboles (détecté par défaut : `safe` sur une console Windows classique) |
| `CHARPENTE_REMOTE_CACHE`, `_TOKEN`, `_MODE` (`readonly`), `_INSECURE`, `CHARPENTE_CACHE_SIGNING_KEY`, `CHARPENTE_CACHE_RELOCATABLE` | Cache partagé |
| `CHARPENTE_CACHE_SERVER_TOKEN` (ou la variable nommée par `--token-env`) | Jeton du serveur de cache |
| `CHARPENTE_AI_PROVIDER`, `_MODEL`, `_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | IA (optionnelle) |
| `CHARPENTE_KEYSTORE_PASSWORD`, `CHARPENTE_KEY_PASSPHRASE` | Mots de passe de signature (jamais en ligne de commande) |
| `CHARPENTE_EVENTS_STRICT=1` | Refuse un événement mal formé (tests) |
| `CHARPENTE_HASH=blake2` | Force le hachage de la bibliothèque standard (sans `blake3`) |
| `CHARPENTE_LINT=0` | Désactive l'analyse statique automatique du `.charpente` au chargement |
| `CHARPENTE_RECIPES`, `CHARPENTE_PKG_DIR` | Dossier de recettes locales ; dossier de stockage des paquets |

Variables **positionnées par Charpente** dans `shell`/Studio : `CHARPENTE_ROOT`, `_CONFIG`, `_TOOLCHAIN`, `_PLATFORM`, `_SHELL`, `_SESSION`, `_EVENT`.

### 11.2 Fichiers et dossiers

| Chemin | Contenu |
|---|---|
| `NOM.charpente` / `charpente.toml` | Le projet |
| `charpente.lock` | Versions et empreintes des paquets (à valider dans Git) |
| `.charpente/` (dans le projet) | Options (`options.toml`), modèles locaux, hooks, état |
| `build/<Config>[-plateforme][-variante]/` | Sorties de build ; `build/compile_commands.json` ; `build/hot/` (rechargement à chaud) |
| `build/.charpente/events/` | Journaux de session (les 20 derniers) |
| `~/.charpente/cache`, `toolchains/`, `pkg/`, `modules/`, `android/`, `keys/`, `cache-server/` | Données utilisateur (`charpente self uninstall` les connaît toutes) |
| `~/.charpente/trusted_files.json`, `trusted_keys.json`, `settings.json`, `toolid.json` | Confiance, préférences, identités d'outils |

### 11.3 Codes d'erreur

Format `CHxxxx` (aucun code n'est réutilisé avec un autre sens). Familles : `1xxx` DSL et fichier de projet, `2xxx` compilateur et système hôte, `3xxx` planification et compilation, `4xxx` usage de la ligne de commande, `5xxx` IA, `6xxx` paquets, `7xxx` versions et modules, `8xxx` outils, plateformes, serveur, Studio, P9, `9xxx` interne. `charpente explain CHxxxx --lang fr` donne cause et remède ; liste complète : `docs/errors.md` (générée). Codes P9 : **CH1026** budget invalide · **CH8024** budget dépassé · **CH8025** contrôle de reproductibilité impossible · **CH8026** import échoué · **CH8027** génération échouée · **CH8028** cache partagé inutilisable.

---

## 12. État de vérification et limites

**Niveaux utilisés** : *Vérifié* = tests automatisés *et* essai réel avec un vrai outil, sur la machine de développement ; *Testé* = tests automatisés seulement (outil simulé, réponse enregistrée, fichier généré jamais ouvert par le vrai programme) ; *Expérimental* = fonctionne dans les cas décrits, peut changer ; *Squelette* = fichiers jamais construits ; *Non fait*.

**Version 0.13 = alpha.** Rien n'est déclaré « stable » : le workflow de CI (`.github/workflows/tests.yml`) existe pour Windows, Linux et macOS × Python 3.9 et 3.12, mais **il n'a jamais tourné sur ce travail**, qui n'a pas été poussé ; tout a été vérifié à la main sur **une seule machine Windows, avec Python 3.12**. Rien n'a tourné sous Linux ni macOS.

| Fonction | Niveau |
|---|---|
| Moteur, cache, `why`/`history`/`replay`, événements | Vérifié |
| Builds reproductibles, budgets | Vérifié (MinGW ; MSVC refusé) |
| Ressources, éco, reprise | Vérifié sous Windows |
| Cache partagé | Vérifié en HTTP sur la boucle locale ; pas de TLS ; `https://` non essayé |
| REAPI / exécution hybride / Xcode | **Non fait** |
| `import cmake`, `generate compile-commands\|ninja\|cmake` | Vérifié (CMake 3.22.1, Ninja 1.10.2, clangd 22) |
| `generate vs` | Testé (jamais ouvert dans Visual Studio) |
| `dev` et rechargement à chaud | Expérimental, vérifié sous Windows |
| `docs` | Testé (balayeur de texte, pas un analyseur C++) |
| `deploy` | Vérifié sur un vrai émulateur x86_64 ; `--device all` : vérifié avec un vrai appareil, **simulé** pour plusieurs |
| Studio, LSP (clangd), DAP (gdb) | Vérifié (Edge seulement) ; lldb-dap jamais exécuté |
| Application de bureau Studio (Tauri) | **Squelette** |
| Extension VS Code | Testé (faux module `vscode`) ; jamais chargée dans un VS Code réel |
| IA (`fix`, `ai tests`, `ai migrate`) | Testé avec un fournisseur factice ; **aucun fournisseur réel appelé** |
| Builds croisés (zig, NDK, OpenHarmony, firmware) | Construits ; en général **non exécutés** (WASI, Emscripten, Android x86_64 : exécutés) |
| Paquet PyPI | Construit et vérifié, **non publié** |

**Pour atteindre une 1.0** : CI verte sur les trois systèmes et les deux versions de Python ; les lignes « non exécuté » de `docs/platforms.md` exécutées ; les lignes *Testé* passées à *Vérifié* ; Studio essayé dans Chrome et Firefox ; une utilisation par quelqu'un d'autre que l'auteur, sur d'autres projets.

---

*Pages de référence citées :* `docs/guide.md`, `docs/guide.fr.md`, `docs/cli-reference.md`, `docs/dsl-reference.md`, `docs/architecture.md`, `docs/security.md`, `docs/stability.md`, `docs/shared-cache.md`, `docs/reproducible-and-budgets.md`, `docs/import-and-generate.md`, `docs/hot-reload.md`, `docs/api-docs.md`, `docs/resources.md`, `docs/multi-device.md`, `docs/setup-and-uninstall.md`, `docs/studio.md`, `docs/serve.md`, `docs/vscode.md`, `docs/terminal.md`, `docs/debugging.md`, `docs/ai.md`, `docs/platforms.md`, `docs/android.md`, `docs/packages.md`, `docs/kits.md`, `docs/templates.md`, `docs/quality.md`, `docs/git.md`, `docs/errors.md`, `docs/events/`, `docs/adr/`, `docs/plans/`, `CHANGELOG.md`.
