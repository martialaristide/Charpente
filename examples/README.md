# Examples

Each subdirectory is a real, buildable workspace — `cd` into one and run
`charpente build && charpente run`.

- **01_hello_console** — the minimum: one executable target.
- **02_static_library** — two targets (`engine` as a static library,
  `game` as an executable that depends on and links it), demonstrating
  `depends_on()` + `links()`.
