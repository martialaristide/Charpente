# AI assistance

Everything here is **optional and opt-in**. Charpente builds, runs, tests, packages, debugs and releases with no AI provider and no API key; the commands below explain what is missing instead of failing mysteriously (`CH8020`).

```
charpente ai status                              # which provider, and the rules
charpente fix [--show-context|--dry-run] [--yes] [--apply]
charpente ai tests TARGET [--write] [--attempts N]
charpente ai migrate [FOLDER] [--write]
charpente ask "question"                         # unchanged
```

## Providers

Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `CHARPENTE_AI_URL` (a local OpenAI-compatible server such as Ollama or llama.cpp). `CHARPENTE_AI_PROVIDER` forces one; `CHARPENTE_AI_MODEL` picks a model. Keys are read from the environment only — never written to a file.

## The rules every command follows

1. **You see what is sent, before it is sent.** A summary is always printed (each item and its size). `--show-context` prints the exact text and asks; `--dry-run` prints it and sends nothing. Without a terminal, `--yes` is required — otherwise `CH8022` and nothing leaves the machine.
2. **Minimal context**: a one-line workspace summary, the error text, and ±18 lines around each reported location in at most 4 project files, under a 12 000-character limit (what is left out is listed).
3. **Secrets are removed first**: known token formats (AWS, GitHub, Slack, Google, Stripe, JWT, private keys, `sk-…`), credentials in URLs, `Authorization` headers, and quoted high-entropy values assigned to names like `password`/`api_key`. The number of replacements is shown. Files that look like secret stores (`.env`, `*.pem`, `*.key`, `id_rsa`, `credentials.*`, `*.secrets.*`…) and anything outside the project are never sent.
4. **Nothing is applied without your agreement**, and what comes back is checked first.

## `charpente fix`

Builds; if it fails, asks the provider for a fix as a **unified diff**. The diff is checked against your real files in memory (hunks are located by content, so slightly wrong line numbers are fine; a hunk that matches nowhere or in two places is refused; deleting files, `..`, absolute paths, `.git` and secret files are refused — `CH8021`). You see the diff. With `--apply` (or answering yes) it is written, the project is **rebuilt**, and if the build still fails **your files are restored byte for byte**; if it passes, the quality gate runs.

## `charpente ai tests TARGET`

Sends the target's public headers (and a sample of an existing test for style) and asks for a self-contained C++ test with its own `main()`. The test is built as a temporary test target and **run**; if it does not compile or fails, the compiler/test output is sent back for another attempt (up to `--attempts`, default 3). Only a test that compiles and passes is shown, and it is written (`tests/TARGET_ai_test.cpp`) only with `--write`; an existing file is never overwritten without `--force`. If no attempt passes, nothing is proposed.

## `charpente ai migrate`

Drafts a `.charpente` from `CMakeLists.txt` or a Makefile (plus a list of source file names). The draft must parse as Python, define a Workspace and Target, and pass `charpente lint`; it is **never executed** (a `.charpente` file is code). Written as `NAME.charpente`, or `NAME.charpente.proposed` if that exists, only with `--write`. Deterministic import (`charpente import cmake`) is a separate, planned feature.

## In Charpente Studio

The *Assistant* panel: choose what to send (a question, the last build errors, the selected code), **Prepare** shows the items, sizes, replaced secrets and the exact text; **Send** is a separate step. A fix comes back as a diff with *Apply, rebuild and check*, which does what `charpente fix --apply` does. *Explain with AI* on a failed build prepares the context but does not send it.

## Verified and not verified

Tested with fake providers: redaction, context limits, diffs (drift, ambiguity, CRLF, unsafe paths), the whole `fix` flow on a real compile error (applied, reverted when it does not build, refused, dry run, not confirmed), `ai tests` on a real library (a test that does not compile, one that fails, one that passes), `ai migrate`, and — in a real browser — the Studio flow against a fake OpenAI-compatible server that records everything it receives (the test asserts a secret in the source is not in the request). **No real AI provider was called**: the prompts have not been tuned against real models, and answer quality is unknown.
