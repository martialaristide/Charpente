# ADR 0020 — Le style de la console : bannière, lignes de build, et ce qui ne change pas

- **Statut** : accepté

## Contexte

La console de Charpente affichait du texte simple (`[ok]`, `Done in …`) ou, avec `rich` installé, une barre de progression. On veut une identité visuelle (bannière en blocs avec ombre, lignes de build colorées, encadré de résultat) **sans rien changer pour les programmes** qui lisent la sortie (`--output plain`, `--output jsonl`, sortie redirigée, CI), sans nouvelle dépendance, et sans qu'un problème d'affichage puisse faire échouer un build.

## Décisions

1. **Un paquet `charpente/ui/`, sans dépendance.** `term.py` (capacités du terminal : fonction *pure* `detect`, conversion 24 bits → 256 → 16 couleurs, mesure du texte), `banner.py` (police, thèmes, `render_banner` et `should_show_banner` purs, `print_banner`), `style.py` (une méthode par type de ligne, pure), `render.py` (le seul composant qui écrit), `demo.py` (`python -m charpente.ui`). Les fonctions de mise en forme prennent des données et des capacités et rendent une chaîne : elles se testent sans terminal.
2. **Le rendu est un abonné du bus d'événements.** `StyledRenderer` s'abonne comme `PlainRenderer` ; le moteur, le bus et les événements ne changent pas (aucun champ ajouté : les schémas JSON et la sortie `jsonl` restent identiques). Ce que le bus ne dit pas (plateforme, chaîne d'outils) est passé au renderer par `Session`.
3. **`auto` sur un terminal = le rendu stylé ; `rich` n'est plus le défaut de `auto`.** `--output rich` reste disponible et inchangé. `-v` garde la sortie simple détaillée. `plain` et `jsonl` sont inchangés octet pour octet : c'est verrouillé par des tests qui rejouent une session complète (compilateur factice, processus séparé, `PYTHONHASHSEED=0`) et la comparent à des références enregistrées **avant** le travail (`tests/golden/output/`).
4. **La bannière est affichée par `cli.main`**, une fois par processus, pour une liste blanche de commandes, seulement sur un terminal, jamais en CI, en `plain`/`jsonl`, avec `--help` ou `--json`. C'est un crochet unique plutôt qu'un appel dans chaque commande (plusieurs commandes n'ont pas de `Session`). Le menu console affiche la grande bannière à son premier écran si la fenêtre est assez haute, sinon sa ligne de titre.
5. **Le renderer ne fait jamais échouer un build.** Flux fermé, encodage incapable d'écrire un caractère, tube cassé, largeur de 0 ou de 10 000 colonnes, bug de mise en forme : l'affichage se dégrade (compact, ASCII, sans couleur) ou s'arrête, le build continue.
6. **La barre de progression est transitoire** et n'utilise que `\r` et des espaces (aucune séquence d'échappement), donc elle fonctionne aussi avec `NO_COLOR`. Une colonne est toujours laissée libre : écrire dans la dernière colonne fait passer à la ligne trop tôt certaines consoles Windows.
7. **Trois jeux de symboles**, choisis par les capacités : moderne (`✔ ✘ ◆ ▸ ━ ╭`), *sûr* (`√ × ♦ ► ▬ ┌`, présents dans la police par défaut des consoles Windows classiques), ASCII (`[ok] [x] [=] > = +`). Le jeu sûr n'était pas prévu : il a été ajouté après avoir **regardé une vraie fenêtre `cmd.exe`**, où `✔ ✘ ◆` s'affichaient comme des carrés vides. `CHARPENTE_SYMBOLS` permet de forcer l'un ou l'autre.
8. **Les textes sont dans `i18n/ui.py`** (mêmes clés et mêmes `{paramètres}` en français et en anglais, testé), séparés du catalogue d'erreurs `CHxxxx`. Un mot inconnu ou un paramètre manquant s'affiche tel quel au lieu de lever une exception.

## Écarts assumés par rapport à la maquette

- Une cible **à jour** affiche « à jour » (et non « à jour, servi par le cache ») : ce n'est pas toujours le cache qui l'a fournie ; « servi par le cache » est réservé aux cibles dont toutes les actions viennent du cache.
- Le chemin de sortie n'est affiché que s'il est connu par les événements (un lien « à jour » n'en émet pas) : on préfère ne rien afficher qu'un chemin trompeur.
- Le logo complet demande 80 colonnes (cadre de 79 avec la marge 1) ; la maquette de 83 colonnes (marge 3) demande 84 colonnes.

## Conséquences

- Nouvelles variables : `CHARPENTE_THEME`, `CHARPENTE_NO_BANNER`, `CHARPENTE_COLOR`, `CHARPENTE_ASCII`, `CHARPENTE_SYMBOLS` (et respect de `NO_COLOR` et `FORCE_COLOR`).
- Vérifié dans de vraies fenêtres `cmd.exe` et Windows PowerShell 5.1. **Non vérifié** : Windows Terminal, PowerShell 7, Linux, macOS (la CI n'a pas encore tourné sur ce travail).
