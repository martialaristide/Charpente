# ADR 0016 — Kits, sources locales, modèles

- **Statut** : accepté (P6)

## Décisions

- **Un kit = des données** (`pkg/kits/*.toml`) : une liste de recettes ordinaires, plus ce qui a été *vérifié* et *non vérifié*. Aucun nouveau
  mécanisme : `ws.kit()` = `ws.requires()` de ses membres ; `uses("kit-x")` se développe en ses membres à l'appel (comme `uses_public`).
  Un projet peut ajouter ses kits (`.charpente/kits/`), jamais remplacer un kit livré.
- **Sources livrées avec Charpente** (`charpente://NAME`, `sha256` = condensé du dossier, fins de ligne normalisées) pour le code écrit pour
  Charpente (`tinylibc`, `charpente-mobile`) : même format de recette, même verrouillage, aucune téléchargement. `tools/sync_kit_digests.py` +
  un test empêchent un condensé périmé.
- **`ws.package_settings(...)`** : réglages par espace de travail d'un paquet (inclusions, définitions, `uses`), sans toucher recette ni verrou.
  Besoin réel : FreeRTOS exige le `FreeRTOSConfig.h` du projet et `tinylibc` sous zig.
- **Choix honnêtes** : pas de SDL3, nativefiledialog, shaderc, chargeur OpenXR, Jolt, libcurl dans les kits — chacun demande des bibliothèques système, des
  générateurs ou des toolchains qu'une recette de sources ne fournit pas. Chaque kit dit ce qu'il vérifie.
- **Modèles = dossiers de fichiers** avec `template.toml` (données), jetons `@NAME@`/`@IDENT@`/`@TITLE@`/`@PACKAGE@`, enregistrés par le même point d'extension
  `template` que les modules. Fichiers cachés stockés `dot_*` (les outils d'empaquetage ignorent les fichiers commençant par un point).
- **Vérification réelle avant d'écrire « vérifié »** : chaque modèle a été généré puis construit/exécuté quand la machine le permettait ; ceux qui ne
  peuvent pas l'être (ArkTS, iOS, ESP-IDF, casque) le disent dans leur `template.toml` et dans `charpente init --list`.

## Bogues réels trouvés en vérifiant

- **Le wheel n'embarquait ni les recettes, ni (plus tard) les kits, sources et modèles** : `package-data` n'était pas déclaré (corrigé + test qui compare
  la déclaration aux fichiers sur disque, y compris les fichiers cachés).
- `platform_settings("ios", name=...)` était impossible (`name` est le premier paramètre) : rendu positionnel seul.
- `uses_public("kit-x")` n'était pas développé ; le linter ignorait les noms de kits.
- zig `-nostdlib` retirait compiler-rt (division/flottants logiciels) des firmwares : plus demandé.
- `websocketpp` ignore le `<thread>` C++11 sous MinGW (défini explicitement) ; les extensions Python MinGW exigent un lien statique du runtime (Python 3.8+ ne
  cherche pas les DLL dans PATH).
- Ordre de rattachement Android : le gestionnaire doit être installé avant `android_attach` sinon `Event::Create` est perdu.

## Non fait

`ar-mobile`, `jeu-harmonyos`, cache binaire partagé, bibliothèques système (SDL/curl/TLS), Jolt, chargeur OpenXR, permissions/capteurs dans `charpente-mobile`.
