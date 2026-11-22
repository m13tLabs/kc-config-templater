import copy

from kc_config_templater.config import EngineConfig, ManagedConfig
from kc_config_templater.engine import detemplatize, templatize

APPS_RAW = {
    "realm": "apps",
    "clients": [
        {"clientId": "blogs", "secret": "realBlogsSecret333"},
        {"clientId": "blogs-autoglas-reinhardt", "secret": "realAsrSecret444"},
        {"clientId": "account", "publicClient": True},  # no "secret" field at all
    ],
    "identityProviders": [
        {"alias": "github", "config": {"clientSecret": "appsGithubSecretBBB"}},
        {
            "alias": "apple",
            "config": {"clientSecret": "applePemCCC", "p8Content": "applePemCCC"},
        },
    ],
    "components": {
        "org.keycloak.keys.KeyProvider": [
            {"providerId": "hmac-generated", "config": {"secret": ["hmacSecretDDD"]}},
            {"providerId": "aes-generated", "config": {"secret": ["aesSecretEEE"]}},
        ]
    },
    "passwordPolicy": "length(12)",  # must NOT trigger a warning (suffix doesn't match)
    "someClient": {"attributes": {"client.secret.creation.time": "1700000000"}},  # noise
}

MASTER_RAW = {
    "realm": "master",
    "clients": [{"clientId": "kc-master-auditor", "secret": "realAuditorSecret111"}],
    "identityProviders": [{"alias": "github", "config": {"clientSecret": "masterGithubSecretAAA"}}],
    "users": [
        {
            "username": "kc-master-admin",
            "credentials": [{"type": "password", "value": "realAdminPass222"}],
        }
    ],
}


def default_config() -> EngineConfig:
    return EngineConfig.default()


def managed_config() -> EngineConfig:
    return EngineConfig(managed=ManagedConfig(enabled=True))


def test_templatize_basic_client_secret():
    result = templatize(APPS_RAW, default_config())
    blogs = next(c for c in result.templated["clients"] if c["clientId"] == "blogs")
    assert blogs["secret"] == "{{ $.Values.keycloakConfigCli.configSecret.clients.blogs }}"
    assert result.secrets["kcClientBlogsClientSecret"] == "realBlogsSecret333"


def test_templatize_mechanical_naming_for_multiword_identifier():
    result = templatize(APPS_RAW, default_config())
    asr = next(c for c in result.templated["clients"] if c["clientId"] == "blogs-autoglas-reinhardt")
    assert asr["secret"] == (
        "{{ $.Values.keycloakConfigCli.configSecret.clients.blogsAutoglasReinhardt }}"
    )
    assert result.secrets["kcClientBlogsAutoglasReinhardtClientSecret"] == "realAsrSecret444"


def test_public_client_without_secret_is_untouched():
    result = templatize(APPS_RAW, default_config())
    account = next(c for c in result.templated["clients"] if c["clientId"] == "account")
    assert "secret" not in account


def test_apple_idp_shares_one_secret_key_across_two_fields():
    result = templatize(APPS_RAW, default_config())
    apple = next(p for p in result.templated["identityProviders"] if p["alias"] == "apple")
    assert apple["config"]["clientSecret"] == apple["config"]["p8Content"]
    assert apple["config"]["clientSecret"] == (
        "{{ $.Values.keycloakConfigCli.configSecret.identityProviders.apple }}"
    )
    assert result.secrets["kcIdentityProviderAppleClientSecret"] == "applePemCCC"


def test_key_provider_strips_generated_suffix():
    result = templatize(APPS_RAW, default_config())
    components = result.templated["components"]["org.keycloak.keys.KeyProvider"]
    hmac = next(c for c in components if c["providerId"] == "hmac-generated")
    assert hmac["config"]["secret"][0] == (
        "{{ $.Values.keycloakConfigCli.configSecret.keyProvider.hmac }}"
    )
    assert result.secrets["kcKeyProviderHmacSecret"] == "hmacSecretDDD"


def test_no_false_positive_warnings():
    result = templatize(APPS_RAW, default_config())
    warning_paths = [w.path for w in result.warnings]
    assert ("passwordPolicy",) not in warning_paths
    assert ("someClient", "attributes", "client.secret.creation.time") not in warning_paths
    # every genuine secret field should be covered (so: no warnings at all here)
    assert result.warnings == []


