# ADR 0006 — Clés d'action, suivi des en-têtes et cache par contenu

- **Statut** : accepté (P1)
- **Problème** : la v0.1.0 comparait des horodatages : un en-tête modifié ne
  déclenchait rien (limite connue n° 1), un `touch` déclenchait une recompilation
  inutile, et rien n'était réutilisable d'un dossier ou d'une branche à l'autre.
- **Décision** :
  1. **Une action** = commande + entrées + sorties + environnement pertinent + identité de
     l'outil (chemin, version, empreinte du binaire). Données pures (`core/actions.py`).
  2. **Fraîcheur** : on compare l'état actuel de l'action à l'enregistrement de sa dernière
     réussite (commande, outil, contenu des entrées, contenu des en-têtes découverts, sorties
     présentes et inchangées). Le **contenu** décide, pas l'horodatage : `touch` ne recompile
     rien ; deux fichiers de même taille et même `mtime` mais de contenu différent sont
     distingués (règle « racily clean » de Git, fenêtre 2 s).
  3. **En-têtes** : `-MMD -MF` (GCC/Clang) et `/showIncludes` (MSVC/clang-cl, avec
     `VSLANG=1033` pour un marqueur non localisé). La liste découverte est enregistrée.
  4. **Cache** (`~/.charpente/cache`, `CHARPENTE_CACHE_DIR`) : adressé par contenu, en deux
     niveaux à la manière du *manifest mode* de ccache. `key1` = commande + outil + entrées
     déclarées ; le manifeste de `key1` liste les ensembles d'en-têtes déjà vus ; la clé finale
     `key2` = `key1` + contenu actuel de chaque en-tête d'un ensemble. Un en-tête modifié
     change `key2` : jamais de résultat périmé, seulement un raté.
  5. **Sorties** supprimées avant exécution (pas de membre périmé dans un `.a`), présence
     vérifiée après (CH3009). Écritures atomiques (fichier temporaire + renommage).
- **Limites documentées** :
  - Un nouvel en-tête qui *masque* un ancien plus loin dans le chemin d'inclusion n'est pas
    détecté par la liste de dépendances (limite identique à ccache).
  - Les chemins absolus font partie de la clé : deux copies du projet à des endroits
    différents ne partagent pas leurs objets (la normalisation par `-ffile-prefix-map` est
    prévue avec `verify-reproducible`, P9).
  - L'identité de l'outil couvre le pilote du compilateur, pas chaque programme qu'il lance
    (`cc1plus`, `as`, `ld`) : sa version en tient lieu.
- **Alternatives rejetées** : horodatages seuls (incorrect) ; hachage de la sortie du
  préprocesseur (`-E`, correct mais ~2× plus lent qu'une compilation en cache).
