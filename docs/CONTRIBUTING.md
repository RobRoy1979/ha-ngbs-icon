# Contributing

Thanks for helping. Bug reports with a diagnostics download and pull requests are both
welcome.

## Development setup

You only need Docker; the toolchain (Python 3.14, Home Assistant, ruff, mypy, pytest)
runs in a container.

```bash
cp .env.example .env    # only needed for the scripts that talk to real devices
make build              # build the toolchain image (once)
make check              # lint + type check + tests, exactly as CI runs them
make ha-up              # development Home Assistant on http://localhost:8125
```

No `make` on your machine? Run the targets in the toolchain container instead:
`docker compose run --rm test make check`, and call the host-side scripts directly
(`scripts/dev-ha.sh up`, `scripts/build-zip.sh`, `python3 scripts/record_fixtures.py`).

The development Home Assistant mounts `custom_components/` from your working copy;
restart it (`docker restart ngbs-icon-dev-ha`) to load code changes.

## Rules

* `make check` must pass. New code comes with tests; the config flow keeps 100 %
  coverage.
* Follow the Home Assistant core conventions (entity naming via `translation_key`,
  `has_entity_name`, typed `runtime_data`, no blocking I/O in the event loop).
  Protocol details belong in `pyngbsicon`, never in the integration.
* Every user-facing string is translated (`strings.json` → `translations/en.json`,
  `translations/hu.json`).
* **Never commit data from a real installation.** A controller's SYSID is also the
  password of its web interface. Record fixtures with `make fixtures`, which
  anonymises them, and run `python3 scripts/check_no_secrets.py --all` before pushing
  (the pre-commit hook does this for you: `pre-commit install`).
* Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

By contributing you agree that your contribution is licensed under the project's
license (see [LICENSE](../LICENSE)).
