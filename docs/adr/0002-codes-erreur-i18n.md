# ADR 0002 — Codes d'erreur stables et i18n

- **Statut** : accepté (P0)
- **Décision** : chaque erreur destinée à l'utilisateur est une `ChError` portant
  un code `CHnnnn` (plage par famille : 1xxx chargement, 2xxx toolchains,
  3xxx build, 4xxx paquets d'installation, 5xxx IA, 6xxx paquets/dépendances,
  7xxx modules, 8xxx qualité/VCS, 9xxx interne). Le catalogue est du **code Python**
  (`i18n/en.py`, `i18n/fr.py`), pas des fichiers de données : il est garanti
  présent dans toute wheel et vérifiable par un test de complétude.
- **Langue** : `CHARPENTE_LANG` (`fr`/`en`), sinon la locale système
  (`LC_ALL`/`LANG`), sinon `en`.
- **Règle de stabilité** : un code publié n'est jamais réutilisé pour autre
  chose ; un code retiré reste dans le catalogue, marqué obsolète.
- **Compatibilité** : les messages anglais de la v0.1.0 sont conservés dans le
  catalogue tels quels, ce qui garde valides les tests existants.
