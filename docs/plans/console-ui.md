# Plan — nouvelle identité visuelle de la console (bannière et lignes de build)

Statut : **réalisé** (décisions prises : police du cahier des charges ; style des lignes pour build/dev/deploy + bannière partout ; grande bannière au premier écran du menu ; correctif Linux à part). Voir l'ADR 0020 et `docs/console.md`. Le §8 et le §9 sont conservés tels que proposés. Cahier des charges : `PROMPT_CLAUDE_CODE_console_charpente.md` + capture de référence.

## 1. Mesures de référence (avant tout changement, dépôt propre au commit `a958352`)

| Contrôle | Résultat |
|---|---|
| `ruff check .` | propre |
| `python -m mypy --strict charpente` (plateforme de la machine : Windows) | 0 erreur, 202 fichiers |
| **`python -m mypy --strict --platform linux charpente`** | **1 erreur déjà présente** : `charpente/resources.py:90 Module has no attribute "windll"`. La CI (job `lint`, Ubuntu) échouerait. **Non corrigée ici** (règle : on signale, on ne mélange pas). Correctif proposé à part, d'une ligne, avec votre accord. |
| `pytest` (suite complète, cmake/ninja dans le PATH) | **1822 réussis, 4 ignorés, 0 échec** (6 min 43) — obtenu *après* la correction du §1.1 ; avant elle, la suite se bloquait |
| Tests Node de Studio | 33 réussis |
| Tests de l'extension VS Code | 26 réussis |
| Sorties de référence `plain` / `jsonl` | enregistrées (build à froid, à chaud, `-v`, `test`, build en échec), brutes et normalisées, dans le dossier de travail de la session |

### 1.1 Un problème préexistant trouvé pendant ces mesures (corrigé, à part)

Mes tests de pseudo-terminal Windows (`tests/test_console_pty.py`, ajoutés avec le menu console) créaient un ConPTY **dans le processus de pytest** ; cela faisait ensuite se bloquer un processus `node` d'un autre test (`test_the_wasi_template_builds_and_runs_under_node`), donc la suite complète ne se terminait plus. Correction : les scénarios tournent maintenant dans un processus séparé (`tests/pty_scenarios.py`). C'est une correction de tests, sans aucun changement de code produit ; elle fera l'objet de son propre commit, **avant** le travail d'affichage.

## 2. Ce qui existe déjà (à réutiliser, pas à dupliquer)

- **Rendu du build** : `charpente/output/` — `plain.py` (`PlainRenderer`), `rich_renderer.py` (`--output rich`, barre `rich` transitoire), `jsonl.py`, `github.py`. Ils sont des **abonnés du bus d'événements**, attachés par `commands/_session.py` (`Session`).
- **Choix du mode** (`Session.__init__`) : `auto` = `rich` si terminal interactif + `rich` installé + pas `CI`/`NO_COLOR`/`TERM=dumb`, sinon `plain`.
- **Lignes par cible** (`[ok]`, `[up to date]`, `[FAILED]`, `Done in …`) : **imprimées par la commande `build`** (`print_result_lines`, aussi utilisée par `dev`), *pas* par un renderer, exactement comme en v0.1.0. `session.say("Building …")` imprime la ligne d'en-tête.
- **Événements disponibles** : `session.started` (commande, version, config), `workspace.loaded`, `graph.analyzed`, `target.started/finished/up_to_date/failed`, `action.started/finished/cache_hit/up_to_date/failed`, `diagnostic.emitted` (sévérité, fichier, ligne), `hint.emitted`, `session.finished` (ok, durée). Le chemin de sortie n'est **pas** dans `target.finished` (il faut le lire dans `action.finished.outputs`).
- **Commandes qui ont `--output`** : `build`, `dev`, `deploy` seulement. `run`, `test` et `package` n'ont pas cette option : elles affichent toujours en `plain`.
- **Langue** : `i18n.current_lang()` (`CHARPENTE_LANG`, puis `settings.json`, puis `LANG`) ; le catalogue `i18n/` ne contient que les erreurs `CHxxxx`.
- **Déjà écrit pour le menu console** (`charpente/console/`, commit `100c3dc`) : détection des capacités (`term.detect`), activation VT Windows par `ctypes` (`enable_windows_vt`), `Style`, `box`, `clip`, `visible_len`, lecture des touches. Une classe `Style` y existe déjà (deux méthodes de couleur sémantiques) ; celle du cahier des charges est plus riche (profondeur de couleur, 24 bits).
- **Aucun test existant ne couvre l'affichage interactif** : les tests d'affichage passent par des flux non-terminal (`plain`).

## 3. Architecture proposée

