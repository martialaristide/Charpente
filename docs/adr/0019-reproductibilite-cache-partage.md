# ADR 0019 — Reproductibilité, cache partagé, interopérabilité et boucle de développement (P9)

- **Statut** : accepté (P9)

## Contexte

La phase P9 réunit des fonctions qui ont un point commun : elles rendent un build *prévisible* (mêmes octets partout, coûts bornés, résultats partageables) et *ouvert* (importer de CMake, produire des fichiers pour Ninja, CMake, Visual Studio). Le cahier des charges y ajoute l'exécution distante (REAPI), l'exécution hybride, un projet Xcode, le rechargement à chaud, la documentation générée, la gestion des ressources et le déploiement multi-appareils. Contraintes réelles de cet environnement : une seule machine (Windows 10, MinGW-w64), Ninja 1.10.2 et CMake 3.22.1 (fournis par le SDK Android), pas de Mac, pas de serveur d'exécution, pas d'intégration continue, aucun téléphone réel (un émulateur x86_64 seulement).

## Décisions

### 1. Reproductibilité : une *saveur* de build, pas un mode global
`--reproducible` est une saveur de la chaîne d'outils (comme `--sanitize`), avec son propre dossier (`build/Debug-repro`) : les objets « normaux » et « reproductibles » ne se mélangent jamais. La saveur remplace le dossier du projet par `/src` (`-ffile-prefix-map`), fixe l'horloge (`SOURCE_DATE_EPOCH`, `TZ=UTC`, `LC_ALL=C`), supprime horodatages et build-id à l'édition de liens, rend les archives déterministes. Réservée aux chaînes de style GNU : MSVC exige `/Brepro`, que Charpente ne pilote pas ; il est **refusé avec une erreur**, pas géré « à moitié » (principe : aucun repli silencieux).
`verify-reproducible` prouve la propriété au lieu de l'affirmer : deux copies du projet dans deux dossiers de noms et profondeurs différents, deux builds sans cache, comparaison octet par octet, causes probables en cas de différence. Ce que cela ne prouve pas est écrit dans la documentation (autre OS, autre version de compilateur).

### 2. Clés de cache relocatables, uniquement dans la saveur reproductible
Pour qu'un cache soit partageable entre machines, la clé d'une action ne doit pas dépendre du dossier du projet ni du chemin du compilateur : la racine devient `@ROOT@` dans la clé, le compilateur est identifié par nom et version. Ce n'est correct que si le compilateur n'incorpore pas le chemin dans sa sortie — ce que garantit la saveur reproductible, et elle seule. Sans elle, le partage ne fonctionne qu'à dossier identique (testé : `test_without_the_reproducible_flavour_...`).

### 3. Cache partagé : un serveur HTTP adressé par le contenu, pas REAPI
Le protocole est volontairement minuscule : `GET/HEAD /cas/<digest>`, `GET/PUT /ac/<clé>`, `/mf/<clé>`, `/health`. Un client, un serveur, la bibliothèque standard Python, aucune dépendance. Sécurité par défaut : boucle locale seulement ; une autre adresse exige un jeton lu dans une variable d'environnement ; téléversements bornés et vérifiés contre leur empreinte ; noms restreints ; entrées signées en HMAC-SHA256 avec `CHARPENTE_CACHE_SIGNING_KEY` ; une adresse `http` distante sans clé est **refusée** (CH8028) sauf `CHARPENTE_REMOTE_CACHE_INSECURE=1`. Le client **échoue ouvert** : un serveur absent n'arrête jamais un build (un avertissement, 30 s de pause).
**Pas de TLS dans le serveur** : implémenter et maintenir une pile TLS correcte dans un outil de build est un mauvais investissement quand un proxy inverse le fait mieux ; la documentation dit de mettre le serveur derrière un proxy TLS et donne le modèle de menace.

### 4. Exécution distante (REAPI) et exécution hybride : **non faites**
REAPI suppose gRPC et protobuf (dépendances lourdes et compilées), un serveur d'exécution (Buildbarn, BuildBuddy, RBE), et surtout des actions **hermétiques** : toute action doit déclarer *tous* ses fichiers d'entrée et son environnement. Le moteur de Charpente découvre une partie des entrées à l'exécution (en-têtes lus par le compilateur) ; la déclaration exhaustive est un chantier en soi. Sans serveur d'exécution à disposition, rien de ce code n'aurait pu être vérifié : livrer un client REAPI non testé serait exactement ce que le projet s'interdit. Le cache partagé donne déjà l'essentiel du gain en équipe (ne pas recompiler ce qu'un autre a compilé) ; l'exécution distante reste dans `docs/idees.md`, avec ces prérequis.

