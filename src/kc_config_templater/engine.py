"""The actual templatize/detemplatize algorithm.

No per-client, per-identity-provider, or per-key-provider data lives here or
anywhere else in this project. Every secret location is discovered
structurally (see config.DEFAULT_SCAN_TARGETS for the handful of Keycloak
schema locations this knows about) and named mechanically from the
resource's own identifier (see naming.py). The only thing that varies
instance-to-instance is the EngineConfig a caller supplies.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from .config import EngineConfig, ScanTarget
from .naming import (
    env_placeholder,
    extract_values_path,
    is_placeholder,
    pascal_word,
    secret_group_key,
    to_camel,
    to_pascal,
    upper_snake,
    values_placeholder,
)

Json = dict[str, Any]
PathTuple = tuple[Any, ...]


@dataclass
class Warning_:
    path: PathTuple
    preview: str


@dataclass
class TemplatizeResult:
    templated: Json
    secrets: dict[str, str]
    secret_tree: dict[str, Any]
    warnings: list[Warning_]


@dataclass
class DetemplatizeResult:
    rendered: Json
    missing: list[str]


def get_path(doc: Any, path: PathTuple) -> Any:
    cur = doc
    for key in path:
        if isinstance(cur, dict):
            if key not in cur:
                return None
            cur = cur[key]
        elif isinstance(cur, list):
            if not isinstance(key, int) or key < 0 or key >= len(cur):
                return None
            cur = cur[key]
        else:
            return None
    return cur


def set_path(doc: Any, path: PathTuple, value: Any) -> None:
    cur = doc
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value


def _effective_id(target: ScanTarget, identifier: str) -> str:
    if target.strip_suffix and identifier.endswith(target.strip_suffix):
        return identifier[: -len(target.strip_suffix)]
    return identifier


def _derive_values_naming(
    config: EngineConfig,
    target: ScanTarget,
    identifier: str,
    realm: str,
    seen: dict[str, str],
    value: str,
) -> tuple[str, str, str]:
    """Returns (secret_key, values_path, effective_identifier). secret_key
    and values_path are both derived from the same effective identifier so
    detemplatize can reverse this from the path text alone - see README
    "Collision handling"."""
    plain_key = f"{config.secret_key_prefix}{target.category_prefix}{to_pascal(identifier)}{target.field_label}"
    if plain_key in seen and seen[plain_key] != value:
        effective_identifier = f"{identifier}-{realm}"
    else:
        effective_identifier = identifier

    secret_key = (
        f"{config.secret_key_prefix}{target.category_prefix}"
        f"{to_pascal(effective_identifier)}{target.field_label}"
    )
    values_path = f"{config.values_path_prefix}.{target.values_segment}.{to_camel(effective_identifier)}"
    return secret_key, values_path, effective_identifier


def _add_to_tree(
    tree: dict[str, Any],
    config: EngineConfig,
    category_prefix: str,
    identifier: str,
    secret_key: str,
    value: str,
) -> None:
    """Adds one secret to the write-ready secrets structure, flat or grouped
    by category depending on config.secret_structure - see
    EngineConfig.secret_structure."""
    if config.secret_structure != "nested":
        tree[secret_key] = value
        return

    group = secret_group_key(config.secret_key_prefix, category_prefix)
    leaf = to_camel(identifier)
    bucket = tree.setdefault(group, {})
    if leaf in bucket and bucket[leaf] != value:
        raise ValueError(
            f"Nested secret structure collision: {group}.{leaf} would get two different "
            "values. Two scanTargets probably share a categoryPrefix but use different "
            "fieldLabels for the same identifier - give them distinct categoryPrefix "
            "values, or use secretStructure: flat."
        )
    bucket[leaf] = value


def _managed_env_vars(config: EngineConfig, identifier: str) -> tuple[str, str]:
    suffix = identifier[len(config.managed.prefix) :]
    name_var = f"{config.managed.env_prefix}{upper_snake(suffix)}_SECRET_NAME"
    value_var = f"{config.managed.env_prefix}{upper_snake(suffix)}_SECRET_VALUE"
    return name_var, value_var


def _is_managed(config: EngineConfig, identifier: str) -> bool:
    return config.managed.enabled and identifier.startswith(config.managed.prefix)


def templatize(raw: Json, config: EngineConfig, seen: dict[str, str] | None = None) -> TemplatizeResult:
    """Scan `raw` (one realm's keycloak-config-cli export) and replace every
    secret field it recognizes with a placeholder. `seen` carries secrets
    already collected from other realms processed earlier in the same run,
    so that identifiers reused across realms with different values (e.g.
    both realms having a "github" identity provider) get disambiguated
    instead of silently colliding - see README "Collision handling"."""
    seen = dict(seen or {})
    doc = copy.deepcopy(raw)
    secrets: dict[str, str] = {}
    secret_tree: dict[str, Any] = {}
    covered: set[PathTuple] = set()
    realm = raw.get("realm", "unknown")

    for target in config.scan_targets:
        elements = get_path(doc, target.container)
        if not isinstance(elements, list):
            continue
        for idx, element in enumerate(elements):
            if not isinstance(element, dict):
                continue
            raw_identifier = element.get(target.id_field)
            if not isinstance(raw_identifier, str):
                continue
            identifier = _effective_id(target, raw_identifier)
            managed = _is_managed(config, raw_identifier)

            if managed and target.id_field:
                id_path = target.container + (idx, target.id_field)
                if not is_placeholder(get_path(doc, id_path)):
                    name_var, _ = _managed_env_vars(config, raw_identifier)
                    set_path(doc, id_path, env_placeholder(name_var))
                    covered.add(id_path)

            for field_path_rel in target.fields:
                field_path = target.container + (idx,) + field_path_rel
                original = get_path(doc, field_path)
                if original is None or is_placeholder(original):
                    continue

                if managed:
                    _, value_var = _managed_env_vars(config, raw_identifier)
                    placeholder = env_placeholder(value_var)
                    secret_key = (
                        f"{config.secret_key_prefix}{config.managed.label}"
                        f"{to_pascal(identifier[len(config.managed.prefix) :])}{target.field_label}"
                    )
                    # Managed secrets stay flat regardless of secret_structure - see
                    # EngineConfig.secret_structure.
                    secret_tree[secret_key] = original
                else:
                    secret_key, values_path, effective_identifier = _derive_values_naming(
                        config, target, identifier, realm, {**seen, **secrets}, original
                    )
                    placeholder = values_placeholder(values_path)
                    _add_to_tree(
                        secret_tree, config, target.category_prefix, effective_identifier, secret_key, original
                    )

                set_path(doc, field_path, placeholder)
                secrets[secret_key] = original
                covered.add(field_path)

    if config.managed.enabled:
        _templatize_managed_users(doc, config, secrets, secret_tree, covered)

    warnings = _find_warnings(raw, config, covered)
    return TemplatizeResult(templated=doc, secrets=secrets, secret_tree=secret_tree, warnings=warnings)


def _templatize_managed_users(
    doc: Json,
    config: EngineConfig,
    secrets: dict[str, str],
    secret_tree: dict[str, Any],
    covered: set[PathTuple],
) -> None:
    """Users whose username starts with the managed prefix (e.g.
    "kc-master-admin") get their username and first password credential
    env-substituted, mirroring how managed clients are handled above. Not a
    generic ScanTarget because the credential to use isn't a fixed index -
    it's "the first credential of type password"."""
    users = doc.get("users")
    if not isinstance(users, list):
        return
    for idx, user in enumerate(users):
        if not isinstance(user, dict):
            continue
        username = user.get("username")
        if not isinstance(username, str) or not _is_managed(config, username):
            continue

        name_path = ("users", idx, "username")
        if not is_placeholder(get_path(doc, name_path)):
            name_var, _ = _managed_env_vars(config, username)
            set_path(doc, name_path, env_placeholder(name_var))
            covered.add(name_path)

        credentials = user.get("credentials") or []
        cred_idx = next(
            (i for i, c in enumerate(credentials) if isinstance(c, dict) and c.get("type") == "password"),
            None,
        )
        if cred_idx is None:
            continue
        value_path = ("users", idx, "credentials", cred_idx, "value")
        original = get_path(doc, value_path)
        if original is None or is_placeholder(original):
            continue
        _, value_var = _managed_env_vars(config, username)
        suffix = username[len(config.managed.prefix) :]
        secret_key = f"{config.secret_key_prefix}{config.managed.label}{to_pascal(suffix)}Password"
        set_path(doc, value_path, env_placeholder(value_var))
        secrets[secret_key] = original
        # Managed secrets stay flat regardless of secret_structure - see
        # EngineConfig.secret_structure.
        secret_tree[secret_key] = original
        covered.add(value_path)


def _iter_leaf_paths(doc: Any, prefix: PathTuple = ()) -> list[tuple[PathTuple, Any]]:
    out: list[tuple[PathTuple, Any]] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            out.extend(_iter_leaf_paths(value, prefix + (key,)))
    elif isinstance(doc, list):
        for idx, value in enumerate(doc):
            out.extend(_iter_leaf_paths(value, prefix + (idx,)))
    else:
        out.append((prefix, doc))
    return out


def _find_warnings(raw: Json, config: EngineConfig, covered: set[PathTuple]) -> list[Warning_]:
    pattern = re.compile(config.warning_suffix_pattern, re.IGNORECASE)
    warnings: list[Warning_] = []
    for path, value in _iter_leaf_paths(raw):
        if not path:
            continue
        last_key = str(path[-1])
        if not pattern.search(last_key):
            continue
        if is_placeholder(value):
            continue
        if path in covered:
            continue
        if isinstance(value, str) and value:
            preview = f"{value[:4]}...({len(value)} chars)"
        else:
            preview = repr(value)
        warnings.append(Warning_(path=path, preview=preview))
    return warnings


def _group_category_lookup(config: EngineConfig) -> dict[str, tuple[str, str]]:
    """group key (as produced by secret_group_key) -> (category_prefix, field_label)."""
    return {
        secret_group_key(config.secret_key_prefix, t.category_prefix): (t.category_prefix, t.field_label)
        for t in config.scan_targets
    }


def flatten_secrets(data: dict[str, Any], config: EngineConfig) -> dict[str, str]:
    """Flattens a secrets mapping loaded from disk - which may be fully flat
    (secretStructure: flat, or an older file), fully nested (secretStructure:
    nested), or a mix (managed secrets are always flat scalars even in
    nested mode, see EngineConfig.secret_structure) - back into the flat
    secret_key -> value form the rest of this module works with."""
    lookup = _group_category_lookup(config)
    flat: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            flat[key] = value
            continue
        if key not in lookup:
            raise ValueError(
                f"Unknown secret group {key!r} in secrets file - no scanTarget's "
                "categoryPrefix produces this group name with the current config."
            )
        category_prefix, field_label = lookup[key]
        for leaf, leaf_value in value.items():
            flat[f"{config.secret_key_prefix}{category_prefix}{pascal_word(leaf)}{field_label}"] = leaf_value
    return flat


# --- detemplatize -----------------------------------------------------------

_CATEGORY_LOOKUP_CACHE: dict[int, dict[str, tuple[str, str]]] = {}


def _category_lookup(config: EngineConfig) -> dict[str, tuple[str, str]]:
    """values_segment-qualified prefix -> (category_prefix, field_label)."""
    key = id(config)
    if key not in _CATEGORY_LOOKUP_CACHE:
        _CATEGORY_LOOKUP_CACHE[key] = {
            f"{config.values_path_prefix}.{t.values_segment}": (t.category_prefix, t.field_label)
            for t in config.scan_targets
        }
    return _CATEGORY_LOOKUP_CACHE[key]


def _secret_key_for_path(config: EngineConfig, path: str) -> str | None:
    prefix, _, identifier_camel = path.rpartition(".")
    info = _category_lookup(config).get(prefix)
    if info is None:
        return None
    category_prefix, field_label = info
    return f"{config.secret_key_prefix}{category_prefix}{pascal_word(identifier_camel)}{field_label}"


def detemplatize(templated: Json, config: EngineConfig, secrets: dict[str, str]) -> DetemplatizeResult:
    """Reverse of templatize(): splices real values back into a templated
    document. $(env:...) placeholders are left untouched on purpose -
    they're resolved by keycloak-config-cli itself at runtime, not by this
    tool."""
    doc = copy.deepcopy(templated)
    missing: list[str] = []

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            path = extract_values_path(node)
            if path is None:
                return node
            key = _secret_key_for_path(config, path)
            if key is not None and key in secrets:
                return secrets[key]
            missing.append(key or path)
            return node
        return node

    rendered = walk(doc)
    return DetemplatizeResult(rendered=rendered, missing=sorted(set(missing)))
