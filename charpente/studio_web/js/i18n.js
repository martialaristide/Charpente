// Studio speaks French and English. `t(key, {name: value})` replaces {name}; a missing key shows the key (and a test keeps both languages complete).

export const LANGS = ["en", "fr"];

export const MESSAGES = {
  en: {
    "boot.loading": "Connecting to Charpente…",
    "boot.noToken": "This page needs the address printed by `charpente studio` (it contains a private token). Start Studio again from your terminal.",
    "boot.failed": "Cannot reach the Charpente server:",
    "app.title": "Charpente Studio",
    "ok": "OK", "cancel": "Cancel", "close": "Close", "clear": "Clear", "refresh": "Refresh", "explain": "Explain", "busy": "A task is already running.",
    "workspace.notLoaded": "No workspace loaded",
    "connection.connecting": "Connecting…", "connection.open": "Connected", "connection.closed": "Disconnected",
    "connection.lost": "The connection to the Charpente server was lost. Restart `charpente studio` and reload this page.",
    "top.config": "Configuration", "top.platform": "Platform (empty: this machine)", "top.language": "Language",
    "top.build": "Build", "top.run": "Run", "top.test": "Test", "top.check": "Check", "top.reload": "Reload", "top.palette": "Commands", "top.theme": "Theme",
    "tab.files": "Files", "tab.targets": "Targets", "tab.options": "Options", "tab.packages": "Packages",
    "tab.build": "Build", "tab.problems": "Problems", "tab.graph": "Graph", "tab.profile": "Profile", "tab.git": "Git", "tab.devices": "Devices",
    "tab.terminal": "Terminal", "tab.ai": "Assistant",
    "editor.label": "Code editor", "editor.empty": "Open a file from the explorer, or press Ctrl+Shift+P for commands.", "editor.unsaved": "unsaved changes",
    "editor.saved": "Saved {name}", "editor.savedAll": "Everything is saved.", "editor.discard": "{name} has unsaved changes. Close it and lose them?", "editor.discardYes": "Discard changes",
    "editor.conflict": "{name} changed on disk since you opened it. Overwrite it with your version?", "editor.overwrite": "Overwrite",
    "status.line": "Ln", "status.column": "Col", "status.building": "building", "status.ok": "built", "status.upToDate": "up to date", "status.failed": "failed",
    "files.new": "New file", "files.newPrompt": "Path of the new file (relative to the project)", "files.refresh": "Refresh the file list",
    "targets.none": "This workspace has no targets.", "targets.uses": "uses",
    "build.all": "Build all", "build.target": "Build", "run.target": "Run", "build.idle": "Nothing built yet", "build.running": "Building…", "build.progress": "Build progress",
    "build.actions": "{total} actions to consider", "build.progressOf": "{done} of {total} actions", "build.succeeded": "Build succeeded", "build.failed": "Build failed",
    "run.running": "Running {name}…", "run.finished": "Program finished", "run.failed": "Program failed", "run.none": "There is nothing to run in this workspace.",
    "test.running": "Testing…", "test.passed": "Tests passed", "test.failed": "Tests failed",
    "check.running": "Running the quality gate…", "check.passed": "Quality gate passed", "check.failed": "Quality gate found problems",
    "problems.none": "No problems.", "severity.error": "error", "severity.warning": "warning", "severity.information": "information", "severity.hint": "hint",
    "graph.critical": "Critical path of the last build: {chain} ({seconds})", "graph.noBuild": "Build once to see the critical path.",
    "profile.none": "No build recorded yet.", "profile.session": "Last {command} ({config}) took {seconds}: {executed} actions run, {cached} from the cache.",
    "profile.targets": "Time per target", "profile.actions": "Slowest actions", "profile.headers": "Most expensive headers to touch", "profile.critical": "on the critical path",
    "profile.includedBy": "read by {count} compilations", "profile.noHeaders": "No header information yet.",
    "options.none": "This workspace declares no options (ws.option).", "options.help": "Saved in .charpente/options.toml; `--opt name=value` on the command line still wins.", "options.saved": "Option {name} saved.",
    "packages.required": "Required by this workspace", "packages.none": "No packages required.", "packages.notInstalled": "(not installed)", "packages.install": "Install", "packages.installing": "Installing…",
    "packages.done": "Done.", "packages.failed": "Installation failed.", "packages.find": "Find a package", "packages.search": "Search packages…", "packages.noMatch": "No package matches.",
    "packages.add": "Add", "packages.remove": "Remove", "packages.added": "Added {spec} to ws.requires.", "packages.removed": "Removed {spec}.",
    "git.staged": "Staged", "git.changes": "Changes", "git.untrackedTitle": "Untracked", "git.nothing": "Nothing here.", "git.stage": "Stage", "git.unstage": "Unstage",
    "git.stageHunk": "Stage this block", "git.unstageHunk": "Unstage this block", "git.open": "Open the file", "git.noDiff": "No differences.", "git.untracked": "A new file, not tracked yet.",
    "git.detached": "detached HEAD", "git.noUpstream": "no upstream", "git.message": "Commit message", "git.messagePlaceholder": "type(scope): what changed and why",
    "git.skipGate": "Skip the quality gate (recorded, and flagged in pull requests)", "git.commit": "Commit", "git.committing": "Running the gate and committing…",
    "git.committed": "Committed.", "git.commitFailed": "The commit did not happen.", "git.needMessage": "Write a commit message first.", "git.history": "History",
    "devices.refresh": "Refresh devices", "devices.none": "No device connected.", "devices.deploy": "Deploy", "devices.showLogs": "Logs", "devices.logs": "Device log",
    "devices.target": "Target to deploy", "devices.platform": "Platform", "devices.needTarget": "Choose a target to deploy.", "devices.deploying": "Deploying {target} to {device}…",
    "devices.deployed": "Deployed.", "devices.deployFailed": "Deployment failed.", "devices.logEnded": "(log ended, code {code})",
    "terminal.name": "Terminal", "terminal.new": "New terminal", "terminal.command": "Command", "terminal.placeholder": "Type a command (no pipes: it runs without a shell)",
    "terminal.stop": "Stop", "terminal.busy": "A command is already running in this terminal.", "terminal.exited": "(exited with code {code})",
    "lsp.unavailable": "clangd: not available", "lsp.stopped": "clangd stopped", "lsp.noDefinition": "No definition found.", "lsp.renameTo": "Rename the symbol to", "lsp.renamed": "{count} places renamed (save to keep them).",
    "cmd.build": "Build everything", "cmd.run": "Run the main program", "cmd.test": "Run the tests", "cmd.check": "Run the quality gate", "cmd.reload": "Reload the workspace",
    "cmd.save": "Save the file", "cmd.saveAll": "Save all files", "cmd.rename": "Rename the symbol under the cursor", "cmd.definition": "Go to definition",
    "cmd.formatToggle": "Toggle format on save (clang-format)", "cmd.formatOn": "Format on save: on", "cmd.formatOff": "Format on save: off",
    "cmd.terminal": "Focus the terminal", "cmd.theme": "Change the theme", "cmd.language": "Switch language", "cmd.show": "Show {name}",
    "theme.auto": "Theme: follow the system", "theme.light": "Theme: light", "theme.dark": "Theme: dark", "palette.placeholder": "Type a command…",
    "tab.debug": "Debug",
    "debug.idle": "Not debugging", "debug.starting": "Starting…", "debug.running": "Running…", "debug.stopped": "Stopped", "debug.stoppedBecause": "Stopped: {reason}",
    "debug.target": "Program to debug", "debug.args": "Arguments", "debug.start": "Debug", "debug.continue": "Continue", "debug.stepOver": "Step over", "debug.stepInto": "Step into",
    "debug.stepOut": "Step out", "debug.stop": "Stop", "debug.stack": "Call stack", "debug.variables": "Variables", "debug.watch": "Evaluate an expression (Enter)",
    "debug.breakpoints": "Breakpoints", "debug.noBreakpoints": "Click a line number in the editor (or press F9) to set one.", "debug.removeBreakpoint": "Remove breakpoint",
    "debug.output": "Output", "debug.noTarget": "There is no program to debug in this workspace.", "debug.expand": "Expand", "debug.terminated": "The program ended.",
    "debug.exited": "Exit code {code}.", "cmd.debugStart": "Start debugging", "cmd.debugStop": "Stop debugging", "cmd.toggleBreakpoint": "Toggle a breakpoint on this line",
    "ai.title": "Assistant", "ai.explainError": "Explain with AI",
    "ai.placeholder": "Ask about your project… (nothing is sent until you press Send)", "ai.question": "Your question", "ai.kind": "What to send",
    "ai.kindQuestion": "A question", "ai.kindError": "The last build errors", "ai.kindSelection": "The selected code", "ai.prepare": "Prepare",
    "ai.notConfigured": "No AI provider is configured; the rest of Studio works without one.", "ai.ready": "Provider: {provider}. Nothing is sent unless you press Send.",
    "ai.needSelection": "Select some code in the editor first.", "ai.willSend": "This is what would be sent to {provider}", "ai.chars": "{count} characters", "ai.redacted": "{count} secret(s) replaced",
    "ai.leftOut": "left out:", "ai.showExact": "Show exactly what is sent", "ai.send": "Send", "ai.asFix": "Ask for a fix instead", "ai.fixNote": "The answer will be a diff you can review; nothing changes until you apply it.",
    "ai.waiting": "Waiting for {provider}…", "ai.answer": "Answer", "ai.proposal": "Proposed change", "ai.apply": "Apply, rebuild and check", "ai.discard": "Discard",
    "ai.applyNote": "Applying writes the files, rebuilds, restores them if the build fails, and runs the quality gate.", "ai.applying": "Applying and rebuilding…",
    "ai.reverted": "The build still fails with this change, so it was reverted. Your files are as they were.", "ai.applied": "Applied to {files}: the build succeeds.",
  },
  fr: {
    "boot.loading": "Connexion à Charpente…",
    "boot.noToken": "Cette page a besoin de l'adresse affichée par `charpente studio` (elle contient un jeton privé). Relancez Studio depuis votre terminal.",
    "boot.failed": "Impossible de joindre le serveur Charpente :",
    "app.title": "Charpente Studio",
    "ok": "OK", "cancel": "Annuler", "close": "Fermer", "clear": "Effacer", "refresh": "Actualiser", "explain": "Expliquer", "busy": "Une tâche est déjà en cours.",
    "workspace.notLoaded": "Aucun espace de travail chargé",
    "connection.connecting": "Connexion…", "connection.open": "Connecté", "connection.closed": "Déconnecté",
    "connection.lost": "La connexion au serveur Charpente est perdue. Relancez `charpente studio` et rechargez cette page.",
    "top.config": "Configuration", "top.platform": "Plateforme (vide : cette machine)", "top.language": "Langue",
    "top.build": "Construire", "top.run": "Lancer", "top.test": "Tester", "top.check": "Vérifier", "top.reload": "Recharger", "top.palette": "Commandes", "top.theme": "Thème",
    "tab.files": "Fichiers", "tab.targets": "Cibles", "tab.options": "Options", "tab.packages": "Paquets",
    "tab.build": "Build", "tab.problems": "Problèmes", "tab.graph": "Graphe", "tab.profile": "Profil", "tab.git": "Git", "tab.devices": "Appareils",
    "tab.terminal": "Terminal", "tab.ai": "Assistant",
    "editor.label": "Éditeur de code", "editor.empty": "Ouvrez un fichier depuis l'explorateur, ou tapez Ctrl+Maj+P pour les commandes.", "editor.unsaved": "modifications non enregistrées",
    "editor.saved": "{name} enregistré", "editor.savedAll": "Tout est enregistré.", "editor.discard": "{name} a des modifications non enregistrées. Le fermer et les perdre ?", "editor.discardYes": "Abandonner les modifications",
    "editor.conflict": "{name} a changé sur le disque depuis son ouverture. L'écraser avec votre version ?", "editor.overwrite": "Écraser",
    "status.line": "Ln", "status.column": "Col", "status.building": "en cours", "status.ok": "construit", "status.upToDate": "à jour", "status.failed": "échec",
    "files.new": "Nouveau fichier", "files.newPrompt": "Chemin du nouveau fichier (relatif au projet)", "files.refresh": "Actualiser la liste des fichiers",
    "targets.none": "Cet espace de travail n'a aucune cible.", "targets.uses": "utilise",
    "build.all": "Tout construire", "build.target": "Construire", "run.target": "Lancer", "build.idle": "Rien n'a encore été construit", "build.running": "Construction…", "build.progress": "Progression du build",
    "build.actions": "{total} actions à examiner", "build.progressOf": "{done} actions sur {total}", "build.succeeded": "Build réussi", "build.failed": "Build en échec",
    "run.running": "Lancement de {name}…", "run.finished": "Programme terminé", "run.failed": "Programme en échec", "run.none": "Il n'y a rien à lancer dans cet espace de travail.",
    "test.running": "Tests en cours…", "test.passed": "Tests réussis", "test.failed": "Tests en échec",
    "check.running": "Portail qualité en cours…", "check.passed": "Portail qualité réussi", "check.failed": "Le portail qualité a trouvé des problèmes",
    "problems.none": "Aucun problème.", "severity.error": "erreur", "severity.warning": "avertissement", "severity.information": "information", "severity.hint": "suggestion",
    "graph.critical": "Chemin critique du dernier build : {chain} ({seconds})", "graph.noBuild": "Construisez une fois pour voir le chemin critique.",
    "profile.none": "Aucun build enregistré.", "profile.session": "Dernier {command} ({config}) : {seconds}, {executed} actions exécutées, {cached} depuis le cache.",
    "profile.targets": "Temps par cible", "profile.actions": "Actions les plus lentes", "profile.headers": "En-têtes les plus coûteux à modifier", "profile.critical": "sur le chemin critique",
    "profile.includedBy": "lu par {count} compilations", "profile.noHeaders": "Pas encore d'information sur les en-têtes.",
    "options.none": "Cet espace de travail ne déclare aucune option (ws.option).", "options.help": "Enregistrées dans .charpente/options.toml ; `--opt nom=valeur` en ligne de commande l'emporte toujours.", "options.saved": "Option {name} enregistrée.",
    "packages.required": "Requis par cet espace de travail", "packages.none": "Aucun paquet requis.", "packages.notInstalled": "(non installé)", "packages.install": "Installer", "packages.installing": "Installation…",
    "packages.done": "Terminé.", "packages.failed": "L'installation a échoué.", "packages.find": "Chercher un paquet", "packages.search": "Chercher des paquets…", "packages.noMatch": "Aucun paquet ne correspond.",
    "packages.add": "Ajouter", "packages.remove": "Retirer", "packages.added": "{spec} ajouté à ws.requires.", "packages.removed": "{spec} retiré.",
    "git.staged": "Indexé", "git.changes": "Modifications", "git.untrackedTitle": "Non suivis", "git.nothing": "Rien ici.", "git.stage": "Indexer", "git.unstage": "Désindexer",
    "git.stageHunk": "Indexer ce bloc", "git.unstageHunk": "Désindexer ce bloc", "git.open": "Ouvrir le fichier", "git.noDiff": "Aucune différence.", "git.untracked": "Nouveau fichier, pas encore suivi.",
    "git.detached": "HEAD détachée", "git.noUpstream": "pas de branche distante", "git.message": "Message de commit", "git.messagePlaceholder": "type(portée) : ce qui change et pourquoi",
    "git.skipGate": "Ignorer le portail qualité (enregistré, et signalé dans les pull requests)", "git.commit": "Valider", "git.committing": "Portail qualité et commit en cours…",
    "git.committed": "Commit créé.", "git.commitFailed": "Le commit n'a pas eu lieu.", "git.needMessage": "Écrivez d'abord un message de commit.", "git.history": "Historique",
    "devices.refresh": "Actualiser les appareils", "devices.none": "Aucun appareil connecté.", "devices.deploy": "Déployer", "devices.showLogs": "Journaux", "devices.logs": "Journal de l'appareil",
    "devices.target": "Cible à déployer", "devices.platform": "Plateforme", "devices.needTarget": "Choisissez une cible à déployer.", "devices.deploying": "Déploiement de {target} sur {device}…",
    "devices.deployed": "Déployé.", "devices.deployFailed": "Le déploiement a échoué.", "devices.logEnded": "(journal terminé, code {code})",
    "terminal.name": "Terminal", "terminal.new": "Nouveau terminal", "terminal.command": "Commande", "terminal.placeholder": "Tapez une commande (pas de tubes : exécutée sans shell)",
    "terminal.stop": "Arrêter", "terminal.busy": "Une commande tourne déjà dans ce terminal.", "terminal.exited": "(terminé avec le code {code})",
    "lsp.unavailable": "clangd : indisponible", "lsp.stopped": "clangd arrêté", "lsp.noDefinition": "Aucune définition trouvée.", "lsp.renameTo": "Renommer le symbole en", "lsp.renamed": "{count} endroits renommés (enregistrez pour les conserver).",
    "cmd.build": "Tout construire", "cmd.run": "Lancer le programme principal", "cmd.test": "Lancer les tests", "cmd.check": "Lancer le portail qualité", "cmd.reload": "Recharger l'espace de travail",
    "cmd.save": "Enregistrer le fichier", "cmd.saveAll": "Tout enregistrer", "cmd.rename": "Renommer le symbole sous le curseur", "cmd.definition": "Aller à la définition",
    "cmd.formatToggle": "Activer/désactiver le formatage à l'enregistrement (clang-format)", "cmd.formatOn": "Formatage à l'enregistrement : activé", "cmd.formatOff": "Formatage à l'enregistrement : désactivé",
    "cmd.terminal": "Aller au terminal", "cmd.theme": "Changer de thème", "cmd.language": "Changer de langue", "cmd.show": "Afficher {name}",
    "theme.auto": "Thème : celui du système", "theme.light": "Thème : clair", "theme.dark": "Thème : sombre", "palette.placeholder": "Tapez une commande…",
    "tab.debug": "Débogage",
    "debug.idle": "Pas de débogage", "debug.starting": "Démarrage…", "debug.running": "En cours…", "debug.stopped": "Arrêté", "debug.stoppedBecause": "Arrêt : {reason}",
    "debug.target": "Programme à déboguer", "debug.args": "Arguments", "debug.start": "Déboguer", "debug.continue": "Continuer", "debug.stepOver": "Pas à pas principal", "debug.stepInto": "Pas à pas détaillé",
    "debug.stepOut": "Pas à pas sortant", "debug.stop": "Arrêter", "debug.stack": "Pile d'appels", "debug.variables": "Variables", "debug.watch": "Évaluer une expression (Entrée)",
    "debug.breakpoints": "Points d'arrêt", "debug.noBreakpoints": "Cliquez sur un numéro de ligne dans l'éditeur (ou appuyez sur F9) pour en poser un.", "debug.removeBreakpoint": "Retirer le point d'arrêt",
    "debug.output": "Sortie", "debug.noTarget": "Il n'y a aucun programme à déboguer dans cet espace de travail.", "debug.expand": "Déplier", "debug.terminated": "Le programme est terminé.",
    "debug.exited": "Code de sortie {code}.", "cmd.debugStart": "Démarrer le débogage", "cmd.debugStop": "Arrêter le débogage", "cmd.toggleBreakpoint": "Poser/retirer un point d'arrêt sur cette ligne",
    "ai.title": "Assistant", "ai.explainError": "Expliquer avec l'IA",
    "ai.placeholder": "Posez une question sur votre projet… (rien n'est envoyé avant d'appuyer sur Envoyer)", "ai.question": "Votre question", "ai.kind": "Quoi envoyer",
    "ai.kindQuestion": "Une question", "ai.kindError": "Les dernières erreurs de build", "ai.kindSelection": "Le code sélectionné", "ai.prepare": "Préparer",
    "ai.notConfigured": "Aucun fournisseur d'IA n'est configuré ; le reste de Studio fonctionne sans.", "ai.ready": "Fournisseur : {provider}. Rien n'est envoyé sans que vous appuyiez sur Envoyer.",
    "ai.needSelection": "Sélectionnez d'abord du code dans l'éditeur.", "ai.willSend": "Voici ce qui serait envoyé à {provider}", "ai.chars": "{count} caractères", "ai.redacted": "{count} secret(s) remplacé(s)",
    "ai.leftOut": "écarté :", "ai.showExact": "Voir exactement ce qui est envoyé", "ai.send": "Envoyer", "ai.asFix": "Demander plutôt un correctif", "ai.fixNote": "La réponse sera un diff à relire ; rien ne change tant que vous ne l'appliquez pas.",
    "ai.waiting": "En attente de {provider}…", "ai.answer": "Réponse", "ai.proposal": "Modification proposée", "ai.apply": "Appliquer, reconstruire et vérifier", "ai.discard": "Abandonner",
    "ai.applyNote": "Appliquer écrit les fichiers, reconstruit, les restaure si le build échoue, et lance le portail qualité.", "ai.applying": "Application et reconstruction…",
    "ai.reverted": "Le build échoue encore avec cette modification : elle a été annulée. Vos fichiers sont comme avant.", "ai.applied": "Appliqué à {files} : le build réussit.",
  },
};

function detect() {
  try {
    const saved = localStorage.getItem("charpente-lang");
    if (saved && LANGS.includes(saved)) return saved;
  } catch {
    /* no storage */
  }
  const browser = (globalThis.navigator && navigator.language) || "en";
  return browser.toLowerCase().startsWith("fr") ? "fr" : "en";
}

let current = detect();

export function getLang() {
  return current;
}

export function setLang(lang) {
  if (LANGS.includes(lang)) current = lang;
}

export function t(key, values = {}) {
  const text = MESSAGES[current][key] ?? MESSAGES.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (whole, name) => (name in values ? String(values[name]) : whole));
}

/** Fill every element that carries data-i18n / data-i18n-title / data-i18n-placeholder / data-i18n-aria-label. */
export function translatePage(root = document) {
  document.documentElement.lang = current;
  for (const element of root.querySelectorAll("[data-i18n]")) element.textContent = t(element.dataset.i18n);
  for (const element of root.querySelectorAll("[data-i18n-title]")) element.title = t(element.dataset.i18nTitle);
  for (const element of root.querySelectorAll("[data-i18n-placeholder]")) element.placeholder = t(element.dataset.i18nPlaceholder);
  for (const element of root.querySelectorAll("[data-i18n-aria-label]")) element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
}
