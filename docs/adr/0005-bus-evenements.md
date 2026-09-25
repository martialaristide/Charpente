# ADR 0005 — Bus d'événements : le build émet, les abonnés affichent

- **Statut** : accepté (P1, implémenté avant P2 parce que le moteur en dépend)
- **Contexte** : en v0.1.0 le code de build affichait directement. Studio, la CI,
  l'historique, les hooks et les notifications ont tous besoin de suivre un build
  sans que le moteur les connaisse.
- **Décision** :
  - Un `EventBus` par session. Un événement est une dataclass immuable
    (`schema_version`, `id` croissant, `parent_id`, `timestamp` monotone, `wall_time`,
    `session_id`, `type`, `payload` en lecture seule).
  - La taxonomie est **une table unique** (`events/types.py`) d'où l'on dérive les
    JSON Schemas (`docs/events/`) et la validation en mode strict (tests).
  - Deux modes d'abonnement : *synchrone* (rapide, dans le thread émetteur ; historique,
    collecteurs) et *asynchrone* (file bornée + un thread ; terminal, JSONL). Un abonné
    lent voit ses événements **abandonnés et comptés**, jamais le build ralenti.
  - L'ordre de livraison est celui des `id` (livraison sous verrou réentrant).
  - Une exception d'abonné est contenue et consignée.
- **Conséquences** : `--output jsonl` est le même flux que celui consommé par Studio ;
  `charpente replay` rejoue un journal de session ; l'historique SQLite n'est qu'un
  abonné.
- **Compromis assumé** : un `KeyboardInterrupt` levé par un abonné synchrone dans le
  thread principal interrompt le build (utile : c'est ainsi que les tests simulent
  Ctrl+C). Seules les `Exception` sont contenues.
