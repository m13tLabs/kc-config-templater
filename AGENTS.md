# AGENTS.md

Notes for agents (and humans) working on this repo. **Keep this file current:
whenever you change the engine's behavior, config schema, or packaging, update
the relevant section here in the same change.** Stale docs here are worse than
no docs, because the next agent will trust them.

## What this project is

A structural secret-templating engine for `keycloak-config-cli` realm export
JSON (the adorsys import/export format Keycloak Helm charts commonly use).
Given a raw realm export, it finds every secret field by **schema shape**
(client secrets, identity-provider client secrets, key-provider secrets, ...),
not by a hand-maintained map of which client/IdP/provider has which secret,
and replaces each one with a Helm `{{ $.Values... }}` placeholder (or an
`$(env:...)` placeholder for a configurable "managed" subset - see below),
writing the extracted real values to a flat secrets YAML. `render` reverses
this for local testing: splice real values back in from a secrets YAML.

This was extracted from a specific project's (m13t's `infrastructure/iam`
Helm chart) bash+jq implementation on 2026-11-22, generalized, and
rewritten in Python. **If you're an agent working on this repo because of
something you learned in that source project, cross-check `naming.py`,
`config.py`, and `engine.py` before assuming a convention is universal -
see "Deliberately not built in" below.** The `kc-master-*`/`KC_MASTER_*`
convention in particular used to be hardcoded here as a default and was a
real bug (see "Known quirks / gotchas").

## Repo shape

- `src/kc_config_templater/naming.py` - pure string functions
  (`to_pascal`/`to_camel`/`upper_snake`, placeholder read/write/detect). No
  Keycloak-schema knowledge at all; this file only knows about kebab-case
  identifiers and the two placeholder syntaxes.
- `src/kc_config_templater/config.py` - `ScanTarget` (one schema location to
  scan: container path, id field, secret field(s), naming labels),
  `ManagedConfig` (the opt-in env-var-substitution convention), and
  `EngineConfig` (everything a caller can override, loaded from YAML).
  `DEFAULT_SCAN_TARGETS` is the only Keycloak-schema knowledge baked into
  this project as code rather than config - the 3 rows in the README's
  naming-scheme table (clients, identityProviders, KeyProvider).
- `src/kc_config_templater/engine.py` - `templatize()` / `detemplatize()`,
  the actual algorithm. No per-identifier data lives here or anywhere else in
  this project - everything is either structural discovery (walk
  `scan_targets`) or mechanical naming (call into `naming.py`). If you're
  about to add a per-client/per-realm special case, that's very likely the
  wrong fix - see "Collision handling" and "Extending via scanTargets" in the
  README first.
- `src/kc_config_templater/keycloak_client.py` - minimal Admin REST API
  client (`get_admin_token`, `partial_export`). Deliberately not a general
  Keycloak SDK; only what `export` needs.
- `src/kc_config_templater/cli.py` - argparse subcommands `export` (pull from
  live Keycloak + templatize), `template` (templatize a local raw JSON file,
  no live Keycloak needed), `render` (splice real values back in).
- `tests/` - `test_naming.py`, `test_config.py`, `test_engine.py`. The engine
  tests are the ones that matter most for correctness; they include the
  collision-handling and managed-secret round-trip cases, and should grow
  alongside any change to `engine.py`.
- `examples/config.yaml` - a fully-commented `EngineConfig` YAML, including
  the one deliberately-not-enabled `managed` block and a `scanTargets`
  example for an LDAP bind credential. If you add a new config field, add it
  here too, commented the same way.
- `Dockerfile` - multi-stage: build a wheel in a `python:3.12-slim` stage,
  install it into a second slim stage as a non-root `kcct` user,
  `ENTRYPOINT ["kc-config-templater"]`. No source is present in the final
  image, only the installed wheel - if you add a runtime dependency, it
  needs to be in `pyproject.toml`'s `dependencies`, not assumed present.
  `kcct` gets whatever UID `useradd` assigns (1000, the first free one on
  this base image) - it essentially never matches the UID that owns a
  caller's bind-mounted `/work`, so both the CI smoke test and the README's
  `docker run` examples pass `-u "$(id -u):$(id -g)"` to write as the
  caller instead. Without it, writing `--out-templated`/`--out-secrets`
  fails with `PermissionError: [Errno 13] Permission denied` (hit this for
  real in CI, where the runner's UID is 1001).
- `.github/workflows/ci.yml` - pytest+ruff across 3.10/3.11/3.12, plus a
  `docker` job that builds the image and runs a real `template` call through
  it as a smoke test (checks both the placeholder and the secrets YAML
  output against literal expected strings - update both greps if you change
  the naming scheme).
- `.github/workflows/release.yml` - manual `workflow_dispatch` release via
  `m13tLabs/gh-actions-templates`' `docker-release.yml` (version bump,
  changelog, multi-arch build and push to GHCR + Docker Hub, GitHub Release),
  with a `bump_command` that pins `pyproject.toml`'s version to match
  `config.json`, followed by a `publish-pypi` job that builds the wheel from
  the release commit and publishes it via PyPI trusted publishing. Not yet
  exercised - this repo hasn't been pushed/published anywhere yet (see
  "Status" below).
