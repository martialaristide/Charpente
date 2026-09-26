# `charpente docs` -- documentation from your headers

```bash
charpente docs                       # writes docs/api/ in the project
charpente docs --out site/api        # somewhere else
charpente docs --doxygen             # let Doxygen do it (if installed)
```

Output (Markdown, readable on GitHub or in any editor, no site generator needed):

* `index.md` -- the workspace, its targets, how many declarations each documents, and the dependency graph as a **Mermaid** diagram (rendered by GitHub and many editors);
* `targets/<name>.md` -- one page per target with the documented declarations of its public headers (the folders in `include_dirs`, public and interface includes), grouped by kind;
* `graph.svg` -- the same dependency graph as a standalone image, layered left to right.

## Writing the comments

The extractor reads `///`, `//!`, `/** ... */` and `/*! ... */` comments and attaches each to the declaration that follows. It understands `@brief`, `@param name text`, `@return`, `@note`, `@warning`, `@see`,
`@throws`, `@deprecated`, `@since` and `@tparam` (with `\` instead of `@` as well).

```cpp
/// @brief Adds two integers.
/// @param a first operand
/// @param b second operand
/// @return the sum
int add(int a, int b);
```

Classes, structs, enums, unions, namespaces, functions, aliases (`using`/`typedef`), macros and variables are recognised. Header suffixes: `.h .hh .hpp .hxx .inl`. A build target that is external (a package) is skipped.

## What it is not

It is a **text scanner, not a C++ parser**. Templates with unusual layouts, declarations produced by macros and comments in the middle of a declaration can be misread or missed. When that matters, use
`charpente docs --doxygen`: a `Doxyfile` is generated from the workspace (inputs, include paths, defines), Doxygen runs, and `graph.svg` is still written. If Doxygen is not installed you get error CH8007 with what to do,
not a silent fallback to the built-in extractor.
If no comment is found, the command tells you how to write one instead of producing empty pages.
