# ADR 0008 — Système de modules et capacités

- **Statut** : accepté (P2)
- **Contexte** : le cahier des charges veut que tout ce qui n'est pas le cœur soit un module, que
  modules officiels et communautaires partagent la même API, que les capacités soient déclarées et
  approuvées, et qu'on documente honnêtement qu'un module Python peut les contourner.
- **Décisions** :
  1. **Un manifeste TOML** (`charpente-module.toml`) déclare nom, version, plage d'API, point d'entrée,
     ce que le module fournit (`[provides]`) et ce dont il a besoin (`[capabilities]`). Tout est validé
     d'un coup (`CH7003` liste *tous* les problèmes).
  2. **API de modules 2.0.0** (numérotation du cahier des charges), semver, plage `^2.0`.
  3. **Enregistrement contrôlé** : un module n'enregistre que ce qu'il a déclaré (`CH7014`), les noms sont
     uniques (`CH7008`), il ne remplace jamais une commande intégrée (`CH7013`).
  4. **Capacités = un contrat vérifié, pas un bac à sable.** `ctx.process`, `ctx.fs`, `ctx.net`
     appliquent les capacités approuvées (y compris échappements `..` et liens symboliques). Un module
     qui importe `subprocess` ou `socket` les contourne : `charpente module check` le signale, la
     documentation le dit, la confiance repose sur signature et auteur.
  5. **Approbation persistante** ; une mise à jour qui demande davantage reste désactivée (`CH7015`).
  6. **Installer n'exécute rien** ; le code n'est importé qu'au chargement, et un module défaillant est
     ignoré avec une raison (`CH7009`), jamais fatal.
  7. **Signatures Ed25519** (RFC 8032, implémentation pure Python vérifiée sur les vecteurs de test du
     RFC) sur un condensé déterministe du dossier ; magasin de clés de confiance. Une signature qui ne
     vérifie pas est refusée, pas dégradée en « non signé ». **La liste des clés officielles est vide**
     tant qu'aucun registre signé n'a été publié.
  8. **Toolchains intégrés réécrits comme modules** : les six détecteurs (msvc, clang-cl, mingw, gcc,
     clang, apple-clang) passent par le même point d'extension `toolchain`, dans l'ordre de préférence de
     la v0.1.0 (test dédié). `toolchains.detect()` interroge le registre.
- **Alternatives rejetées** :
  - *Sigstore* comme seul mécanisme : exige des services en ligne ; prévu en complément pour un registre
    officiel, pas livré ici.
  - *Sous-processus/WASM pour l'isolation réelle* : hors périmètre P2 ; à reconsidérer si des modules
    non fiables deviennent un cas d'usage courant.
  - *Entry points setuptools* : couplent l'installation des modules à pip et à l'environnement Python ;
    un dossier + un manifeste s'installe sans pip et se signe.
