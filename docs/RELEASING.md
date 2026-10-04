# Releasing

The integration and the protocol library are released separately. The library has to
be on PyPI before an integration release can pin it: Home Assistant installs the
`requirements` of `manifest.json` when it starts and refuses to load the integration if
that fails — even though the release zip also bundles a copy of the library.

## One-time setup

1. Create the GitHub repository `robroy1979/ha-ngbs-icon` and push `main`.
2. On PyPI, add a *trusted publisher* for the project `pyngbsicon`: owner
   `robroy1979`, repository `ha-ngbs-icon`, workflow `release.yml`, environment `pypi`.
3. In the repository settings, create the environment `pypi` (optionally with a
   required reviewer).
4. Add the repository topics `home-assistant`, `hacs`, `ngbs`, `heating` (HACS checks
   for a description and topics).

## Library release (`lib-v*`)

1. Set `__version__` in `lib/pyngbsicon/src/pyngbsicon/__init__.py` and add the changes
   to the `pyngbsicon` part of `CHANGELOG.md`.
2. `docker compose run --rm test make check`
3. Commit, then `git tag lib-v0.1.0 && git push origin lib-v0.1.0`.
4. The `Release` workflow builds the wheel and sdist and publishes them to PyPI.
   Check `pip install pyngbsicon==0.1.0`.

## Integration release (`v*`)

1. Pin the library in `custom_components/ngbs_icon/manifest.json`:
   `"requirements": ["pyngbsicon==0.1.0"]`.
2. Set `"version"` in the same file and give the `## [x.y.z] - YYYY-MM-DD` section of
   `CHANGELOG.md` the release date.
3. `docker compose run --rm test make check`
4. Commit, then `git tag v1.0.0 && git push origin main v1.0.0`.
5. The `Release` workflow checks that the tag matches the manifest and that the pinned
   library is on PyPI, builds `ngbs_icon.zip` (with the library bundled) and creates
   the GitHub release with the changelog section as notes.

## After the first release

* HACS: users add the repository as a custom repository. The default HACS list
  requires a license GitHub can identify, which is not the case for the Business
  Source License, so the integration stays a custom repository (the HACS check in CI
  ignores the license validation for that reason).
* Brand images ship with the integration (`custom_components/ngbs_icon/brand/`), so a
  pull request to `home-assistant/brands` is optional.
