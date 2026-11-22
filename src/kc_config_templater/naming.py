"""Mechanical name derivation shared by the templatize and detemplatize engines.

Every identifier Keycloak hands us (a clientId, an identity-provider alias, a
key-provider providerId, ...) is assumed kebab-case. Everything downstream -
the Helm/Values-style placeholder path and the human-readable secret key used
in the generated secrets file - is derived from that identifier mechanically,
by the rules below, and nowhere else. There is deliberately no per-identifier
lookup table anywhere in this project: if you find yourself wanting one,
something about these rules needs to change instead.
"""

from __future__ import annotations

import re


def pascal_word(word: str) -> str:
    """Upper-case just the first character; leaves the rest untouched."""
    if not word:
        return ""
    return word[0].upper() + word[1:]


def to_pascal(identifier: str) -> str:
    """kebab-case -> PascalCase, e.g. 'blogs-autoglas-reinhardt' -> 'BlogsAutoglasReinhardt'."""
    return "".join(pascal_word(part) for part in identifier.split("-"))


def to_camel(identifier: str) -> str:
    """kebab-case -> camelCase, e.g. 'home-asr' -> 'homeAsr'."""
    parts = identifier.split("-")
    if not parts:
        return ""
    return parts[0] + "".join(pascal_word(part) for part in parts[1:])


def upper_snake(identifier: str) -> str:
    """kebab-case -> UPPER_SNAKE_CASE, e.g. 'auditor' -> 'AUDITOR', 'master-admin' -> 'MASTER_ADMIN'."""
    return "_".join(identifier.split("-")).upper()


def secret_group_key(secret_key_prefix: str, category_prefix: str) -> str:
    """Top-level key a category's secrets are grouped under in the "nested"
    secrets-file structure, e.g. ('kc', 'Client') -> 'kcClientSecrets'."""
    return f"{secret_key_prefix}{category_prefix}Secrets"


_PLACEHOLDER_VALUES_RE = re.compile(r"^\{\{ \$\.Values\.([A-Za-z0-9_.]+) \}\}$")
_PLACEHOLDER_ENV_RE = re.compile(r"^\$\(env:([A-Za-z0-9_]+)\)$")


def is_placeholder(value: object) -> bool:
    """True if `value` is already a templated placeholder of either kind."""
    if not isinstance(value, str):
        return False
    return value.startswith(("{{", "$(env:"))


def values_placeholder(path: str) -> str:
    return f"{{{{ $.Values.{path} }}}}"


def env_placeholder(var_name: str) -> str:
    return f"$(env:{var_name})"


def extract_values_path(placeholder: str) -> str | None:
    match = _PLACEHOLDER_VALUES_RE.match(placeholder)
    return match.group(1) if match else None


def extract_env_var(placeholder: str) -> str | None:
    match = _PLACEHOLDER_ENV_RE.match(placeholder)
    return match.group(1) if match else None
