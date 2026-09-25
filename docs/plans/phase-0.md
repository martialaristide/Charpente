# Phase P0 — Fondations

## Objectifs

1. Une **seule** couche d'exécution de sous-processus : `charpente/core/process.py`.
2. Un **catalogue d'erreurs** à codes stables (`CH1001`…), rendu en français et
   en anglais, avec `charpente explain CHxxxx`.
3. **i18n** FR/EN (langue via `CHARPENTE_LANG`, puis locale système, défaut `en`).
4. **Qualité outillée** : `ruff`, `mypy --strict` sur les nouveaux modules,
   couverture (`pytest-cov`), CI matricielle 3 OS.
5. **Publication préparée** de la 0.2.0 (sdist + wheel + `twine check` +
   workflow « trusted publishing »). L'envoi réel sur PyPI n'est pas exécuté.

## Fichiers

| Fichier | Rôle |
|---|---|
| `charpente/core/process.py` | `run()`, `Popen()`-like unique ; refuse `shell=True` ; injection pour les tests |
| `charpente/errors.py` | `ChError` (code + paramètres), rendu localisé, compatibilité `CommandError` |
| `charpente/i18n/__init__.py`, `en.py`, `fr.py` | catalogue : titre, message, correction, explication longue |
| `charpente/commands/explain.py` | `charpente explain CH1001` |
| `tests/test_process_layer.py` | garde-fou : aucun `subprocess`/`shell=True` hors `core/process.py` |
| `tests/test_errors_catalog.py` | chaque code a FR + EN + correction ; codes uniques ; format |
| `pyproject.toml`, `.github/workflows/*` | outils, extras, publication |

## API

```python
from charpente.core import process
result = process.run(["g++", "-c", "a.cpp"], capture=True)   # ProcessResult
process.run("g++ -c a.cpp")                                  # -> ChError CH9001 (chaîne interdite)
```

```python
raise ChError("CH3001", target="app")      # message localisé + correction + « charpente explain CH3001 »
```

## Compatibilité

- `CommandError`, `WorkspaceLoadError`, `NoToolchainFoundError`… restent
  importables et **héritent de `ChError`** ; leurs messages anglais
  d'origine sont conservés mot pour mot (les 131 tests existants restent
  la référence).
- `builder.build_target(..., run=…)` garde sa signature.

## Risques

- Une locale française sur la machine du développeur changerait les messages
  vus par les tests → `conftest.py` force `CHARPENTE_LANG=en`.
- `subprocess.run` injecté par les tests renvoie des `CompletedProcess` : la
  couche `process` doit accepter cette forme.

## Critères d'acceptation

- [ ] Toutes les erreurs de la v0.1.0 ont un code ; `explain` fonctionne en FR/EN.
- [ ] `grep -r "import subprocess" charpente/` ne trouve que `core/process.py`.
- [ ] `ruff check`, `mypy --strict charpente/core charpente/errors.py charpente/i18n` : 0 erreur.
- [ ] 131 tests d'origine + nouveaux : verts ; couverture globale ≥ 75 %.
- [ ] `python -m build` + `twine check` : OK.
- [ ] CI verte sur 3 OS (à vérifier au premier push — **non vérifiable localement**).