### 5. Générateurs : le plan du moteur, pas une seconde interprétation
`generate ninja` et `compile-commands` sont produits à partir du **plan d'actions du moteur** (`plan → graph`), donc avec les arguments exacts d'un vrai build ; `generate cmake` part du modèle du workspace et liste ce qu'il ne sait pas exprimer ; `generate vs` produit des projets *Makefile* qui appellent `charpente` (Visual Studio reste un éditeur, Charpente reste le système de build). Vérité annoncée : Ninja et CMake ont été exécutés pour de vrai ; Visual Studio **jamais ouvert** ; **Xcode non implémenté** (un projet Xcode ne se vérifie que sur un Mac).
Un fichier que Charpente n'a pas écrit n'est jamais écrasé sans `--force`.

### 6. Import CMake : interroger CMake (File API), ne pas analyser `CMakeLists.txt`
`CMakeLists.txt` est un langage de programmation (`if`, `foreach`, fonctions, expressions génératrices) : le ré-implémenter serait une source de bugs sans fin. On demande à CMake de configurer le projet dans un dossier temporaire (la source n'est jamais modifiée) et on lit sa réponse `codemodel-v2`. Tout ce qui ne se traduit pas est **listé dans un rapport**, jamais abandonné en silence. CMake doit être installé.

### 7. Rechargement à chaud : générations et manifeste, surveillance par interrogation
Sous Windows, une DLL chargée ne peut pas être remplacée : chaque build réussi d'un plugin est copié sous un nom unique (`nom.<génération>.dll`) et un manifeste JSON est remplacé atomiquement. Un build **en échec ne publie rien** : l'hôte garde le dernier code sain. L'API côté hôte est un en-tête C/C++ sans dépendance (`charpente_hot.h`, livré dans Charpente). La surveillance se fait par interrogation de `stat` (aucune dépendance, identique partout) ; le watcher est créé *avant* le premier build (une sauvegarde pendant le build n'est pas perdue — bug trouvé et corrigé par un test). L'état du plugin reste à la charge de l'hôte : c'est écrit en toutes lettres dans la documentation.

### 8. Documentation générée : un extracteur modeste et honnête
Un balayeur de texte reconnaît `///`, `//!`, `/** */`, les étiquettes Doxygen usuelles et la déclaration qui suit ; ce n'est **pas** un analyseur C++ et la documentation le dit. `--doxygen` génère un `Doxyfile` et lance Doxygen s'il est installé (sinon CH8007, pas de repli silencieux). Le graphe est produit en Mermaid et en SVG autonome.

### 9. Ressources : ne jamais changer le résultat, seulement le rythme
`resources.plan_jobs` est une fonction pure d'un `Sample` (mémoire libre, disque libre, batterie, température) : chaque règle se teste sans vraie batterie ni disque plein. Mémoire et disque sont surveillés toujours (un OOM est pire qu'un build lent) ; le mode éco est **opt-in** (`--eco`, `CHARPENTE_ECO`). Une mesure impossible vaut « inconnue » et sa règle ne s'applique pas. La reprise après interruption n'a rien de spécial : chaque action terminée est enregistrée et dans le cache ; testé en tuant un vrai build.

### 10. Déploiement multi-appareils : un APK, des ABI, des échecs isolés
On lit les ABI de chaque appareil, on construit **un seul APK** avec exactement les bibliothèques nécessaires, on installe en parallèle, et l'échec d'un appareil n'arrête pas les autres. Les journaux `logcat` sont fusionnés, chaque ligne étiquetée. Vérité annoncée : l'APK est réel, les appareils des tests sont simulés par un faux `adb`.

## Conséquences

- Nouveaux codes d'erreur : CH1026 (budget invalide), CH8024 (budget dépassé), CH8025 (contrôle de reproductibilité impossible), CH8026 (import échoué), CH8027 (génération échouée), CH8028 (cache partagé inutilisable) ; CH8019–CH8023 relèvent de l'ADR 0018.
- Chaque fonction annonce son niveau de vérification dans `docs/stability.md` ; aucune n'est dite « stable » et la version reste `0.x` tant qu'aucune CI ne couvre les plateformes annoncées.
- Trois fonctions annoncées ne sont pas faites (REAPI, exécution hybride, Xcode) ; deux sont testées sans contrepartie réelle (Visual Studio, appareils multiples). Chacune est listée dans `docs/idees.md`.
