"""Engine configuration: everything that's specific to *your* chart/Helm
values layout lives here, loaded from YAML. Everything else (the actual
discovery + naming algorithm) is fixed and lives in engine.py/naming.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PathPart = str | int


@dataclass(frozen=True)
class ScanTarget:
    """One schema location to scan for secrets.

    container: path (keys/indices) to a JSON array, relative to the realm root.
    id_field: the field on each element that identifies it (e.g. "clientId").
    fields: list of paths (relative to the element) that hold a secret value.
            More than one entry means "these fields share one secret" (e.g.
            Keycloak's Apple identity provider stores the same PEM key under
            both config.clientSecret and config.p8Content).
    category_prefix: Pascal-case word used to build the secret key, e.g. "Client".
    field_label: Pascal-case word appended to the secret key, e.g. "ClientSecret".
    strip_suffix: if set, stripped from the identifier before naming (e.g.
                  Keycloak's KeyProvider components are named "hmac-generated").
    """

    container: tuple[PathPart, ...]
    id_field: str
    fields: tuple[tuple[PathPart, ...], ...]
    category_prefix: str
    field_label: str
    values_segment: str
    strip_suffix: str | None = None


@dataclass(frozen=True)
class ManagedConfig:
    """Identifiers matching `prefix` are resolved at runtime by
    keycloak-config-cli itself (IMPORT_VARSUBSTITUTION_ENABLED), via env vars
    backed by a real Kubernetes Secret - never a templated Values placeholder.
    This is opt-in and off by default: most charts don't have this mechanism
    wired up at all, and templating these fields as a Values placeholder
    instead is equally valid (just less good, since the value then has to
    live in a ConfigMap rather than a Secret).

    There is deliberately no default `prefix`/`env_prefix`/`label` - which
    identifiers get this treatment, and what their env vars are called, is
    entirely a convention of *your* deployment pipeline, not a Keycloak or
    keycloak-config-cli standard. (An earlier draft of this tool defaulted
    these to the one specific project it was extracted from's own naming -
    that was a bug, not a sensible default for anyone else.) All three are
    required once `enabled: true`.
    """

    enabled: bool = False
    prefix: str | None = None
    env_prefix: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (("prefix", self.prefix), ("envPrefix", self.env_prefix), ("label", self.label))
            if not value
        ]
        if missing:
            raise ValueError(
                "managed.enabled is true but managed."
                + ", managed.".join(missing)
                + " is not set. There is no default for these - they're your deployment"
                " pipeline's own convention. See README 'Managed/env-substituted secrets'."
            )


DEFAULT_SCAN_TARGETS: tuple[ScanTarget, ...] = (
    ScanTarget(
        container=("clients",),
        id_field="clientId",
        fields=(("secret",),),
        category_prefix="Client",
        field_label="ClientSecret",
        values_segment="clients",
    ),
    ScanTarget(
        container=("identityProviders",),
        id_field="alias",
        fields=(("config", "clientSecret"), ("config", "p8Content")),
        category_prefix="IdentityProvider",
        field_label="ClientSecret",
        values_segment="identityProviders",
    ),
    ScanTarget(
        container=("components", "org.keycloak.keys.KeyProvider"),
        id_field="providerId",
        fields=(("config", "secret", 0),),
        category_prefix="KeyProvider",
        field_label="Secret",
        values_segment="keyProvider",
        strip_suffix="-generated",
    ),
)

DEFAULT_WARNING_SUFFIX_PATTERN = r"(secret|password|credential|privatekey)$"


@dataclass(frozen=True)
class EngineConfig:
    values_path_prefix: str = "keycloakConfigCli.configSecret"
    secret_key_prefix: str = "kc"
    scan_targets: tuple[ScanTarget, ...] = DEFAULT_SCAN_TARGETS
    managed: ManagedConfig = field(default_factory=ManagedConfig)
    warning_suffix_pattern: str = DEFAULT_WARNING_SUFFIX_PATTERN

    @staticmethod
    def default() -> EngineConfig:
        return EngineConfig()

    @staticmethod
    def load(path: Path) -> EngineConfig:
        raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        return EngineConfig._from_dict(raw)

    @staticmethod
    def _from_dict(raw: dict[str, Any]) -> EngineConfig:
        kwargs: dict[str, Any] = {}

        if "valuesPathPrefix" in raw:
            kwargs["values_path_prefix"] = raw["valuesPathPrefix"]
        if "secretKeyPrefix" in raw:
            kwargs["secret_key_prefix"] = raw["secretKeyPrefix"]
        if "warningSuffixPattern" in raw:
            kwargs["warning_suffix_pattern"] = raw["warningSuffixPattern"]

        if "managed" in raw:
            m = raw["managed"]
            kwargs["managed"] = ManagedConfig(
                enabled=m.get("enabled", False),
                prefix=m.get("prefix"),
                env_prefix=m.get("envPrefix"),
                label=m.get("label"),
            )

        if "scanTargets" in raw:
            targets = []
            for t in raw["scanTargets"]:
                targets.append(
                    ScanTarget(
                        container=tuple(t["container"]),
                        id_field=t["idField"],
                        fields=tuple(tuple(f) for f in t["fields"]),
                        category_prefix=t["categoryPrefix"],
                        field_label=t["fieldLabel"],
                        values_segment=t["valuesSegment"],
                        strip_suffix=t.get("stripSuffix"),
                    )
                )
            # Additive, not replacing: the 3 built-in locations cover the
            # vast majority of Keycloak realms, so a config file should only
            # need to list what it wants to ADD.
            kwargs["scan_targets"] = DEFAULT_SCAN_TARGETS + tuple(targets)

        return EngineConfig(**kwargs)
