from pathlib import Path

import pytest

from kc_config_templater.config import DEFAULT_SCAN_TARGETS, EngineConfig, ManagedConfig


def test_default_config():
    config = EngineConfig.default()
    assert config.values_path_prefix == "keycloakConfigCli.configSecret"
    assert config.managed.enabled is False
    assert config.scan_targets == DEFAULT_SCAN_TARGETS
    assert config.secret_structure == "flat"


def test_load_overrides_values_path_prefix_and_managed(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
valuesPathPrefix: myChart.secrets
managed:
  enabled: true
  prefix: "sys-"
  envPrefix: "SYS_"
  label: "System"
"""
    )
    config = EngineConfig.load(config_file)
    assert config.values_path_prefix == "myChart.secrets"
    assert config.managed.enabled is True
    assert config.managed.prefix == "sys-"
    assert config.managed.env_prefix == "SYS_"
    assert config.managed.label == "System"
    # untouched defaults still present
    assert config.scan_targets == DEFAULT_SCAN_TARGETS


def test_custom_scan_targets_are_additive_not_replacing(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
scanTargets:
  - container: ["components", "org.keycloak.storage.UserStorageProvider"]
    idField: "name"
    fields: [["config", "bindCredential", 0]]
    categoryPrefix: "LdapProvider"
    fieldLabel: "BindCredential"
    valuesSegment: "ldapProvider"
"""
    )
    config = EngineConfig.load(config_file)
    assert len(config.scan_targets) == len(DEFAULT_SCAN_TARGETS) + 1
    for target in DEFAULT_SCAN_TARGETS:
        assert target in config.scan_targets
    custom = config.scan_targets[-1]
    assert custom.category_prefix == "LdapProvider"
    assert custom.values_segment == "ldapProvider"


def test_managed_enabled_without_prefix_raises():
    with pytest.raises(ValueError, match="managed.prefix"):
        ManagedConfig(enabled=True)


def test_managed_enabled_with_all_fields_is_fine():
    m = ManagedConfig(enabled=True, prefix="sys-", env_prefix="SYS_", label="System")
    assert m.prefix == "sys-"


def test_managed_disabled_requires_nothing():
    ManagedConfig(enabled=False)  # must not raise


def test_load_overrides_secret_structure(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("secretStructure: nested\n")
    config = EngineConfig.load(config_file)
    assert config.secret_structure == "nested"


def test_invalid_secret_structure_raises():
    with pytest.raises(ValueError, match="secret_structure"):
        EngineConfig(secret_structure="bogus")
