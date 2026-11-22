from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .config import EngineConfig
from .engine import DetemplatizeResult, TemplatizeResult, detemplatize, templatize


def _load_config(path: str | None) -> EngineConfig:
    return EngineConfig.load(Path(path)) if path else EngineConfig.default()


def _load_secrets(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Error: {path} does not contain a flat mapping of key: value secrets.")
    return data


def _write_json(path: str, data: object) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def _write_secrets_yaml(path: str, secrets: dict[str, str]) -> None:
    Path(path).write_text(yaml.safe_dump(secrets, sort_keys=False, default_flow_style=False))


def _report_templatize(result: TemplatizeResult, out_secrets: str) -> None:
    if result.warnings:
        print(
            f"Warning: {len(result.warnings)} secret-looking field(s) not covered by any "
            "scan target:",
            file=sys.stderr,
        )
        for w in result.warnings:
            path_str = ".".join(str(p) for p in w.path)
            print(f"  {path_str}  ({w.preview})", file=sys.stderr)
        print(
            "If these are real secrets, add a scanTargets entry for them in your config.",
            file=sys.stderr,
        )
    print(f"Templated {len(result.secrets)} secret(s). Wrote secrets to {out_secrets}.")


def cmd_export(args: argparse.Namespace) -> None:
    from .keycloak_client import get_admin_token, partial_export

    config = _load_config(args.config)
    seen = _load_secrets(args.seed_secrets)

    token = get_admin_token(args.keycloak_url, args.admin_user, args.admin_password)
    raw = partial_export(args.keycloak_url, token, args.realm)

    if args.out_raw:
        _write_json(args.out_raw, raw)

    result = templatize(raw, config, seen=seen)
    _write_json(args.out_templated, result.templated)
    _write_secrets_yaml(args.out_secrets, result.secrets)
    _report_templatize(result, args.out_secrets)


def cmd_template(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    seen = _load_secrets(args.seed_secrets)
    raw = json.loads(Path(args.in_raw).read_text())

    result = templatize(raw, config, seen=seen)
    _write_json(args.out_templated, result.templated)
    _write_secrets_yaml(args.out_secrets, result.secrets)
    _report_templatize(result, args.out_secrets)


def cmd_render(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    secrets = _load_secrets(args.secrets)
    templated = json.loads(Path(args.templated).read_text())

    result: DetemplatizeResult = detemplatize(templated, config, secrets)
    _write_json(args.out, result.rendered)

    if result.missing:
        print(
            f"Warning: {len(result.missing)} secret(s) have no value in {args.secrets}, "
            "left as unrendered placeholders:",
            file=sys.stderr,
        )
        for key in result.missing:
            print(f"  {key}", file=sys.stderr)
    else:
        print(f"Rendered {args.out} with no missing secrets.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kc-config-templater",
        description=(
            "Structurally discover and templatize secrets in keycloak-config-cli "
            "realm exports."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_only = argparse.ArgumentParser(add_help=False)
    config_only.add_argument("--config", help="Path to a YAML EngineConfig override file.")

    with_seed_secrets = argparse.ArgumentParser(add_help=False, parents=[config_only])
    with_seed_secrets.add_argument(
        "--seed-secrets",
        help=(
            "Secrets YAML from a realm already processed earlier in this run, so cross-realm "
            "naming collisions are resolved consistently. Process realms in a stable order."
        ),
    )

    export_parser = subparsers.add_parser(
        "export",
        parents=[with_seed_secrets],
        help="Pull a realm from a running Keycloak via the Admin REST API and templatize it.",
    )
    export_parser.add_argument("--keycloak-url", required=True)
    export_parser.add_argument("--admin-user", required=True)
    export_parser.add_argument("--admin-password", required=True)
    export_parser.add_argument("--realm", required=True)
    export_parser.add_argument("--out-raw", help="Where to write the full export with real secrets.")
    export_parser.add_argument("--out-templated", required=True)
    export_parser.add_argument("--out-secrets", required=True)
    export_parser.set_defaults(func=cmd_export)

    template_parser = subparsers.add_parser(
        "template",
        parents=[with_seed_secrets],
        help="Templatize a realm export you already have locally (no live Keycloak needed).",
    )
    template_parser.add_argument("--in-raw", required=True)
    template_parser.add_argument("--out-templated", required=True)
    template_parser.add_argument("--out-secrets", required=True)
    template_parser.set_defaults(func=cmd_template)

    render_parser = subparsers.add_parser(
        "render",
        parents=[config_only],
        help="Splice real values from a secrets YAML back into a templated realm export.",
    )
    render_parser.add_argument("--templated", required=True)
    render_parser.add_argument("--secrets", required=True)
    render_parser.add_argument("--out", required=True)
    render_parser.set_defaults(func=cmd_render)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