```
charpente/ui/                 (nouveau, Python pur, aucune dépendance)
  term.py     capacités : fonction PURE detect(env, flux) -> Caps (couleur none|16|256|truecolor, unicode, largeur, tty, ci) ;
              activation VT Windows (ctypes, sans processus) ; conversions RGB -> 256 -> 16
  banner.py   police 6 lignes (C H A R P E N T E) ; 4 thèmes ; render_banner(caps, theme, lang, version) PUR -> str ;
              should_show_banner(...) PUR ; print_banner() (une fois par processus)
  style.py    classe Style : une méthode par type de ligne (étape, contexte, cible ok/cache/échec, avertissement,
              barre de progression, encadré de résultat) ; PURE : (données, caps) -> str ; repli ASCII
  render.py   StyledRenderer : abonné au bus (session.started, workspace.loaded, target.*, diagnostic.emitted, action.*,
              session.finished) qui imprime ces lignes ; c'est le SEUL endroit qui écrit à l'écran
  __main__.py python -m charpente.ui --theme T --lang fr|en : démonstration (bannière + session fictive)
charpente/i18n/ui.py          textes FR/EN de l'interface (mêmes clés dans les deux langues, test de parité)
```

### Points d'accroche (le moins de fichiers modifiés possible)

| Fichier existant | Modification prévue | Risque |
|---|---|---|
| `commands/_session.py` | `auto` sur terminal interactif → `StyledRenderer` (au lieu de `rich`) ; nouvel attribut `Session.fancy` ; le contexte (plateforme, chaîne d'outils) est passé au renderer **directement**, pas par de nouveaux champs d'événements (les événements et le jsonl ne changent pas) | moyen : c'est ici que le mode est choisi |
| `commands/build.py` (`print_result_lines`, en-tête `say`) | en mode `fancy` : ne pas imprimer les lignes `[ok]`/`Done in` (le renderer les a déjà montrées) ; conserver le diagnostic IA et « Build interrupted » | moyen : `dev.py` partage cette fonction |
| `cli.py` | un seul crochet avant `command(rest)` : bannière pour les commandes de la liste (`init`, `setup`, `studio`, `test`, `run`, `package`…) qui n'ont pas de renderer ; un drapeau « déjà affichée » évite le doublon | faible |
| `console/term.py` | remplacer sa copie de `enable_windows_vt` par un import de `ui/term.py` (dédoublonnage, 3 lignes) | faible (couvert par les 96 tests du menu) |
| `pyproject.toml`, docs | données de paquet si besoin ; `docs/console.md`, guides, CHANGELOG, tableau des variables | nul |

**Non modifiés** : moteur, cache, planificateur, paquets, bus (aucun nouvel événement, aucun champ ajouté), `PlainRenderer`, `JsonlStream`, `github.py`, `rich_renderer.py` (`--output rich` reste tel quel).

### Comportement

- **Quand la bannière s'affiche** : une fois par processus, terminal interactif, mode `auto`, hors CI (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `BUILDKITE`, `TF_BUILD`, `JENKINS_URL`, `TEAMCITY_VERSION`), sans `CHARPENTE_NO_BANNER=1`, jamais pour `--version`, `explain`, `serve`, `debug-adapter`, `shell --print-env`, ni en `plain`/`jsonl`.
- **Adaptation** : logo complet si la largeur le permet (marge intérieure 3, 2, 1, 0 essayée dans l'ordre) ; sinon cadre compact `C H A R P E N T E` ; sans Unicode ou `CHARPENTE_ASCII=1` : cadre `+ = |` ; sans couleur (`NO_COLOR`, `CHARPENTE_COLOR=never`, `TERM=dumb`) : aucune séquence ; 24 bits / 256 / 16 couleurs selon `COLORTERM`, `TERM`, `WT_SESSION`, VS Code, iTerm, VT Windows ; `FORCE_COLOR` / `CHARPENTE_COLOR=always` forcent.
- **Thèmes** : `bois` (défaut), `neon`, `foret`, `ocean` par `CHARPENTE_THEME`.
- **Garantie d'affichage** : toute erreur d'affichage (flux fermé, encodage inconnu, largeur nulle) dégrade le rendu (compact, ASCII, sans couleur) et ne fait jamais échouer un build.

## 4. Non-régression `plain` / `jsonl`

1. **Références réelles** (déjà enregistrées, brutes + normalisées) : à recomparer après le travail ; les durées, identifiants et chemins temporaires sont masqués, tout le reste doit être **identique octet pour octet**.
2. **Tests portables** (ajoutés au dépôt) : le même scénario de build rejoué **dans le processus** avec un compilateur factice (celui de `test_builder`), sortie `plain` et `jsonl` capturée puis comparée à des fichiers de référence normalisés. Cela ne dépend ni du compilateur, ni du système, donc tourne aussi sur la CI Linux/macOS.
3. Ces références sont figées **avant** de toucher au code d'affichage ; le test doit passer avant et après.

## 5. Tests prévus

Ceux du cahier des charges : glyphes rectangulaires (6 lignes de même largeur) ; toutes les lignes de la bannière de même largeur visible (séquences ANSI retirées) pour chaque thème et chaque profondeur ; 80 colonnes = logo complet, plus étroit = compact sans dépassement ; sans couleur aucun `\x1b` ; ASCII sans caractère de dessin ; `should_show_banner` faux pour `plain`, `jsonl`, tube, CI, `CHARPENTE_NO_BANNER` ; `print_banner` muet dans un tube sauf forcé ; détection (`NO_COLOR` l'emporte, `FORCE_COLOR`, `TERM=dumb`, `xterm-256color`, `COLORTERM=truecolor`, Windows sans VT) ; conversions (rouge pur → 196, noir → 16, gris → rampe 232–255) ; `Style` (encadré rectangulaire, barre bornée, repli ASCII). Ajouts : cas limites (flux fermé, encodage inconnu, largeur 0/1/absurde, variable vide), parité FR/EN des textes, `StyledRenderer` rejoué sur les événements de référence (réussite, cache, avertissement, échec, interruption), et un test qui prouve qu'**aucun** octet n'est écrit en `plain`/`jsonl`.

## 6. Vérification réelle prévue

Suite complète (chiffres avant/après) ; `ruff` ; `mypy --strict` en `--platform win32` **et** `--platform linux` ; `python -m charpente.ui` et un vrai `charpente build` dans un pseudo-terminal Windows (ConPTY) aux largeurs 100 et < 79, avec `NO_COLOR=1`, redirigé vers un fichier, et sur une console `cmd`/PowerShell/Windows Terminal réelle **si** je peux les piloter et les capturer ici. **Non vérifiable ici** : Linux, macOS, anciennes consoles Windows sans VT — dit clairement dans le rapport final.

## 7. Risques

| Risque | Parade |
|---|---|
| Doublon d'affichage (renderer + lignes imprimées par la commande) | `Session.fancy` ; test qui compte les lignes de cible |
| Interférence barre de progression / autres écritures (avertissements du compilateur, conseils) | le renderer possède la ligne de progression : efface, imprime, redessine ; il traite lui-même `action.output` et `hint.emitted` |
| Événements émis depuis plusieurs threads | le bus les livre à un abonné sur son propre fil, dans l'ordre ; un verrou protège l'écriture |
| Largeur du logo (≈ 77 colonnes de dessin) | marge essayée de 3 à 0 ; mesuré, testé à 60, 79, 80, 100 |
| Changement visible pour les utilisateurs de `rich` en mode `auto` | assumé (`--output rich` reste disponible) ; documenté |
| Confusion `Style` (menu) / `Style` (nouveau) | espaces de noms distincts ; dédoublonnage progressif, documenté |

## 8. Décisions à prendre (voir les questions posées avec ce plan)

1. Police : suivre l'**art ASCII du cahier des charges** (« ANSI Shadow » : pleins `█` + ombre en filets), la capture montre un rendu en pixels avec ombre décalée ; je juge le rendu à la fin par rapport à la capture.
2. Portée du style « lignes de build » : `build`, `dev`, `deploy` (qui ont `--output auto`) ; `run`, `test`, `package` n'affichent que la bannière (leurs lignes restent inchangées).
3. Menu (`charpente` seul) : grande bannière au premier écran seulement (si la fenêtre est assez haute), ligne compacte ensuite.
4. Corriger à part l'erreur `mypy --platform linux` préexistante (`resources.py`).
5. Ajouter au dépôt les sorties de référence portables (§4.2) : oui, en tests.

## 9. Ordre de travail (petits commits)

1. `test:` isoler le ConPTY (fait, en attente de commit) · 2. `test:` références `plain`/`jsonl` portables (avant tout code d'affichage) · 3. `feat(ui):` `term.py` + tests · 4. `feat(ui):` `banner.py` + polices + thèmes + tests · 5. `feat(ui):` `style.py` + `i18n/ui.py` + tests · 6. `feat(ui):` `render.py`, `Session`, `build.py`, `cli.py` + tests de non-régression · 7. `feat(ui):` `python -m charpente.ui` · 8. `docs:` console.md, guides, CHANGELOG, variables · 9. vérification réelle et rapport.
