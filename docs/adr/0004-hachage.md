# ADR 0004 — Hachage des clés d'action

- **Statut** : accepté (P0)
- **Décision** : BLAKE3 si le paquet `blake3` est installé (extra `fast`), sinon
  `hashlib.blake2b(digest_size=32)`. Chaque empreinte est préfixée par
  l'algorithme (`b3:…` / `b2:…`).
- **Pourquoi le préfixe** : deux machines avec des algorithmes différents ne
  peuvent jamais se tromper de contenu : leurs clés ne se rencontrent pas
  (un cache partagé rate au lieu de servir un mauvais objet).
- **SHA-256** reste utilisé pour la confiance des fichiers `.charpente` et les
  sommes de contrôle publiées par des tiers (interop).
