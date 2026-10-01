![Playlist Passage](docs/brand.svg)

A Tkinter transfer utility with Spotify OAuth, paginated playlist/library reads and import/remove operations. Account identity is checked before access.

## What was verified

Three tests passed: account/configuration safety using mocked clients and real hidden Tk UI construction with background logging. No real account authenticated or library changed.

## Run locally

```sh
python -m venv .venv
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python -m src.main
```

Use a fresh checkout and isolated data. Inspect configuration before running provider, seed or mutation commands.

## Implementation map

- [Core implementation](src/spotify_manager.py)
- [Supporting implementation](src/data_handler.py)
- [Verification and limitations](docs/VERIFICATION.md)

## Boundaries

Actual Spotify transfer is unverified and requires a developer application and explicit account consent. Review exports and destination identity before any mutation.

Tests with synthetic inputs prove those cases only. They do not establish user adoption, educational effectiveness, financial returns or production readiness.

## Contributing

Use a focused branch, reproduce the issue locally, add a regression for changed behavior, and describe exactly which paths were exercised. Keep credentials and personal data out of fixtures, screenshots and issue reports. License terms remain unchanged; inspect the repository's existing license files before reuse.
