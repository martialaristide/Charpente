"""Catalogue de messages en français. Mêmes codes et mêmes paramètres que
`en.py` (un test vérifie que les deux catalogues sont strictement alignés)."""
from __future__ import annotations

from typing import Dict

CATALOG: Dict[str, Dict[str, str]] = {
    # ------------------------------------------------------------------ 1xxx
    "CH1001": {
        "title": "Fichier de workspace introuvable",
        "message": "Fichier introuvable : {path}",
        "cause": "Le chemin donné avec --file n'existe pas.",
        "fix": "Vérifiez l'orthographe du chemin, ou lancez la commande depuis le dossier qui contient le fichier .charpente.",
        "explain": "Les commandes qui ont besoin d'un workspace acceptent --file CHEMIN. Sans cette option, Charpente cherche un unique fichier *.charpente dans le dossier courant, puis dans chaque dossier parent.",
    },
    "CH1002": {
        "title": "Aucun fichier .charpente trouvé",
        "message": "Aucun fichier .charpente dans {directory} ni dans ses dossiers parents.",
        "cause": "Ni le dossier courant ni ses parents ne contiennent de fichier .charpente.",
        "fix": "Lancez `charpente init MonApp` pour en créer un, ou utilisez --file CHEMIN.",
    },
    "CH1003": {
        "title": "Plusieurs fichiers .charpente",
        "message": "Plusieurs fichiers .charpente dans {directory} : {names}. Utilisez --file pour en choisir un.",
        "cause": "Charpente ne choisit un workspace automatiquement que si le dossier contient exactement un fichier .charpente.",
        "fix": "Ajoutez --file CHEMIN avec le workspace voulu.",
    },
    "CH1004": {
        "title": "Le fichier de workspace n'a pas pu être chargé",
        "message": "Erreur au chargement de {path} : {detail}",
        "cause": "Le fichier .charpente est du code Python ; son exécution a levé une erreur (syntaxe, nom inconnu, mauvais argument...).",
        "fix": "Lisez le détail après les deux-points : il indique la ligne et le problème. `charpente lint` fait une vérification statique.",
    },
    "CH1005": {
        "title": "Aucun workspace défini",
        "message": "{path} ne définit aucun workspace (pas de bloc `with Workspace(...):`).",
        "cause": "Le fichier s'exécute sans erreur mais n'ouvre jamais de bloc `with Workspace(...)`.",
        "fix": "Placez vos cibles dans un bloc `with Workspace(\"Nom\") as ws:`.",
    },
    "CH1006": {
        "title": "Confirmation requise avant d'exécuter le fichier de workspace",
        "message": "Refus d'exécuter ce {label} sans confirmation : {path}\n  Un fichier .charpente s'exécute comme du code Python sans restriction. Cette session ne peut pas demander de confirmation (non interactive).\n  Correction : lancez `charpente` une fois en interactif pour l'approuver, ou définissez CHARPENTE_TRUST_ALL=1 dans cet environnement (CI) si vous faites confiance à la source de ce dépôt.",
        "cause": "Un fichier .charpente est du code exécutable. Charpente demande une fois par fichier et par contenu avant de l'exécuter, et ce terminal n'est pas interactif.",
        "fix": "Lancez une commande une fois dans un terminal interactif et répondez « y », ou définissez CHARPENTE_TRUST_ALL=1 en CI pour les dépôts de confiance.",
        "explain": "Les approbations sont stockées par empreinte SHA-256 du contenu dans ~/.charpente/trusted_files.json. Modifier le fichier redemande l'approbation. Un charpente.toml déclaratif n'en a jamais besoin : il ne contient aucun code.",
    },
    "CH1007": {
        "title": "Exécution refusée",
        "message": "Exécution refusée par l'utilisateur : {path}",
        "cause": "Vous avez répondu « non » à la question de savoir s'il faut exécuter ce fichier .charpente.",
        "fix": "Lisez le fichier, puis relancez la commande si vous lui faites confiance.",
    },
    "CH1008": {
        "title": "Cible inconnue",
        "message": "Aucune cible nommée {name!r} dans le workspace {workspace!r}. Cibles connues : {known}",
        "cause": "Le nom donné à --target n'est pas déclaré dans le workspace.",
        "fix": "Utilisez un des noms de cible listés.",
    },
    "CH1009": {
        "title": "Plusieurs cibles : en choisir une",
        "message": "Le workspace {workspace!r} a {count} cibles ; précisez-en une avec --target. Cibles connues : {known}",
        "cause": "La commande travaille sur une seule cible et le workspace en déclare plusieurs.",
        "fix": "Ajoutez --target NOM.",
    },
    "CH1010": {
        "title": "Le workspace n'a aucune cible",
        "message": "Le workspace {workspace!r} n'a aucune cible à exécuter.",
        "cause": "Aucun bloc `with Target(...)` n'a été déclaré.",
        "fix": "Déclarez au moins une cible.",
    },
    "CH1011": {
        "title": "Nom vide",
        "message": "{field} ne peut pas être vide.",
        "cause": "Les noms de workspace et de cible deviennent des noms de fichiers : ils ne peuvent pas être vides.",
        "fix": "Donnez-lui un nom non vide.",
    },
    "CH1012": {
        "title": "Nom contenant '..'",
        "message": "{field} {name!r} contient '..', ce qui est interdit (un fichier généré pourrait sortir du dossier de sortie).",
        "cause": "Un '..' dans un nom pourrait faire atterrir un fichier de sortie hors du dossier de build.",
        "fix": "Retirez le '..' du nom.",
    },
    "CH1013": {
        "title": "Nom contenant un séparateur de chemin ou un caractère de contrôle",
        "message": "{field} {name!r} contient un séparateur de chemin ou un caractère de contrôle, ce qui est interdit.",
        "cause": "Les noms deviennent des noms de fichiers ; barres obliques, antislashs et caractères de contrôle n'y sont pas valides.",
        "fix": "Utilisez lettres, chiffres, '-', '_' et '.'.",
    },
    "CH1014": {
        "title": "Cible déclarée hors d'un workspace",
        "message": "La cible {name!r} est déclarée hors de tout bloc `with Workspace(...)`.",
        "cause": "`Target(...)` doit être utilisé dans un bloc `with Workspace(...)`.",
        "fix": "Déplacez la cible dans le bloc du workspace.",
    },
    "CH1015": {
        "title": "Workspaces imbriqués",
        "message": "Le workspace {name!r} est ouvert alors que {outer!r} est encore ouvert. Les workspaces ne peuvent pas être imbriqués.",
        "cause": "Un bloc `with Workspace(...)` a été ouvert dans un autre.",
        "fix": "Fermez le premier workspace avant d'en ouvrir un autre.",
    },
    "CH1016": {
        "title": "Cible en double",
        "message": "La cible {name!r} est déjà définie dans le workspace {workspace!r}.",
        "cause": "Deux cibles portent le même nom.",
        "fix": "Renommez l'une d'elles.",
    },
    "CH1017": {
        "title": "Cible sans emplacement",
        "message": "La cible {name!r} n'a pas d'emplacement ; resolved_sources() doit s'exécuter après que le chargeur l'a rattaché.",
        "cause": "Une cible a été construite à la main sans le dossier du workspace.",
        "fix": "Créez les cibles via le DSL, ou passez `location=`.",
    },
    "CH1018": {
        "title": "Fichier de workspace introuvable",
        "message": "Fichier de workspace introuvable : {path}",
        "cause": "Le chargeur a reçu un chemin qui n'existe pas.",
        "fix": "Vérifiez le chemin.",
    },
    "CH1019": {
        "title": "Motif de fichiers invalide",
        "message": "Motif {pattern!r} invalide : '**' doit être un composant de chemin entier (écrivez src/**/*.cpp, pas src/**.cpp).",
        "cause": "'**' signifie « un nombre quelconque de dossiers » et ne fonctionne que comme composant complet entre deux barres obliques.",
        "fix": "Écrivez \"src/**/*.cpp\" pour désigner les fichiers .cpp de src et de tous ses sous-dossiers.",
    },
    "CH1020": {
        "title": "Motif de fichiers absolu",
        "message": "Le motif {pattern!r} est absolu : les motifs de sources()/exclude() sont relatifs au dossier du fichier .charpente.",
        "cause": "Des chemins absolus rendent un workspace impossible à déplacer ou à partager.",
        "fix": "Utilisez un chemin relatif au fichier .charpente (\"../shared/*.cpp\" est permis).",
    },
    # ------------------------------------------------------------------ 2xxx
    "CH2001": {
        "title": "Aucun compilateur C/C++ trouvé",
        "message": "Aucun compilateur C/C++ trouvé pour {os}. Installez-en un et vérifiez qu'il est dans le PATH :\n  windows -> Visual Studio Build Tools (cl.exe), ou LLVM (clang-cl.exe), ou MSYS2/MinGW (gcc.exe + g++.exe)\n  linux   -> `apt install build-essential` (gcc/g++) ou clang\n  macos   -> `xcode-select --install` (clang via les Xcode CLT)",
        "cause": "Charpente cherche un compilateur dans le PATH et n'en a trouvé aucun.",
        "fix": "Installez un compilateur pour votre système (voir le message) et rouvrez votre terminal. `charpente doctor` revérifie.",
    },
    "CH2002": {
        "title": "Programme introuvable",
        "message": "Programme introuvable : {tool!r}. Il n'est pas installé ou pas dans le PATH.",
        "cause": "Charpente a essayé de lancer un programme que le système ne trouve pas.",
        "fix": "Installez-le, ou ajoutez son dossier au PATH. `charpente doctor` liste ce qui manque.",
    },
    "CH2003": {
        "title": "Système hôte non pris en charge",
        "message": "Système hôte non pris en charge : {os!r}",
        "cause": "Charpente ne peut lancer des builds que depuis Windows, Linux ou macOS.",
        "fix": "Utilisez une machine prise en charge.",
    },
    "CH2004": {
        "title": "Permission refusée au lancement d'un programme",
        "message": "Permission refusée au lancement de {tool!r}.",
        "cause": "Le fichier existe mais ne peut pas être exécuté (bit d'exécution manquant, antivirus, ou c'est un dossier).",
        "fix": "Vérifiez ses permissions (chmod +x sous Linux/macOS) ou votre logiciel de sécurité.",
    },
    # ------------------------------------------------------------------ 3xxx
    "CH3001": {
        "title": "Cible sans fichiers source",
        "message": "La cible {target!r} n'a aucun fichier source (vérifiez ses motifs sources()/exclude()).",
        "cause": "Les motifs donnés à sources() ne correspondent à aucun fichier, ou exclude() les a tous retirés.",
        "fix": "Vérifiez les motifs relativement au dossier du fichier .charpente (ex. \"src/**/*.cpp\").",
    },
    "CH3002": {
        "title": "Échec de compilation",
        "message": "{detail}",
        "cause": "Le compilateur a renvoyé une erreur pour un fichier source.",
        "fix": "Lisez d'abord le premier message d'erreur : les suivants en sont souvent des conséquences. `charpente build --ai-diagnose` peut aider (opt-in).",
    },
    "CH3003": {
        "title": "Échec de l'édition de liens",
        "message": "{detail}",
        "cause": "Tous les fichiers ont compilé, mais l'éditeur de liens n'a pas pu produire la sortie (bibliothèque manquante, symbole indéfini, symbole en double).",
        "fix": "Vérifiez .links([...]) et l'ordre des dépendances.",
    },
    "CH3004": {
        "title": "Cycle de dépendances",
        "message": "Cycle de dépendances détecté : {cycle}",
        "cause": "Des cibles dépendent les unes des autres en boucle : aucun ordre de build n'existe.",
        "fix": "Cassez la boucle : déplacez le code partagé dans une troisième cible dont les deux dépendent.",
    },
    "CH3005": {
        "title": "Dépendance inconnue",
        "message": "La cible {target!r} dépend de la cible inconnue {dependency!r}.",
        "cause": "depends_on() nomme une cible qui n'est pas déclarée.",
        "fix": "Corrigez l'orthographe ou déclarez la cible.",
    },
    "CH3006": {
        "title": "Ignorée car une dépendance a échoué",
        "message": "Ignorée : dépend de cible(s) en échec {targets}.",
        "cause": "Une cible dont celle-ci a besoin n'a pas été construite.",
        "fix": "Corrigez d'abord la cible en échec.",
    },
    "CH3007": {
        "title": "Sorte de cible non gérée",
        "message": "Sorte de cible non gérée : {kind}",
        "cause": "Cette sorte de cible n'est pas prise en charge par la toolchain/plateforme choisie.",
        "fix": "Consultez `charpente platforms` et le tableau de prise en charge des sortes.",
    },
    "CH3008": {
        "title": "Build interrompu",
        "message": "Build interrompu.",
        "cause": "Le build a été arrêté (Ctrl+C ou signal).",
        "fix": "Relancez le build : les actions terminées sont gardées dans le cache et ne sont pas refaites.",
    },
    "CH3009": {
        "title": "L'action n'a produit aucun fichier de sortie",
        "message": "La commande a réussi mais n'a pas créé {path}.",
        "cause": "Une commande de build s'est terminée avec 0 alors que le fichier attendu manque (mauvais -o, ou outil qui écrit ailleurs).",
        "fix": "Vérifiez la commande avec `charpente build -v` et la documentation de l'outil.",
    },
    "CH3010": {
        "title": "Deux actions écrivent le même fichier",
        "message": "Deux actions de build écrivent le même fichier {path} : {first} et {second}.",
        "cause": "Deux cibles (ou deux sources) produiraient une sortie de même chemin : l'une écraserait l'autre en silence.",
        "fix": "Donnez des noms distincts aux sources ou aux cibles, ou excluez l'une d'elles.",
    },
    "CH3011": {
        "title": "Contrainte d'ordre vers une action inconnue",
        "message": "L'action {action!r} doit s'exécuter après {missing!r}, qui n'existe pas.",
        "cause": "Une arête d'ordonnancement interne pointe vers une action absente du graphe de build.",
        "fix": "C'est un bogue d'un module ou de Charpente ; signalez-le.",
    },
    "CH3012": {
        "title": "Cycle dans le graphe d'actions",
        "message": "Les actions de build dépendent les unes des autres en cycle : {cycle}",
        "cause": "Une action (directement ou via d'autres) a besoin de sa propre sortie avant de pouvoir s'exécuter.",
        "fix": "Cassez le cycle : vérifiez les fichiers générés qui sont aussi des entrées de l'action qui les produit.",
    },
    "CH3013": {
        "title": "Action en double",
        "message": "L'action {action!r} est définie deux fois.",
        "cause": "Deux actions ont reçu le même identifiant.",
        "fix": "C'est un bogue d'un module ou de Charpente ; signalez-le.",
    },
    # ------------------------------------------------------------------ 4xxx
    "CH4001": {
        "title": "Rien à empaqueter",
        "message": "Échec du build, rien à empaqueter : {detail}",
        "cause": "L'empaquetage commence par construire la cible ; ce build a échoué.",
        "fix": "Corrigez l'erreur de build ci-dessus, puis empaquetez à nouveau.",
    },
    "CH4002": {
        "title": "Aucun format d'installeur pour ce système",
        "message": "Aucun format d'installeur défini pour {os}.",
        "cause": "--format installer existe pour Windows, Linux et macOS seulement.",
        "fix": "Utilisez --format zip.",
    },
    "CH4003": {
        "title": "L'outil d'empaquetage a échoué",
        "message": "{tool} a échoué (code de sortie {code}).",
        "cause": "L'outil d'installeur de la plateforme a renvoyé une erreur.",
        "fix": "Lisez la sortie propre à l'outil, au-dessus de ce message.",
    },
    "CH4004": {
        "title": "Sortie pas encore construite",
        "message": "{path} n'existe pas. Construisez d'abord (retirez --no-build).",
        "cause": "--no-build a été donné mais la cible n'a jamais été construite dans cette configuration.",
        "fix": "Relancez sans --no-build, ou lancez d'abord `charpente build`.",
    },
    "CH4005": {
        "title": "Erreur d'utilisation",
        "message": "{usage}",
        "cause": "La ligne de commande est incomplète ou mal formée.",
        "fix": "Lancez la commande avec --help.",
    },
    "CH4006": {
        "title": "Paquet optionnel manquant",
        "message": "Ceci nécessite le paquet optionnel {package!r}, qui n'est pas installé.",
        "cause": "La fonctionnalité est optionnelle et sa dépendance n'est installée que sur demande.",
        "fix": "Installez-le avec : pip install \"charpente[{extra}]\"",
    },
    # ------------------------------------------------------------------ 5xxx
    "CH5001": {
        "title": "Fournisseur d'IA non configuré",
        "message": "Aucun fournisseur d'IA n'est configuré.",
        "cause": "Les fonctions d'IA sont optionnelles et désactivées tant que vous n'avez pas choisi de fournisseur.",
        "fix": "Définissez ANTHROPIC_API_KEY, OPENAI_API_KEY ou CHARPENTE_AI_URL (voir docs/security.md).",
    },
    # ------------------------------------------------------------------ 6xxx
    "CH6001": {
        "title": "Échec du téléchargement",
        "message": "Impossible de télécharger {url} : {detail}",
        "cause": "Le serveur est injoignable, a coupé la connexion ou a refusé la requête.",
        "fix": "Vérifiez votre connexion et réessayez : un téléchargement interrompu reprend là où il s'est arrêté. Charpente fonctionne hors ligne pour tout ce qui est déjà en cache.",
    },
    "CH6002": {
        "title": "Somme de contrôle incorrecte",
        "message": "Somme de contrôle incorrecte pour {url} : attendu {expected}, obtenu {actual}. Le fichier a été supprimé.",
        "cause": "Le fichier téléchargé n'est pas celui qui a été publié (corruption, transfert tronqué ou falsification).",
        "fix": "Réessayez. Si cela persiste, n'utilisez pas cette source : signalez-le à l'éditeur.",
    },
    "CH6003": {
        "title": "Téléchargement au-delà de la taille autorisée",
        "message": "{url} fait {size} octets, au-delà du budget autorisé de {budget} octets. Rien n'a été conservé.",
        "cause": "Un budget de téléchargement (--max-download) est défini et ce fichier est plus gros.",
        "fix": "Augmentez le budget, ou récupérez-le sur une meilleure connexion et placez-le dans le cache local ou un miroir.",
    },
    "CH6004": {
        "title": "Mode hors ligne : accès réseau refusé",
        "message": "Refus de télécharger {url} : le mode hors ligne est actif (CHARPENTE_OFFLINE=1).",
        "cause": "Vous avez demandé à Charpente de ne pas utiliser le réseau.",
        "fix": "Retirez CHARPENTE_OFFLINE, ou fournissez le fichier via un miroir local ou un dossier vendor.",
    },
    # ------------------------------------------------------------------ 7xxx
    "CH7001": {
        "title": "Version invalide",
        "message": "Version invalide : {value!r} (attendu MAJEUR.MINEUR.CORRECTIF, p. ex. 1.2.0).",
        "cause": "Le texte n'est pas une version sémantique.",
        "fix": "Écrivez MAJEUR.MINEUR.CORRECTIF, avec éventuellement un suffixe -prerelease.",
    },
    "CH7002": {
        "title": "Contrainte de version invalide",
        "message": "Contrainte de version invalide : {value!r} (exemples : ^1.2, ~1.2.3, >=1.0,<2.0, *).",
        "cause": "La contrainte n'a pas pu être analysée.",
        "fix": "Utilisez ^ (compatible), ~ (niveau correctif), des opérateurs de comparaison séparés par des virgules, ou *.",
    },
    "CH7003": {
        "title": "Manifeste de module invalide",
        "message": "Manifeste de module invalide {path} : {detail}",
        "cause": "charpente-module.toml est absent, n'est pas du TOML valide, ou il manque un champ obligatoire.",
        "fix": "Comparez-le au manifeste de docs/modules.md ; `charpente module check CHEMIN` liste tous les problèmes.",
    },
    "CH7004": {
        "title": "Le module exige une autre API de modules",
        "message": "Le module {name} exige l'API de modules {required}, mais ce Charpente fournit {provided}.",
        "cause": "Le module a été écrit pour une version incompatible de l'API de modules.",
        "fix": "Mettez à jour le module (`charpente module update {name}`) ou Charpente.",
    },
    "CH7005": {
        "title": "Capacité non accordée",
        "message": "Le module {module} a tenté d'utiliser {capability}, qu'il n'a pas déclaré ou que l'utilisateur n'a pas approuvé.",
        "cause": "Un module ne peut utiliser que ce que son manifeste déclare et que vous avez approuvé à l'installation.",
        "fix": "Si vous faites confiance au module, ajoutez la capacité à son manifeste puis approuvez-la avec `charpente module approve {module}`.",
    },
    "CH7006": {
        "title": "Module introuvable",
        "message": "Aucun module nommé {name!r} ({where}).",
        "cause": "Le nom n'est pas installé et n'existe dans aucun registre configuré.",
        "fix": "`charpente module list` montre ce qui est installé ; ajoutez un registre avec `charpente module registry add URL`, ou installez depuis un dossier : `charpente module add ./mon-module`.",
    },
    "CH7007": {
        "title": "Échec du contrôle d'intégrité du module",
        "message": "Contrôle d'intégrité échoué pour {name} : {detail}",
        "cause": "Le module téléchargé ou décompressé ne correspond pas à sa somme de contrôle ou à sa signature publiées.",
        "fix": "Ne l'installez pas. Retéléchargez-le depuis un registre de confiance ; si cela persiste, signalez-le au mainteneur du registre.",
    },
    "CH7008": {
        "title": "Extension en double",
        "message": "Le module {module} tente d'enregistrer {kind} {name!r}, déjà fourni par {owner}.",
        "cause": "Deux modules fournissent une extension du même nom.",
        "fix": "Désactivez l'un d'eux (`charpente module disable NOM`) ou demandez à son auteur de la renommer.",
    },
    "CH7009": {
        "title": "Échec du chargement du module",
        "message": "Le module {name} n'a pas pu être chargé : {detail}",
        "cause": "L'import du point d'entrée du module a levé une erreur.",
        "fix": "Lancez `charpente module check {name}` ; si le module est le vôtre, corrigez l'erreur ci-dessus, sinon désactivez-le et signalez le problème.",
    },
    "CH7010": {
        "title": "Module non signé : confirmation requise",
        "message": "Le module {name} n'est pas signé par une clé de confiance ({detail}). Refus sans confirmation.",
        "cause": "Seuls les modules signés par une clé de confiance s'installent sans question.",
        "fix": "Examinez les capacités du module, puis relancez avec --allow-unsigned si vous faites confiance à sa source.",
    },
    "CH7011": {
        "title": "Module déjà installé",
        "message": "Le module {name} {version} est déjà installé.",
        "cause": "La même version est déjà présente.",
        "fix": "Utilisez `charpente module update {name}` ou supprimez-le d'abord.",
    },
    "CH7012": {
        "title": "Registre injoignable",
        "message": "Impossible de lire le registre de modules {registry} : {detail}",
        "cause": "L'adresse du registre est erronée, hors ligne, ou n'est pas un index de registre valide.",
        "fix": "Vérifiez l'adresse et votre connexion. Charpente fonctionne hors ligne avec les modules déjà installés.",
    },
    "CH7013": {
        "title": "La commande du module entre en conflit avec une commande intégrée",
        "message": "Le module {module} fournit la commande {name!r}, qui est une commande intégrée et ne peut pas être remplacée.",
        "cause": "Un module peut ajouter des commandes mais jamais remplacer les commandes intégrées.",
        "fix": "Demandez à l'auteur du module de renommer la commande.",
    },
    "CH7014": {
        "title": "Extension non déclarée",
        "message": "Le module {module} a enregistré l'extension {kind} {name!r}, que son manifeste ne déclare pas sous [provides] {key}.",
        "cause": "Un module doit déclarer tout ce qu'il fournit afin de pouvoir être examiné avant d'être chargé.",
        "fix": "Ajoutez {name!r} à la liste [provides] {key} du manifeste du module.",
    },
    "CH7015": {
        "title": "Le module doit être approuvé à nouveau",
        "message": "Le module {name} demande plus que ce que vous avez approuvé ({detail}) ; il reste désactivé jusqu'à approbation.",
        "cause": "Une mise à jour a changé les capacités demandées par le module.",
        "fix": "Examinez-les avec `charpente module info {name}`, puis `charpente module approve {name}`.",
    },
    # ------------------------------------------------------------------ 9xxx
    "CH9001": {
        "title": "La commande doit être une liste d'arguments",
        "message": "Refus de lancer {command!r} : une commande doit être une liste d'arguments non vide, jamais une chaîne pour un shell.",
        "cause": "Charpente ne passe jamais de commande par un shell (pas de shell=True), ce qui empêche l'injection via des noms de fichiers.",
        "fix": "Règle interne : passez [\"programme\", \"arg1\", ...]. Si vous voyez ceci depuis un module, signalez-le à son auteur.",
    },
    "CH9002": {
        "title": "Erreur interne",
        "message": "Erreur interne : {detail}",
        "cause": "Un bogue de Charpente.",
        "fix": "Signalez-le avec la sortie de `charpente doctor` sur https://github.com/martialaristide/Charpente/issues",
    },
}
