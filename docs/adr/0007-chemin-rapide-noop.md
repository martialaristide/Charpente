# ADR 0007 — Chemin rapide du build « rien à faire » et cache de `stat`

- **Statut** : accepté (P1)
- **Mesure de départ** (banc `bench/noop_build.py`, 10 000 sources, Windows 10, Python 3.12,
  premier moteur complet) : **18,7 s** pour ne rien faire. Profil : `Path.resolve()` (40 000
  appels), `pathlib` en général, et `os.stat` à ~48 µs l'appel (10 000 appels = 480 ms) sur
  cette machine.
- **Décisions successives** et gain mesuré :
  1. Planificateur sans `resolve()`, chemins normalisés par opérations de chaîne : 18,7 → 5,8 s.
  2. `StatCache` : sous Windows, `os.scandir` fournit les métadonnées de tout un dossier presque
     gratuitement (24 ms pour 10 000 entrées contre 480 ms pour autant de `stat`) ; Ninja fait de même.
     Ailleurs, `os.stat` reste le bon choix (1 µs).
  3. Globber propre à base de `scandir` à la place de `Path.glob` (qui crée un objet par entrée).
  4. **Empreinte de build** (`core/fastpath.py`) : après un build entièrement réussi on garde un
     *stamp* (contexte + métadonnées de tous les fichiers lus/écrits, groupées par dossier). Au
     build suivant, si le contexte et les métadonnées sont identiques, le résultat est « à jour »
     sans construire un seul objet action : **246 ms pour 10 000 fichiers** (cible : < 300 ms).
- **Sûreté** : le chemin rapide ne peut que *conclure « à jour »* quand tout est identique ; au
  moindre doute (contexte différent, fichier ajouté, retiré, modifié — même seulement `touch`é)
  le moteur complet décide. Stamp refusé si un fichier surveillé est plus récent que 2 s.
- **Limite Windows** : un listing de dossier peut être en retard sur un fichier tenu ouvert en
  écriture par un autre processus ; les sorties produites par le build sont relues avec un vrai
  `stat`, et un retard ne peut mener qu'à trop reconstruire pour elles.
- **Conséquence pour l'ADR 0010** : voir cet ADR.
