# ADR 0010 — Cœur en Python ou en Rust ? (décision sur mesures)

- **Statut** : accepté (P1) — le cœur reste en Python ; réexamen prévu (voir « Ce qui reste »)
- **Critère du cahier des charges** : « no-op build < 300 ms sur 10 000 fichiers, sinon ADR +
  cœur Rust (PyO3/maturin) avec repli Python ».

## Mesures

Banc `bench/noop_build.py --files 10000` : 10 000 sources, 200 en-têtes, 8 tâches, compilateur
factice en processus (donc on mesure Charpente, pas gcc). Machine : Windows 10, Python 3.12,
disque dont l'ouverture d'un fichier coûte ~1 ms (antivirus temps réel) et `os.stat` ~48 µs.

| Scénario | Premier moteur | Après optimisations (ADR 0007) |
|---|---:|---:|
| Build complet (10 001 actions) | 102,7 s | 104,4 s (dominé par ~12 ouvertures de fichiers par action, ~1 ms chacune ici) |
| **Build sans changement (no-op)** | **18,7 s** | **0,24 s (242 ms meilleur, 258 ms médian)** ✔ |
| Une source modifiée (1 compilation + édition de liens) | — | 6,2 s |
| Un en-tête modifié (99 compilations + édition de liens) | — | 7,0 s |

## Décision

Le critère chiffré est **atteint en Python** : 242 ms < 300 ms. Un cœur Rust n'est donc pas
requis par le critère, et — c'est décisif — **aucune toolchain Rust n'est installée dans
l'environnement où ce code est développé et vérifié** : livrer un module natif serait livrer du
code invérifié. On garde le cœur en Python, avec une API (`core.graph`, `core.cache`,
`core.hashing`, `core.statcache`) écrite pour qu'une implémentation native puisse la remplacer
derrière les mêmes tests.

## Ce que le gain doit — et ne doit pas — à Python

- Le gain 18,7 s → 0,24 s vient d'un **changement d'algorithme** (empreinte des métadonnées,
  listages de dossiers, plus de `pathlib` sur le chemin chaud), pas d'un changement de langage.
- Un cœur Rust n'aurait pas réduit le coût des appels système ; il aurait réduit le coût de
  construction des objets Python, qu'on a évité autrement.

## Limites honnêtes (à ne pas cacher)

1. **Le build incrémental d'un gros projet reste lent : 6–7 s pour 10 000 fichiers.** Dès qu'un
   fichier change, le chemin rapide abandonne et le moteur complet replanifie et réévalue
   *toutes* les actions (≈ 3 s de planification + ≈ 3 s de vérification de fraîcheur). C'est le
   vrai point faible actuel ; Ninja fait cela en quelques centaines de ms.
2. Le build complet est limité ici par le système de fichiers de la machine de test, pas par le moteur.
3. Ces chiffres sont d'une seule machine. Sous Linux, `os.stat` coûte ~1 µs : la CI ajoutera la
   mesure Linux/macOS (le banc est un script autonome).

## Ce qui reste (piste, pas engagement)

- Un chemin rapide **incrémental** : la comparaison du stamp fournit déjà la liste des fichiers
  modifiés ; il suffirait de n'évaluer que les actions qui les touchent (index inverse
  fichier → actions, gardé dans le stamp). Objectif : incrémental ≈ no-op + coût des actions
  réellement exécutées. À faire avant d'envisager Rust.
- Si, après cela, une mesure sur un dépôt réel (P9 : moteur C++/Vulkan) montre encore un écart,
  le graphe, le hachage et l'ordonnanceur passeront en Rust (PyO3/maturin, repli Python testé par
  les mêmes tests) et cet ADR sera remplacé.
