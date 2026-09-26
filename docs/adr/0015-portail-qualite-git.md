# ADR 0015 — Portail qualité, Git/GitHub, releases

- **Statut** : accepté (P5)

## Décisions

- **Le portail est unique** : `charpente check` est ce qu'appellent les hooks Git, `commit`/`push`/`pr`/`release` et la CI. Chaque vérification est une
  extension `quality_check` (les intégrées sont enregistrées comme celles des modules) ; la configuration est `.charpente/quality.toml`, versionnée.
- **Un contrôle qui ne peut pas s'exécuter est « ignoré » à la vue de tous**, jamais « réussi » : outil absent, données absentes, toolchain incapable.
  `fail_on_skipped` le transforme en échec pour la CI. Une vérification qui plante est un échec.
- **Saveurs de build** (`--sanitize`, `--coverage`) : même toolchain + drapeaux + répertoire et identifiants d'action propres ; l'aptitude est *sondée*
  (on compile et exécute un programme minuscule) plutôt que devinée d'après le nom du compilateur.
- **`--no-verify` ne peut pas être empêché** (c'est Git) : Charpente enregistre quels *arbres* Git ont passé le portail et signale dans la PR les
  commits sans enregistrement.
- **Git reste la source de vérité** : on appelle `git`/`gh` par la couche de processus unique ; tests avec de vrais dépôts temporaires ; aucun push forcé
  sans confirmation typée ; aucune action distante sans demande (`release --publish`).
- **Jeton GitHub jamais dans un fichier** : `gh`, sinon `GH_TOKEN`/`GITHUB_TOKEN`, sinon trousseau système (bibliothèque `keyring` optionnelle).
- **Messages de commit** : Conventional Commits imposés (dérogation explicite), brouillon de secours à partir des chemins, brouillon IA optionnel toujours relu.
- **Coffre de clés** : Ed25519 (déjà présent pour les modules), graine masquée par un masque scrypt à usage unique par sel, clé publique stockée pour
  détecter une mauvaise phrase secrète — pas de chiffrement inventé. Écart avec le cahier des charges (« coffre chiffré ») : pas d'AES dans la bibliothèque
  standard ; le masque scrypt est le choix le plus simple qui reste solide pour 32 octets.
- **Provenance SLSA** honnête : déclaration in-toto + prédicat SLSA v1, enveloppe DSSE signée, `builder.id` disant que ce n'est pas un constructeur isolé.
- **Workflow CI généré depuis des données** avec un petit émetteur YAML (pas de dépendance), permissions minimales, actions épinglées par étiquette majeure.

## Bogues réels trouvés en vérifiant

- Le motif `*.charpente` correspondait au dossier `.charpente/` (déjà rencontré dans le chercheur d'espace de travail) — de nouveau dans le lecteur de version.
- Une priorité d'opérateurs (`"a" + x or "b"`) rendait un message d'échec du portail toujours vrai.
- Le brouillon de message classait un `.txt` en « docs ».

## Non fait

Branch coverage, MSVC pour warnings/sanitizers/coverage, installeurs/AAB/IPA dans `release`, jetons dans le trousseau via `charpente auth`, envoi des pièces jointes SBOM
à la PR, exécution réelle contre GitHub.
