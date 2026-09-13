# Tutorial: a small project from nothing to packaged

This walks through everything in one sitting: scaffolding, a second
target with a dependency, a test, and packaging. Fifteen minutes with a
compiler installed (see the [README](../README.md#installation) for
per-platform prerequisites).

## 1. Scaffold and run the minimum

```bash
charpente init Calculator
cd Calculator
charpente build
charpente run
```

You now have `Calculator.charpente` and `src/main.cpp`. Open the
`.charpente` file — it's short:

```python
from charpente import *

with Workspace("Calculator") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("Calculator") as t:
        t.kind(Kind.EXECUTABLE)
        t.language(Language.CPP)
        t.standard("c++17")
        t.sources(["src/**/*.cpp"])
```

`ws` and `t` are ordinary Python objects — there's no special syntax to
learn beyond "this is a `with` block that configures something," and you
can put an `if`, a loop, or a helper function anywhere a plain Python
script could have one (see [`security.md`](security.md) for why, and what
that means for trusting a file you didn't write).

## 2. Split logic into a library

Real projects usually separate reusable logic from the executable that
uses it. Replace the scaffolded `src/main.cpp` layout with:

```
Calculator/
  Calculator.charpente
  mathlib/
    include/mathlib.h
    src/mathlib.cpp
  app/
    src/main.cpp
```

`mathlib/include/mathlib.h`:

```cpp
#pragma once
int add(int a, int b);
```

`mathlib/src/mathlib.cpp`:

```cpp
#include "mathlib.h"
int add(int a, int b) { return a + b; }
```

`app/src/main.cpp`:

```cpp
#include <cstdio>
#include "mathlib.h"

int main() {
    std::printf("2 + 3 = %d\n", add(2, 3));
    return 0;
}
```

Now declare both targets in `Calculator.charpente`:

```python
from charpente import *

with Workspace("Calculator") as ws:
    ws.configurations(["Debug", "Release"])

    with Target("mathlib") as t:
        t.kind(Kind.STATIC_LIBRARY)
        t.language(Language.CPP)
        t.standard("c++17")
        t.sources(["mathlib/src/**/*.cpp"])
        t.include_dirs(["mathlib/include"])

    with Target("Calculator") as t:
        t.kind(Kind.EXECUTABLE)
        t.language(Language.CPP)
        t.standard("c++17")
        t.depends_on(["mathlib"])   # build order: mathlib first
        t.links(["mathlib"])       # actually link libmathlib.a/mathlib.lib
        t.sources(["app/src/**/*.cpp"])
        t.include_dirs(["mathlib/include"])
```

```bash
charpente build
charpente run --target Calculator
```

`--target` is needed now because the workspace has two targets and
`charpente run` can't guess which one you mean. (`charpente build` doesn't
need it — it always builds everything, in dependency order.)

If you forget `.links(["mathlib"])`, the build fails at the link step
with an "undefined reference" (GNU) or "unresolved external symbol"
(MSVC) error naming `add` — `.depends_on()` alone only controls build
*order*, not what gets linked.

## 3. Add a test

```
Calculator/
  mathlib/
    test/
      test_mathlib.cpp
```

`mathlib/test/test_mathlib.cpp`:

```cpp
#include <cassert>
#include "mathlib.h"

int main() {
    assert(add(2, 3) == 5);
    assert(add(-1, 1) == 0);
    return 0;   // charpente test treats a zero exit as a pass
}
```

Add a `Kind.TEST` target:

```python
    with Target("mathlib_test") as t:
        t.kind(Kind.TEST)
        t.language(Language.CPP)
        t.standard("c++17")
        t.depends_on(["mathlib"])
        t.links(["mathlib"])
        t.sources(["mathlib/test/**/*.cpp"])
        t.include_dirs(["mathlib/include"])
```

```bash
charpente test
```

```
  [PASS] mathlib_test

1/1 test target(s) passed.
```

Break the test on purpose (`assert(add(2, 3) == 6)`) and run it again —
you'll get `[FAIL] mathlib_test (exit code ...)` and a non-zero exit code
from `charpente test` itself, which is what you'd wire into CI (see the
project's own `.github/workflows/tests.yml` for an example of exactly
that pattern applied to Charpente's own test suite).

## 4. Package it

```bash
charpente package --target Calculator --config Release --version 1.0.0
```

Produces `dist/Calculator-Release.zip` — no external tool needed. For a
real installer instead:

```bash
charpente package --target Calculator --format installer --config Release --version 1.0.0
```

See [`cli-reference.md`](cli-reference.md#building-a-real-installer) for
what each platform needs installed to actually build the `.exe`/`.deb`/`.pkg`
(Charpente still writes the installer script/staging tree even without the
tool, with the exact command to finish by hand).

## 5. What to read next

- [`dsl-reference.md`](dsl-reference.md) — every `Workspace`/`Target` method.
- [`cli-reference.md`](cli-reference.md) — every command and flag.
- [`security.md`](security.md) — the trust model, and what "a `.charpente`
  file is plain Python" actually means for a file you didn't write.
- [`troubleshooting.md`](troubleshooting.md) — common errors and fixes.
- [`architecture.md`](architecture.md) — internals, for anyone extending
  Charpente itself.