- `cliff.toml` / `CHANGELOG.md` - git-cliff conventional-commit changelog
  generation (house convention for `m13tLabs` OSS projects). Keep commit
  messages conventional (`feat:`, `fix:`, `chore:`, ...) so this stays
  accurate.

## The naming/placeholder scheme (what makes this "structural, no map file")

Every secret location is discovered by walking `config.scan_targets`
(3 built-in + whatever a config file adds), and both the Helm Values path
and the human-readable secret key are derived **mechanically** from the
resource's own Keycloak identifier (clientId / IdP alias / key-provider
providerId) - never from a lookup table:

- Values path segment: `camelCase(identifier)`, e.g.
  `blogs-autoglas-reinhardt` -> `blogsAutoglasReinhardt`.
- Secret key: `secretKeyPrefix + categoryPrefix + PascalCase(identifier) +
  fieldLabel`, e.g. `kcClientBlogsAutoglasReinhardtClientSecret`.
- `categoryPrefix`/`fieldLabel` come from the matching `ScanTarget`, not the
  identifier - that's the only per-schema-location knowledge in the system.

**Collision handling** (`engine._derive_values_naming`): if the
mechanically-derived secret key would collide with a *different* value
already seen earlier in the same `templatize()` call (passed in via
`seen`/`--seed-secrets`, e.g. two realms both having a `github` identity
provider with different secrets), the realm name is appended to the
identifier **before** deriving both the secret key and the Values path -
critical that both come from the same `effective_identifier`, so a
placeholder's secret key is always recoverable from the placeholder text
alone when rendering, with no lookup table needed on that side either. This
means **processing order matters** for which realm gets the disambiguated
name: callers doing multi-realm work (like `export`'s `--seed-secrets` chain)
must process realms in a stable order (e.g. alphabetical), or already-wired
downstream Values keys for a colliding identifier go stale across runs.

**Managed/env-substituted secrets** (`ManagedConfig`, opt-in, off by
default): identifiers matching `managed.prefix` get `$(env:...)` placeholders
instead of Values placeholders - resolved by `keycloak-config-cli` itself at
container start via `IMPORT_VARSUBSTITUTION_ENABLED`, never baked into a
rendered ConfigMap. There is **no default** `prefix`/`envPrefix`/`label` -
see "Known quirks / gotchas" for why that used to be a bug. `fields[0]` of a
managed client's `ScanTarget`, and a managed user's username + first
password-type credential (handled separately in
`_templatize_managed_users`, not a generic `ScanTarget`, because the
credential to use isn't a fixed index), all go through this path when
`managed.enabled` and the identifier matches.

**Unmapped secret-looking fields**: `_find_warnings` flags any scalar whose
*last* path segment matches `warningSuffixPattern` (default:
`(secret|password|credential|privatekey)$`, case-insensitive, suffix-anchored
to avoid false positives like `client.secret.creation.time` or
`passwordPolicy`) and isn't already covered by a scan target or a
placeholder. This is the signal that a chart has a secret-looking field this
tool doesn't know about yet - the fix is a `scanTargets` config entry, not a
code change, unless the field needs genuinely new logic (like the managed-user
handling did).

## Deliberately not built in (config, not code)

Nothing in this list has a sensible universal default - each one is a
convention of the *caller's* deployment pipeline, not a Keycloak or
keycloak-config-cli standard:

- Which identifiers get env-var substitution instead of a Values placeholder
  (`managed.prefix`/`envPrefix`/`label`) - off by default, no default values
  once enabled.
- The Helm Values path prefix (`valuesPathPrefix`, defaults to
  `keycloakConfigCli.configSecret` - that default IS still the originating
  project's own layout; it's a reasonable default to ship since a value has
  to be shipped, but don't read anything into it being "the standard").
- The secret-key prefix (`secretKeyPrefix`, defaults to `"kc"` - same caveat).
- Extra `scanTargets` beyond the 3 built-in schema locations.

If you're adding a new feature and reach for a hardcoded string that looks
like it came from one specific chart's naming convention, it almost
certainly belongs in `EngineConfig` instead. This is the exact mistake found
and fixed in commit `916162c` - see below.

## Known quirks / gotchas

- **`ManagedConfig` used to default to one specific project's own
  convention** (`prefix: "kc-master-"`, `envPrefix: "KC_MASTER_"`,
  `label: "Master"`) - found during an explicit audit for leaked
  project-specific conventions after this tool was extracted, fixed in
  commit `916162c`. The bug existed in **two places that had to be fixed
  together**: the dataclass defaults in `config.py`, and the YAML loader's
  `_from_dict`, which had its own separate `.get("prefix", "kc-master-")`-style
  fallback. If you ever add a new `ManagedConfig` field, check both places
  for the same trap. `ManagedConfig.__post_init__` now raises `ValueError`
  naming exactly which of `prefix`/`envPrefix`/`label` is missing once
  `enabled: true`, so this class of bug fails loudly instead of silently
  inheriting a stale default.
- **`scanTargets` in a config file is additive, not replacing**
  (`EngineConfig._from_dict`: `DEFAULT_SCAN_TARGETS + tuple(targets)`). A
  config file listing `scanTargets` only needs to list what it wants to
  *add* to the 3 built-ins, not restate them. There's a regression test for
  this (`test_custom_scan_targets_are_additive_not_replacing`) because the
  obvious-looking implementation (`kwargs["scan_targets"] = tuple(targets)`)
  silently does the wrong thing and nothing else would catch it.
- **Apple IdP's PEM key maps to two fields, same secret**: Keycloak's Apple
  identity provider stores the same private key under both
  `config.clientSecret` and `config.p8Content` - that's why the
  `identityProviders` `ScanTarget` lists both in `fields` as "entries that
  share one secret." They get the *same* secret key / Values path on
  purpose.
- **`strip_suffix` exists because of Keycloak's own naming, not a user
  convention**: `components."org.keycloak.keys.KeyProvider"[].providerId`
  values look like `hmac-generated`/`aes-generated-generated` -
  `-generated` is Keycloak's own suffix for its auto-created key providers,
  stripped before naming so the secret key reads `kcKeyProviderHmacSecret`
  rather than `kcKeyProviderHmacGeneratedSecret`.
- **This tool cannot templatize a chart file that isn't valid JSON on its
  own.** Some Helm charts (the originating project's included) use an
  *unquoted* `{{ ... | toJson }}` Go-template expression for some field
  (e.g. a redirect-URI array), which is only valid JSON after Go-template
  rendering. `template`/`render` both require genuine JSON input - if a
  caller's chart file has this pattern, they need to render it through Helm
  first (template only works against real Keycloak exports or already-valid
  JSON), not try to feed the tracked chart source into this tool directly.
  This isn't a bug to fix here - real Helm rendering already resolves both
  the `toJson` expression and any secret placeholders in one pass, so there
  is no reason for this tool to special-case it.
- **Container networking for `export`'s `--keycloak-url`**: this tool itself
  does no Docker-specific URL rewriting - that's the caller's job (see the
  originating project's `scripts/kc-export-template.sh`, which rewrites
  `localhost`/`127.0.0.1` to `host.docker.internal` before invoking the
  Docker image, since a bare `localhost` inside the container means the
  container's own loopback). If you add Docker-specific networking logic,
  it belongs in a wrapper script, not in `keycloak_client.py`.

## Status

- Local-only: this repo has not been pushed to GitHub or published to PyPI
  or a container registry yet. `release.yml`'s `docker-release.yml`-based
  GHCR/Docker Hub push and PyPI trusted-publish flow are therefore untested
  end-to-end (the `pypi` environment and PyPI trusted-publisher entry, plus
  the org-level `CI_CLIENT_ID` and `CI_PRIVATE_KEY` GitHub App, still need to
  be set up before the first real run).
- Validated as a genuine drop-in replacement for the jq-based implementation
  it was extracted from: built the wheel, installed into a clean
  non-editable venv, and ran it (via the Docker image, tagged
  `m13t/kc-config-template` by that project's own convention - note the
  tag intentionally differs from this project's own name
  `kc-config-templater`, that's the consuming project's choice, not a typo
  here) against a real live Keycloak + docker-compose stack, producing
  byte-for-byte identical placeholder/secrets output to the prior
  implementation.
- Test suite: 25 tests across `test_naming.py`/`test_config.py`/
  `test_engine.py`, plus the CI `docker` job's smoke test. Keep this number
  roughly current in mind when judging whether a change has adequate
  coverage - a new `ScanTarget` field, a new `EngineConfig` option, or a new
  collision/managed-secret edge case should come with a new test, following
  the existing naming pattern (`test_<behavior>_<condition>`).

## Possible future work (discussed, not started)

- First real release once the org-level secrets/environment above are in
  place and the repo is pushed to GitHub.
- A `detemplatize`/`render` warning for Values placeholders in the input
  that don't match any known `values_path_prefix` + `values_segment`
  combination (today these just end up in `missing` under their raw path
  string, which works but gives a less actionable message than a true
  "unrecognized placeholder" warning would).
