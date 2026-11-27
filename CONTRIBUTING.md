# Contributing to RagNex

Thanks for helping. The short version:

1. **Set up** a development environment: [docs/development.md](docs/development.md#setting-up).
2. **Find your way around**: [docs/architecture.md](docs/architecture.md) explains the
   services and the code layout; [docs/extending.md](docs/extending.md) lists every place
   to change when adding a model provider, file type, chunking template, setting,
   endpoint or migration.
3. **Make the change with tests**, including one that fails without it, and update the
   docs it affects ([conventions](docs/development.md#conventions)).
4. **Run the tests**: `python -m pytest` in `backend/`, `npm test -- --run` and
   `npm run build` in `frontend/`.
5. **Open a pull request** against `master`. CI runs the full test suites; it needs to
   pass before merging ([commits and pull requests](docs/development.md#commits-and-pull-requests)).

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE), except changes to `deepdoc/`, which stay under the Apache License
2.0 ([NOTICE](NOTICE)).

Found a security problem? Please don't open a public issue; contact the maintainer
privately.
