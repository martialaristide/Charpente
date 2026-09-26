# ADR 0009 — DSL v2, résolution par contexte, et gestionnaire de paquets

- **Statut** : accepté (P3)

## DSL v2

- **Additif et rétrocompatible.** Aucun champ ni comportement de la v0.1.0 n'est retiré : les 131 tests
  d'origine passent inchangés à travers le nouveau planificateur. Un fichier v0.1.0 n'active aucune des
  nouveautés.
- **Résolution à la planification, pas au chargement.** `on_config` / `on_platform` / `on_toolchain`
  enregistrent des *overlays* dans le modèle ; `dsl/resolve.py` produit, pour un contexte
  `(configuration, plateforme, toolchain, options)`, un `Target` ordinaire (overlays appliqués,
  `uses` développé, réglages `public`/`interface` propagés). Conséquences : un seul chargement sert
  toutes les configurations ; `flags.py` et le moteur ne changent pas ; Studio peut inspecter le modèle.
- **`uses` ≠ include transitif.** Les librairies statiques se lient transitivement (nécessaire pour
  l'édition de liens) ; les répertoires d'inclusion/définitions ne se propagent que via `public`,
  `interface` ou `uses_public` (l'équivalent du PUBLIC/PRIVATE de CMake).
- **Kinds non supportés = erreur explicite** (`CH3007`) à la planification, jamais un build silencieux
  d'autre chose.
- **`charpente.toml` = données seules** : pas d'exécution donc pas d'approbation ; clés inconnues =
  erreurs.
- **Lint statique par `ast`** : il n'exécute rien et ne signale que ce que les littéraux prouvent.
- **Règles (`Rule`)** : commande sous forme de liste (jamais une chaîne de shell), entrées/sorties
  déclarées ⇒ actions du moteur, donc mises en cache ; leurs sorties deviennent des entrées des
  compilations qui les consomment.

## Paquets

- **Recettes TOML (données), pas du code.** Le cahier des charges suggère des recettes « écrites dans le
  DSL » ; j'ai choisi TOML : lire ou installer une recette n'exécute rien, ce qui est cohérent avec le
  modèle de confiance (une recette venue d'un registre est un contenu non fiable). La compilation, elle,
  est faite par le moteur : un paquet devient des cibles ordinaires (`HEADER_ONLY` / `STATIC_LIBRARY`).
  Contrepartie : pas de recette avec logique arbitraire (générateurs, autotools) ; à rouvrir si le besoin
  se présente.
- **Réseau uniquement sur demande.** `ws.requires` n'enregistre qu'un souhait ; seul
  `charpente pkg install` télécharge. Un build sans paquet installé échoue en `CH6005` en disant quoi lancer.
- **Reproductibilité.** `charpente.lock` épingle les versions, le condensé exact de la recette et celui de
  l'archive ; toute archive est vérifiée avant d'être décompressée ; l'extraction refuse évasions de chemin
  et liens, gère les chemins Windows > 260 caractères (bogue réel trouvé en construisant les dix paquets).
- **Résolution** : recherche en profondeur avec retour arrière, versions décroissantes, déterministe, erreurs
  qui disent qui exige quoi (`CH6010`).
- **Hors-ligne** : `vendor/` (uniquement ce qui sert à construire : inclusions, sources listées, globs
  `keep`, licences — pas les tests/docs/exemples) et miroir HTTP (avec `Range`, écoute locale par défaut,
  sans authentification, dit clairement).
- **SBOM** SPDX 2.3 et CycloneDX 1.5 depuis le graphe réel, validés contre les schémas officiels
  (versionnés dans `tests/fixtures/schemas`).
- **Audit** OSV : n'envoie que `purl` + version ; couverture C/C++ partielle, documentée.
- **Non livré** (documenté dans `docs/packages.md`) : binaires précompilés téléchargeables, ponts
  vcpkg/Conan/pkg-config/CMake, options de recette, recettes signées.
