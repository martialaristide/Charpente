# ADR 0001 — Une seule couche d'exécution de processus

- **Statut** : accepté (P0)
- **Contexte** : `subprocess` était importé depuis 5 modules. Chaque appel devait
  penser séparément à `shell=False`, à la capture, aux encodages et aux tests.
- **Décision** : tout lancement de processus passe par `charpente.core.process`.
  Ce module (a) refuse toute chaîne au lieu d'une liste d'arguments, (b) ne
  transmet jamais `shell=True`, (c) accepte une fonction `runner` injectée pour
  les tests. Un test de garde échoue si un autre fichier du paquet importe
  `subprocess` ou contient `shell=True`.
- **Conséquences** : les capacités des modules (`process = [...]`, ADR 0006)
  pourront être vérifiées à un seul endroit ; le journal d'actions et les
  événements `action.*` n'ont qu'un point d'accroche.
- **Alternatives rejetées** : un lint `ruff` (S602) seul — ne couvre pas
  l'absence d'import et n'impose pas la couche.
