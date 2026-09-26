# ADR 0012 — Android natif sans Gradle

- **Statut** : accepté (P4b)

## Décisions

- **APK construit directement** (`aapt2 link` → ajout des bibliothèques → `zipalign` → `apksigner`) plutôt que via
  Gradle : la chaîne est courte, déterministe, chaque étape est une liste d'arguments dans la couche de processus
  unique (ADR 0001), et l'échec d'une étape nomme l'étape. Contrepartie : pas de Java/Kotlin, pas d'AAR/AAB ; un
  projet Gradle existant n'est pas pris en charge (documenté).
- **`Kind.MOBILE_APP` = bibliothèque partagée** chargée par `NativeActivity` (`hasCode="false"`) : c'est ce qu'exige
  Android pour du code natif pur. Sur les autres plateformes le type reste refusé (`CH3007`).
- **L'API de compilation est le `min_sdk` du workspace** (le plus élevé déclaré) : compiler contre une API plus
  récente que celle du manifeste permettrait d'appeler des fonctions absentes des appareils visés.
- **libc++ statique par défaut** (`stl="static"`), comme le `c++_static` de CMake. Trouvé en déployant pour de bon :
  le clang++ du NDK lie `libc++_shared.so` par défaut et l'application plantait au chargement. `stl="shared"` ajoute
  `libc++_shared.so` de l'ABI à l'APK.
- **Les bibliothèques sont stockées non compressées** et alignées (`zipalign -P 16` dès build-tools 35, `-p`
  avant) : Android les mappe directement depuis le fichier.
- **Signature** : clé de débogage standard du SDK pour Debug (avertissement en Release sans `--keystore`) ; clé de
  publication fournie par l'utilisateur, **mot de passe uniquement par variable d'environnement**
  (`CHARPENTE_KEYSTORE_PASSWORD`), jamais sur la ligne de commande. Le mot de passe de la clé de débogage est public
  (`android`) et peut donc y figurer.
- **`apksigner` via `java -jar`** plutôt que le `.bat` : pas de problème de guillemets sous Windows.
- **Installation des composants du SDK** depuis `repository2-3.xml` de Google, dans une racine SDK propre à
  Charpente (même disposition qu'Android Studio). **La licence n'est jamais acceptée pour l'utilisateur** : elle est
  affichée et la commande exige `--accept-android-license` (`CH8010`). SHA-1 (le seul condensé publié) vérifié ;
  le manifeste XML est refusé s'il déclare des entités ; extraction sûre des liens symboliques de zip (créés
  seulement s'ils restent dans l'archive, ignorés sous Windows).
- **`-fPIC`** ajouté aux objets des bibliothèques partagées hors Windows (manque constaté : une bibliothèque
  partagée Linux/Android ne se liait pas sans lui).
- **Un fichier C dans une cible C++** : `compile_args(..., language=)` : le code C de `native_app_glue` est compilé
  en C11 sans changer la règle v0.1.0 (les `.c` d'une cible C++ restent compilés en C++).

## Non fait

Java/Kotlin/Gradle/AAR/AAB, shaders, exécution arm64 vérifiée, téléchargement réel des composants (licence).
