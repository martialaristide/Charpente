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
    # ------------------------------------------------------------------ 5xxx
    "CH5001": {
        "title": "Fournisseur d'IA non configuré",
        "message": "Aucun fournisseur d'IA n'est configuré.",
        "cause": "Les fonctions d'IA sont optionnelles et désactivées tant que vous n'avez pas choisi de fournisseur.",
        "fix": "Définissez ANTHROPIC_API_KEY, OPENAI_API_KEY ou CHARPENTE_AI_URL (voir docs/security.md).",
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
