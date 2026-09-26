# The console interface: `charpente` alone

Type `charpente` in a terminal with no command and a guided menu opens. It is for people who prefer the terminal to [Charpente Studio](studio.md): you create, build, run, test, package and diagnose
projects by choosing from lists, without having to remember commands.

```
 ■ Charpente 0.13.0   the C/C++ build system
┌─ Where you are ──────────────────────────────────────────────────────────────────┐
│ hello  hello.charpente  ● 3 target(s)                                            │
│ Folder       C:\Users\you\projects\hello                                         │
│ Last build   ● succeeded 2 min ago (build, 1.3 s)                                │
│ Working mode Debug ● this machine (windows-x64)                                  │
│ Compiler     mingw (g++.EXE)                                                     │
└──────────────────────────────────────────────────────────────────────────────────┘
  BUILD AND RUN
   ► 1  Build                            Compile the project (Debug, this machine)
     2  Run                              Build if needed, then start a program
     3  Test                             Build and run the tests
     ...
 ↑↓ move   Enter choose   the key beside a row: shortcut   Esc back   Ctrl+C leave
```

## It teaches the command line

Every choice ends as an ordinary command, **shown before it runs** (`► charpente build --config Debug`). The menu does nothing the command line cannot do: it starts the same code as
`charpente build` and friends, never through a shell, and asks before anything that deletes files. Use it until you know the commands, then stop using it.

## Using it

| Key | Action |
|---|---|
| Up / Down (also Home, End, PgUp, PgDn) | Move the selection (rows that cannot be used are skipped) |
| Enter | Choose the selected row |
| The key beside a row (`1`, `g`, `s`, `m`...) | Choose that row at once |
| Esc, Left arrow, `q` inside a sub-menu | Back |
| `q` at the main menu, or Ctrl+C anywhere in a menu | Leave |
| Ctrl+C at a question | Cancel the question |

Where arrow keys are not available (output piped to a file, `CHARPENTE_CONSOLE=plain`, a terminal that cannot be driven) the same menus work by typing the number or letter and pressing Enter.
`charpente menu` opens it explicitly, in any of those situations.

## What is in it

**When the folder has no project**: *Create a new project* (pick one of the templates, give it a name, confirm; the new project is opened), *Open an existing project* (the projects in the folders below, or type a path),
*Prepare this machine* (`charpente setup`, recommended when no compiler was found), *Check this machine* (`charpente doctor`), *Learn: the first steps*, Studio, language, help.

**When it has one**:

| Group | Rows |
|---|---|
| Build and run | Build, Run (asks which program when there are several, and its arguments), Test, Rebuild on every change (`charpente dev`) |
| Your project | Targets and packages (list targets, search and install packages, kits), Target platform (this machine, Linux ARM, Android, web, microcontrollers...; only what this machine can build is selectable, the others say what is missing; installs on Android devices), Package (zip, installer, apk), Quality check (fast, standard, strict) |
| Tools | Diagnose and understand (explain an error code, why something was rebuilt, history, costly headers), Git (status, checked commit, push, hooks), Cache and cleaning (each deletion asks first), Studio, terminal UI |
| This session | Switch Debug / Release (shortcut `m`), language (English / Français, remembered), help |

The frame at the top shows where you are: the project and its targets, the last build and how it went, the working mode (configuration and platform), and the compiler found. A project file that you have not approved yet is
**not run** to draw this frame (it says "not approved yet"): Charpente asks the first time you build, as usual ([security.md](security.md)).

## On small and old terminals

Below 46 columns, or (with arrow keys) below 42 rows, the frame shrinks to two lines and the tip is left out, so the menu keeps its room; a menu longer than the screen scrolls. If the terminal cannot show box-drawing
characters, ASCII frames are used. `NO_COLOR` turns colours off. On Windows the console is asked to understand ANSI sequences; if it refuses, plain line input is used.

## Settings

| Variable | Effect |
|---|---|
| `CHARPENTE_CONSOLE=off` | A bare `charpente` prints the plain help, as before (scripts and pipes always get the plain help) |
| `CHARPENTE_CONSOLE=plain` | No arrow keys, colours or screen clearing: type the row's number or letter |
| `NO_COLOR` | No colours |
| `CHARPENTE_LANG` | `en` or `fr` (the menu's *language* row also remembers your choice) |

## Verified, and not

* **Verified**: 96 automated tests (drawing at several widths, both languages, every flow with scripted answers, a real project created, built and run through the menu) and a **real Windows pseudo-console (ConPTY)**:
  arrows, shortcuts, redraw, text input after key navigation, Ctrl+C cancelling a question, creating, building and running a project, in English and French. That last check found one real defect
  (Windows reports Ctrl+C at a prompt as end of input, which closed the program), now fixed and tested.
* **Not verified**: the POSIX key reader (Linux, macOS) was written from the terminal specification and its decoding is unit-tested, but it was never run in a real Linux or macOS terminal; other Windows terminals than
  ConPTY-based ones (old `conhost` with legacy rendering); very small terminals by eye (checked by the tests only).
