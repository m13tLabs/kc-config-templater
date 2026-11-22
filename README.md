<p align="center">
  <img src=".github/assets/logo.svg" alt="kc-config-templater" width="500">
</p>

# kc-config-templater

[![CI](https://github.com/m13tLabs/kc-config-templater/actions/workflows/ci.yml/badge.svg)](https://github.com/m13tLabs/kc-config-templater/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/m13t/kc-config-templater)](https://hub.docker.com/r/m13t/kc-config-templater)

Keep secrets out of `keycloak-config-cli` realm exports without hand-maintaining
a map of which client/identity-provider/key has which secret.

## The problem

[`keycloak-config-cli`](https://github.com/adorsys/keycloak-config-cli) imports
Keycloak realm configuration from JSON files that look exactly like Keycloak's
own realm export - which means every client secret, identity-provider secret,
and signing key is sitting in that JSON **in plaintext**. If you commit that
file (e.g. as a Helm chart's ConfigMap source), you've committed your secrets.

The usual fix is to hand-write a list mapping each client to a Helm
`{{ .Values... }}` placeholder, and keep it in sync by hand every time someone
adds a client in the Keycloak admin UI. That list rots the moment someone
forgets to update it - and it already happened at least once in the project
this tool was extracted from (two OAuth client secrets and a private key sat
in plaintext in git for months because they weren't on the list).

## The idea

Don't maintain a list. **Discover secrets structurally** (by schema location
- `clients[].secret`, `identityProviders[].config.clientSecret`, etc. - the
same handful of locations for every Keycloak realm, ever) and **name the
placeholder mechanically** from the thing's own identifier (its `clientId`,
its identity-provider `alias`, ...). A new client shows up with a secret? It
gets templated automatically, with a predictable name, the next time you run
this tool. Nothing to edit.

```jsonc
// before
{ "clientId": "blogs", "secret": "<a real secret value, in plaintext>" }

// after
{ "clientId": "blogs", "secret": "{{ $.Values.keycloakConfigCli.configSecret.clients.blogs }}" }
```

```yaml
# secrets.yaml (generated alongside it)
kcClientBlogsClientSecret: <the real secret value, now only here>
```

## Install

```sh
pip install kc-config-templater
```

Or from source:

```sh
git clone https://github.com/m13tLabs/kc-config-templater
cd kc-config-templater
pip install -e .
```

Or as a container, if you'd rather not install Python locally - it runs as a
non-root user and expects your files under `/work`:

```sh
docker run --rm -v "$PWD":/work ghcr.io/m13tlabs/kc-config-templater \
  template --in-raw raw.json --out-templated templated.json --out-secrets secrets.yaml
```

Published to GHCR and Docker Hub with identical tags each release
(`ghcr.io/m13tlabs/kc-config-templater:<version>|<major.minor>|latest`,
`m13t/kc-config-templater:<version>|<major.minor>|latest`), `linux/amd64` and
`linux/arm64`. Or build it yourself from the `Dockerfile` in this repo.

Every example below using the `kc-config-templater` binary directly works
the same way through
`docker run --rm -v "$PWD":/work ghcr.io/m13tlabs/kc-config-templater ...`
- paths are just relative to `/work` instead of your shell's cwd.

## Usage

### 1. Pull a realm from a running Keycloak and templatize it

```sh
kc-config-templater export \
  --keycloak-url https://keycloak.example.com \
  --admin-user admin --admin-password "$ADMIN_PW" \
  --realm apps \
  --out-raw apps-realm-config.raw.json \
  --out-templated apps-realm-config.json \
  --out-secrets apps-realm-config.secrets.yaml
```

This pulls the realm via Keycloak's Admin REST API (`partial-export`),
writes the full export with real secrets to `--out-raw` (never commit this),
the templated candidate to `--out-templated` (commit this), and the flat
`key: value` secrets it extracted to `--out-secrets` (never commit this -
merge it into whatever secrets store your deployment pipeline uses).

Run it for each realm you have, **in a stable order** (alphabetically by
realm name is the default and recommended - see "Collision handling" below),
threading each realm's `--seed-secrets` from the previous realm's
`--out-secrets` so cross-realm naming collisions get resolved consistently:

```sh
kc-config-templater export --realm apps   --out-secrets apps.secrets.yaml   ...
kc-config-templater export --realm master --out-secrets master.secrets.yaml \
  --seed-secrets apps.secrets.yaml ...
```

It also prints a warning for any secret-looking field name it doesn't
recognize (see "Extending" below) - that's your signal to either add a
`scanTargets` entry for it, or decide it's not actually sensitive.

### 2. Render a templated file back to real values

Useful for local testing (e.g. feeding it into a docker-compose Keycloak), or
for verifying a round-trip didn't lose anything:

```sh
kc-config-templater render \
  --templated apps-realm-config.json \
  --secrets apps-realm-config.secrets.yaml \
  --out apps-realm-config.rendered.json
```

`$(env:...)` placeholders (see "Managed/env-substituted secrets" below) are
left untouched - they're meant to be resolved by `keycloak-config-cli` itself
at import time, not by this tool.

### 3. Verify nothing was lost

Pull the realm again after importing the rendered file somewhere, and diff:

```sh
diff <(jq -S 'walk(if type=="object" then del(.id) else . end)' apps-realm-config.raw.json) \
     <(jq -S 'walk(if type=="object" then del(.id) else . end)' apps-realm-config.reimported.json)
```

(`id` fields are Keycloak-assigned UUIDs, regenerated on every import - strip
them before comparing.)

## How placeholders are named

Every identifier (`clientId`, identity-provider `alias`, key-provider
`providerId`) is kebab-case. The Helm Values path segment is its camelCase
form; the secret key used in the generated secrets file is
`kc<CategoryPrefix><PascalCase(identifier)><FieldLabel>`:

| Schema location | identifier field | category prefix | field label |
|---|---|---|---|
| `clients[].secret` | `clientId` | `Client` | `ClientSecret` |
| `identityProviders[].config.clientSecret` / `.p8Content` | `alias` | `IdentityProvider` | `ClientSecret` |
| `components."org.keycloak.keys.KeyProvider"[].config.secret[0]` | `providerId` minus `-generated` | `KeyProvider` | `Secret` |

e.g. identifier `blogs-autoglas-reinhardt` -> Values path
`keycloakConfigCli.configSecret.clients.blogsAutoglasReinhardt`, secret key
`kcClientBlogsAutoglasReinhardtClientSecret`.

### Collision handling

Two realms can reasonably have, say, a `github` identity provider each, with
two different secrets. If the second realm processed would otherwise produce
the same secret key as an already-seen *different* value, its realm name is
appended to the identifier before naming - to **both** the Values path and
the secret key, so the secret key is always recoverable from the placeholder
text alone (no lookup table needed to render it back). This makes processing
order matter: **always process realms in the same order** (alphabetically by
realm name, by default) or already-wired Values keys for a colliding
identifier will drift.

### Managed/env-substituted secrets

Some setups wire specific identifiers (by whatever naming convention *they*
use - there's no standard one) to real Kubernetes Secrets via
`keycloak-config-cli`'s own `IMPORT_VARSUBSTITUTION_ENABLED` env-var
substitution, instead of a Helm Values placeholder - strictly better, since
the secret then never touches a ConfigMap. This is **off by default** (most
charts don't have this wired up), and `prefix`/`envPrefix`/`label` have **no
default** once enabled - there's nothing universal to default them to, so
you must set all three to your own convention or `kc-config-templater`
refuses to run:

```yaml
managed:
  enabled: true
  prefix: "sys-"        # e.g. a client named "sys-reporter" is "managed"
  envPrefix: "SYS_"      # -> SYS_REPORTER_SECRET_NAME / SYS_REPORTER_SECRET_VALUE
  label: "Sys"           # used only for the human-readable generated secret key
```

## Configuration

All of the above is configurable via `--config path/to/config.yaml` (see
`examples/config.yaml`), because the Values-path prefix
(`keycloakConfigCli.configSecret` by default) and the schema locations are
specific to *your* Helm chart layout, not a Keycloak standard.

## Extending

Found a secret-looking field this tool doesn't know about (it'll warn you
with the field name and a short, non-sensitive preview)? Add a `scanTargets`
entry in your config - no code changes needed:

```yaml
scanTargets:
  - container: ["components", "org.keycloak.storage.UserStorageProvider"]
    idField: "name"
    fields: [["config", "bindCredential", 0]]
    categoryPrefix: "LdapProvider"
    fieldLabel: "BindCredential"
    valuesSegment: "ldapProvider"
```

## Development

```sh
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT
