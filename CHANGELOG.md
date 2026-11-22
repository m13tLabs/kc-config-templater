
## [0.1.1](https://github.com/m13tLabs/kc-config-templater/compare/...v0.1.1) (2026-11-22)

### Bug Fixes

* Remove m13t-specific defaults from ManagedConfig ([916162c](https://github.com/m13tLabs/kc-config-templater/commit/916162c07ec6aad844d0bd6279393b7ac276c4d5))



### Dependency Updates

* **deps:** Update actions/checkout action to v7 ([b16606d](https://github.com/m13tLabs/kc-config-templater/commit/b16606d5acdf8cb065790e464d25a1d192a3ca3e))

* **deps:** Update python docker tag to v3.15 ([f013770](https://github.com/m13tLabs/kc-config-templater/commit/f01377069418d5a4408dec6ed868ad9e301ec9f4))

* **deps:** Update actions/setup-python action to v7 ([82b464e](https://github.com/m13tLabs/kc-config-templater/commit/82b464e29ce544c14a8ac6a5807181643f8def6d))



### Documentation

* Update README & add logo ([c7e8ebb](https://github.com/m13tLabs/kc-config-templater/commit/c7e8ebb782ce0ade2ffae42fab742d5f8064a6f8))



### Features

* Initial extraction of the structural secret templating engine ([30e941b](https://github.com/m13tLabs/kc-config-templater/commit/30e941b4319d7094bdfc14dcd9b2cb9e76a3c7c3))

* Add Dockerfile for container-based usage alongside pip ([eab2e9d](https://github.com/m13tLabs/kc-config-templater/commit/eab2e9d20b681944fc811f90ffddbc3d9afe29db))

* Allow nested secret structure ([72ec9a9](https://github.com/m13tLabs/kc-config-templater/commit/72ec9a908b126a71fafb2aaf63134593f7f1ba7d))



# Changelog

All notable changes to this project are documented here, generated with
[git-cliff](https://git-cliff.org/) from conventional commit messages.

## [Unreleased]

### Features

* Initial extraction: structural secret discovery/templating engine,
  configurable scan targets, `kc-master-*`-style managed/env-substitution
  support, cross-realm collision handling, and a CLI (`export`, `template`,
  `render`).
