# Charpente : le guide complet

*English: [guide.md](guide.md).* Chaque page liée va plus loin ; [stability.md](stability.md) (en anglais) dit ce qui est vérifié et ce qui ne l'est pas.

## 1. Ce qu'est Charpente

Vous décrivez votre projet C/C++ dans un fichier `.charpente` (syntaxe Python, mais c'est une *description* : inutile de connaître Python pour le lire). Charpente le construit sous Windows, Linux et macOS, pour ces
systèmes comme pour Android, HarmonyOS, le web (WebAssembly), les microcontrôleurs et d'autres. Quatre parties :

* **Moteur** — builds incrémentaux exacts, cache adressé par le contenu (local et partageable), builds reproductibles, flux d'événements pour les outils.
* **Pkg** — paquets et **kits** de bibliothèques choisies (`ws.requires("fmt")`), avec sommes de contrôle.
* **Kits et modèles** — squelettes de projet prêts à l'emploi (`charpente init NOM --template ...`).
* **Studio** — une application web locale, une extension VS Code, un serveur de build (`charpente serve`), une interface de débogage.

## 2. Installation et premier lancement

```bash
pip install -e .                 # depuis un clone (la publication sur PyPI n'a pas eu lieu)
charpente setup                  # examine la machine ; propose d'installer un compilateur (zig) s'il n'y en a pas
charpente doctor                 # ce que cette machine sait construire, et ce qui manque
```

Voir [setup-and-uninstall.md](setup-and-uninstall.md). Charpente demande avant chaque téléchargement et n'accepte jamais une licence à votre place. Pour des messages en français : `charpente setup --lang fr`
(ou la variable `CHARPENTE_LANG=fr`, qui l'emporte toujours).

## 3. Votre premier projet

```bash
charpente init hello --template console
cd hello
charpente build
charpente run --target hello -- Ada        # Hello, Ada!
charpente test
```

La première fois que Charpente rencontre un fichier `.charpente`, il demande si vous lui faites confiance, car c'est du code qui s'exécute sur votre machine ([security.md](security.md)). `charpente init --list`
montre les 16 modèles ([templates.md](templates.md)). Le fichier est court :

```python
from charpente import *

with Workspace("hello") as ws:
    ws.configurations(["Debug", "Release"])
    with Target("hello") as t:
        t.kind(Kind.EXECUTABLE)
        t.standard("c++17")
        t.sources(["src/*.cpp"])
```

Tout ce qu'on peut y écrire est dans [dsl-reference.md](dsl-reference.md) ; un pas-à-pas est dans [tutorial.md](tutorial.md).

## 4. Au quotidien

| Je veux... | Commande |
|---|---|
| construire / construire en Release | `charpente build` / `charpente build --config Release` |
| voir pourquoi quelque chose a été recompilé | `charpente build -v`, `charpente why FICHIER` |
| reconstruire à chaque enregistrement | `charpente dev` ([hot-reload.md](hot-reload.md)) |
| lancer / tester | `charpente run`, `charpente test` |
| comprendre une erreur | `charpente explain CH1009` (en français ou en anglais) |
| repérer les en-têtes coûteux | `charpente headers` |
| comparer avec le build précédent | `charpente history`, `charpente diff-build` |
| nettoyer | `charpente clean` |

Les reconstructions sont exactes : modifier un en-tête recompile précisément les fichiers qui l'incluent, décidé d'après le *contenu* des fichiers, jamais les horodatages.

## 5. Dépendances

`ws.requires("fmt")` dans le fichier, puis `charpente pkg install` ; `charpente kit list|add` pour des ensembles choisis (graphisme, jeu, réseau, embarqué, mobile...). Les paquets sont vérifiés par empreinte
SHA-256 et peuvent produire un SBOM. Voir [packages.md](packages.md), [kits.md](kits.md).

## 6. Autres plateformes

```bash
charpente toolchain install zig
charpente build --platform linux-arm64
charpente platforms                  # chaque plateforme, son niveau de support, et si cette machine peut la construire
```

Android : `charpente package --format apk`, `charpente deploy` (un appareil) ou `charpente deploy --device all --logs` ([android.md](android.md), [multi-device.md](multi-device.md)).
Voir aussi [HarmonyOS](harmonyos.md), [embarqué](embedded.md), [Apple et XR](apple.md), [plateformes](platforms.md). Beaucoup de builds croisés sont *construits* mais pas *exécutés* ici ; les tableaux le disent.

## 7. Vitesse, et travail à plusieurs

* Le **cache local** rend rapides un retour en arrière ou un clone neuf. `charpente cache stats`.
* Un **cache partagé** permet à une équipe ou à la CI de réutiliser le travail des autres : [shared-cache.md](shared-cache.md) (avec son modèle de menace).
* Les **builds reproductibles** (`--reproducible`, `charpente verify-reproducible`) et les **budgets** (`ws.budget(...)`) rendent les résultats dignes de confiance : [reproducible-and-budgets.md](reproducible-and-budgets.md).
* Sur une petite machine ou sur batterie : la mémoire et le disque sont surveillés, et `--eco` construit doucement : [resources.md](resources.md).

## 8. Qualité, Git, versions

`charpente check` lance le portail qualité (format, avertissements, secrets, tests, sanitizers, couverture, licences, SBOM) ; `charpente hooks install`, `commit`, `push`, `pr` le placent devant Git ;
`charpente ci init` et `charpente release` préparent la CI et des versions signées (rien n'est publié sans `--publish`). Voir [quality.md](quality.md) et [git.md](git.md).

## 9. Éditeurs et Studio

* `charpente studio` — le projet dans votre navigateur : fichiers, cibles, éditeur avec clangd, builds, profil, Git, appareils, débogage ([studio.md](studio.md), [debugging.md](debugging.md)).
* VS Code : l'extension `vscode-charpente/` ([vscode.md](vscode.md)). N'importe quel éditeur : `charpente serve` parle BSP/JSON-RPC ([serve.md](serve.md)), et `charpente generate compile-commands` alimente clangd.
* Terminal : `charpente shell` (la chaîne d'outils du projet dans le PATH), `charpente tui` ([terminal.md](terminal.md)).
* L'aide de l'IA est optionnelle et montre d'abord ce qu'elle enverrait : `charpente fix`, `charpente ai ...` ([ai.md](ai.md)).

## 10. Venir d'ailleurs, ou aller ailleurs

`charpente import cmake` écrit un `.charpente` à partir d'un projet CMake ; `charpente generate ninja|cmake|vs|compile-commands` écrit des fichiers de projet pour d'autres outils
([import-and-generate.md](import-and-generate.md)). `charpente docs` écrit la documentation de l'API à partir des commentaires de vos en-têtes ([api-docs.md](api-docs.md)).

## 11. Quand quelque chose ne va pas

Chaque erreur porte un code : `charpente explain CHxxxx` donne la cause et le remède dans votre langue ([errors.md](errors.md)). Les situations courantes sont dans [troubleshooting.md](troubleshooting.md).
D'abord `charpente doctor`, puis `charpente build -v`. Pour retirer tout ce que Charpente a stocké : `charpente self uninstall` (il montre d'abord ce qu'il retirerait ; rien n'est supprimé sans `--yes`, et les clés de signature
de versions ne le sont jamais sans `--keys`).

## 12. Limites, honnêtement

La version 0.13 est en alpha. Elle a été vérifiée sur une seule machine Windows ; Linux et macOS n'ont jamais été essayés, et le workflow de CI n'a jamais tourné sur ce travail (rien n'a été poussé ; seul Python 3.12 a été utilisé). L'exécution distante et les projets Xcode ne sont pas faits ;
une application de bureau pour Studio n'existe que sous forme de squelette non compilé. La liste complète est dans [stability.md](stability.md).