def test_warning_for_unmapped_secret_field():
    raw = copy.deepcopy(APPS_RAW)
    raw["someOtherThing"] = {"bindCredential": "lurkingLdapSecret"}
    result = templatize(raw, default_config())
    warning_paths = [w.path for w in result.warnings]
    assert ("someOtherThing", "bindCredential") in warning_paths
    # and the real value is never included in the warning, only a short preview
    preview = next(w.preview for w in result.warnings if w.path == ("someOtherThing", "bindCredential"))
    assert "lurkingLdapSecret" not in preview


def test_managed_client_uses_env_placeholders_not_values():
    result = templatize(MASTER_RAW, managed_config())
    auditor = result.templated["clients"][0]
    assert auditor["clientId"] == "$(env:KC_MASTER_AUDITOR_SECRET_NAME)"
    assert auditor["secret"] == "$(env:KC_MASTER_AUDITOR_SECRET_VALUE)"
    assert result.secrets["kcMasterAuditorClientSecret"] == "realAuditorSecret111"


def test_managed_user_password_uses_env_placeholders():
    result = templatize(MASTER_RAW, managed_config())
    admin = result.templated["users"][0]
    assert admin["username"] == "$(env:KC_MASTER_ADMIN_SECRET_NAME)"
    assert admin["credentials"][0]["value"] == "$(env:KC_MASTER_ADMIN_SECRET_VALUE)"
    assert result.secrets["kcMasterAdminPassword"] == "realAdminPass222"


def test_managed_disabled_by_default_falls_back_to_values_placeholder():
    result = templatize(MASTER_RAW, default_config())
    auditor = result.templated["clients"][0]
    # not env-substituted - templated like any other client, since "managed" is opt-in
    assert auditor["secret"] == (
        "{{ $.Values.keycloakConfigCli.configSecret.clients.kcMasterAuditor }}"
    )


def test_collision_across_realms_appends_realm_name_consistently():
    config = default_config()
    apps_result = templatize(APPS_RAW, config)  # processed first: plain names
    apps_idp = next(p for p in apps_result.templated["identityProviders"] if p["alias"] == "github")
    assert apps_idp["config"]["clientSecret"] == (
        "{{ $.Values.keycloakConfigCli.configSecret.identityProviders.github }}"
    )
    assert apps_result.secrets["kcIdentityProviderGithubClientSecret"] == "appsGithubSecretBBB"

    master_result = templatize(MASTER_RAW, config, seen=apps_result.secrets)
    master_idp = next(
        p for p in master_result.templated["identityProviders"] if p["alias"] == "github"
    )
    assert master_idp["config"]["clientSecret"] == (
        "{{ $.Values.keycloakConfigCli.configSecret.identityProviders.githubMaster }}"
    )
    assert master_result.secrets["kcIdentityProviderGithubMasterClientSecret"] == "masterGithubSecretAAA"
    # the plain name must NOT reappear in master's own secrets - no silent merge
    assert "kcIdentityProviderGithubClientSecret" not in master_result.secrets


def test_round_trip_identity_with_collision():
    config = default_config()
    apps_result = templatize(APPS_RAW, config)
    detemplatize_result = detemplatize(apps_result.templated, config, apps_result.secrets)
    assert detemplatize_result.missing == []
    assert detemplatize_result.rendered == APPS_RAW


def test_round_trip_missing_secret_is_reported_and_left_as_placeholder():
    config = default_config()
    result = templatize(APPS_RAW, config)
    partial_secrets = dict(result.secrets)
    del partial_secrets["kcClientBlogsClientSecret"]

    rendered = detemplatize(result.templated, config, partial_secrets)
    assert "kcClientBlogsClientSecret" in rendered.missing
    blogs = next(c for c in rendered.rendered["clients"] if c["clientId"] == "blogs")
    assert blogs["secret"] == "{{ $.Values.keycloakConfigCli.configSecret.clients.blogs }}"


def test_round_trip_through_realistic_cross_realm_run():
    """templatize both realms in order, then detemplatize each and compare
    against the original raw doc - the full, realistic use of this tool."""
    config = default_config()
    apps_result = templatize(APPS_RAW, config)
    master_result = templatize(MASTER_RAW, config, seen=apps_result.secrets)

    apps_back = detemplatize(apps_result.templated, config, apps_result.secrets)
    assert apps_back.rendered == APPS_RAW

    master_back = detemplatize(master_result.templated, config, master_result.secrets)
    assert master_back.rendered == MASTER_RAW
