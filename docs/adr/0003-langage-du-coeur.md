# ADR 0003 — Langage du cœur : Python d'abord, Rust sur mesure

- **Statut** : accepté (P0), à réviser avec les mesures de P1
- **Contexte** : le cahier des charges fixe un critère chiffré : *no-op build < 300 ms
  sur 10 000 fichiers*, sinon cœur Rust (PyO3/maturin) avec repli Python.
- **Décision** : le moteur est écrit en Python. Un banc d'essai
  (`bench/noop_build.py`) mesure le no-op build. La décision Rust est prise **sur
  la mesure**, pas par principe (ADR 0010, écrit en P1 avec les chiffres).
- **Contrainte de l'environnement** : aucune toolchain Rust n'est installée sur la
  machine de développement actuelle ; toute promesse « cœur Rust livré » serait
  invérifiable. Le repli Python est donc la référence fonctionnelle, et l'API
  du cœur (`core.graph`, `core.cache`, `core.hashing`) est écrite pour qu'une
  implémentation native puisse la remplacer sans changer les appelants.
