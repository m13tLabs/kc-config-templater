from kc_config_templater.naming import (
    extract_values_path,
    is_placeholder,
    to_camel,
    to_pascal,
    upper_snake,
)


def test_to_pascal():
    assert to_pascal("blogs") == "Blogs"
    assert to_pascal("blogs-autoglas-reinhardt") == "BlogsAutoglasReinhardt"
    assert to_pascal("home-asr") == "HomeAsr"


def test_to_camel():
    assert to_camel("blogs") == "blogs"
    assert to_camel("blogs-autoglas-reinhardt") == "blogsAutoglasReinhardt"
    assert to_camel("home-asr") == "homeAsr"
    assert to_camel("litellm") == "litellm"


def test_upper_snake():
    assert upper_snake("auditor") == "AUDITOR"
    assert upper_snake("master-admin") == "MASTER_ADMIN"


def test_is_placeholder():
    assert is_placeholder("{{ $.Values.x.y }}")
    assert is_placeholder("$(env:FOO)")
    assert not is_placeholder("a-real-secret-value")
    assert not is_placeholder(123)


def test_extract_values_path():
    assert extract_values_path("{{ $.Values.keycloakConfigCli.configSecret.clients.blogs }}") == (
        "keycloakConfigCli.configSecret.clients.blogs"
    )
    assert extract_values_path("not a placeholder") is None
