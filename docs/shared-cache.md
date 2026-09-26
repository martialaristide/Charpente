# The shared build cache

Charpente already keeps a content-addressed cache on your machine (`charpente cache stats`). The **shared cache** puts a second, common one behind it, so a teammate or a CI job
that already compiled a file saves everyone else the work. It is an HTTP server (`charpente cache serve`) and a client setting; there is nothing to install besides Charpente.

## What it does, and what it does not

* **Lookup order**: local cache, then the shared one. A shared hit is copied into the local cache (verified, see below), so the second time it is local.
* **Stores** go to the local cache first, then are pushed to the shared one in the background.
* **Fail open**: a server that is down, slow or refusing never fails a build. It is skipped for 30 seconds, the build carries on locally, and you get one warning.
* **Cache keys are relocatable when you build with `--reproducible`**: the project folder is written as `@ROOT@` in the key, and the compiler is identified by name and version rather than by
  path, so two machines with different folders share entries. *Without* `--reproducible` the compiler embeds absolute paths in its output, so entries are only shared by builds in the same folder.
* This is a **cache**, not remote execution: nothing is compiled on the server. (See [ADR 0019](adr/0019-reproductibilite-cache-partage.md) for why remote execution is not done.)

## Try it in two minutes

```bash
# on the machine that serves the cache (this machine only, no token needed)
charpente cache serve --port 8765

# on any machine that builds
export CHARPENTE_REMOTE_CACHE=http://127.0.0.1:8765
charpente build --reproducible
charpente cache remote          # shows the address and whether it answers
```

## For a team on a LAN or a CI fleet

```bash
# server: anything other than this machine needs a token, read from an environment variable (never a file or the command line)
export CACHE_TOKEN='a long random string'
charpente cache serve --host 0.0.0.0 --port 8765 --token-env CACHE_TOKEN

# clients
export CHARPENTE_REMOTE_CACHE=http://cache-host:8765
export CHARPENTE_REMOTE_CACHE_TOKEN='the same string'
export CHARPENTE_CACHE_SIGNING_KEY='a second secret shared by the team'    # strongly recommended, see the threat model
```

| Variable | Meaning |
|---|---|
| `CHARPENTE_REMOTE_CACHE` | The server's address (`http://host:port` or `https://...`). Unset: no shared cache. |
| `CHARPENTE_REMOTE_CACHE_TOKEN` | Bearer token sent to the server. |
| `CHARPENTE_CACHE_SIGNING_KEY` | Shared secret. Entries are signed (HMAC-SHA256) when stored and **rejected on read when the signature does not match**. |
| `CHARPENTE_REMOTE_CACHE_MODE` | `readonly`: fetch from the server but never upload (typical for developers; only CI uploads). |
| `CHARPENTE_REMOTE_CACHE_INSECURE` | `1` accepts a plain-`http` server on another machine *without* a signing key. Read the threat model first. |

`charpente cache serve` options: `--dir` (where it keeps files, default `~/.charpente/cache-server`), `--host`, `--port`, `--token-env`, `--readonly` (a mirror that refuses uploads),
`--max-blob` (largest file accepted, default 1 GB).

## Threat model, in plain words

A build cache is trusted with **your binaries**: whoever can write an entry can make other machines link a different object file. So:

| Risk | What protects you | What does not |
|---|---|---|
| A stranger on the network reads or writes the server | Loopback-only by default; another address requires a token (`--token-env`). Uploads are size-limited, names are restricted to safe characters, nothing outside the cache folder is reachable. | There is **no TLS** in the server. A token sent over plain HTTP can be sniffed on an untrusted network. Put the server behind a TLS proxy (nginx, Caddy, a cloud load balancer) and use an `https://` address. |
| A file is corrupted or replaced on the wire or on disk | Every file is named by its digest; the server checks the upload against its name and the client checks the download against it again. | -- |
| A stranger (or a man in the middle) writes an *entry* saying "this action produced that file" | With `CHARPENTE_CACHE_SIGNING_KEY` set on the clients, an entry without a valid signature is ignored. | Without the key, a compromised server can serve wrong binaries for any key. Everyone on the team must share the key, and anyone who holds it can sign entries. |
| The server is compromised | Signed entries cannot be forged without the key; digests stop corrupted files. | A compromised server with a *valid* signing key elsewhere is game over, as with any shared artefact store. Treat the key like a build credential. |
| A plain-`http` address on another machine, no key | Charpente **refuses to use it** (CH8028) unless you set `CHARPENTE_REMOTE_CACHE_INSECURE=1`. | The refusal is the protection: the flag means you accept the risk. |

Nothing secret is ever written to a file by Charpente: the token and the key come from the environment.

## Verified, and not

Verified with real builds: two different project folders sharing entries and producing byte-identical output; a server that is not answering (the build finishes, one warning);
a wrong signature being refused; a wrong token being refused; uploads that do not match their digest being refused; the loopback rule. **Not verified**: `https://` addresses and behaviour behind a TLS proxy, a server that dies in the middle of a transfer,
a server on Linux or macOS, and load with many simultaneous clients.
