# Continuous integration

One workflow, [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), runs on
every pull request, on every push to `main`, and on demand from the Actions tab.
It uses no secrets and makes no model calls, so it costs nothing and is safe to
run on any change. It does not deploy; deploys stay manual.

## What runs

| Job | What it checks | Rough time |
|---|---|---|
| Backend (lint, unit, e2e) | `uv sync --locked`, ruff (new findings only), eval suites load, `tests/unit` and `tests/e2e` | 2 min |
| Backend (integration, Neo4j) | `tests/integration` against a real Neo4j, including the eval harness end to end with a mocked model | 2 min |
| Frontend (types, lint, build) | `npm ci`, `tsc -b`, ESLint (new findings only), `vite build` | 1 min |
| Docker images (build only) | Both Dockerfiles build. Nothing is pushed | 2 to 8 min |
| Backend tests inside the image | Unit and e2e tests again, inside the built backend image | 2 min |

The first four run in parallel; the fifth waits for the image build so it can
reuse its layer cache. A pull request is ready when all five are green.

## Running the same checks locally

Backend, from the repo root:

```bash
uv sync --locked --extra dev          # or use your existing .venv
export OPENAI_API_KEY=sk-test
OPTS='-o addopts= -o asyncio_default_fixture_loop_scope=function'

python scripts/ruff_ratchet.py
python -m agent_system.evals list
python -m pytest tests/unit tests/e2e --deselect tests/e2e/api/test_api.py $OPTS -q
python -m pytest tests/integration $OPTS -q     # needs Docker running
```

Frontend:

```bash
cd frontend
npm ci
npx tsc -b --noEmit
npx eslint .
npm run build
```

Images:

```bash
docker build -f infra/docker/Dockerfile.backend -t agent-system-backend:ci .
docker build -f infra/docker/Dockerfile.frontend -t agent-system-frontend:ci .
docker run --rm -e OPENAI_API_KEY=sk-test -v "$PWD/tests:/app/tests:ro" agent-system-backend:ci \
  sh -c "python -m pip install -q --user pytest==9.0.2 pytest-asyncio==1.3.0 && \
         python -m pytest tests/unit tests/e2e --deselect tests/e2e/api/test_api.py $OPTS -p no:cacheprovider -q"
```

## Choices, and why

**Lint fails on new findings only.** When CI was added the repo had about 2,400
ruff findings (about 1,900 of them whitespace on blank lines) and 10 ESLint
errors. Fixing them in one go would be a very large diff that changes no
behaviour and conflicts with every open branch. Turning the rules off would
lose them for new code too. So the backlog is recorded and the gate is "no
worse than recorded":

- Python: `.ruff-baseline.json` holds a count per file and rule.
  `scripts/ruff_ratchet.py` fails when any count rises. After fixing findings,
  run `python scripts/ruff_ratchet.py --update` and commit, which lowers the
  ceiling.
- Frontend: `frontend/eslint-suppressions.json` is ESLint's built-in version of
  the same idea. After fixing, run `npx eslint . --prune-suppressions`.

Both count rather than record line numbers, so editing a file does not make old
findings look new. The alternative, linting only the files a pull request
touches, was rejected: it makes anyone who edits one line of an old file
responsible for the whole file's backlog, which pushes unrelated cleanup into
feature diffs. `ruff format --check` is not gated at all yet (147 files would
change).

**Integration tests run on every change.** They need Neo4j, and they get it from
testcontainers using the Docker daemon the runner already has, exactly as on a
laptop. A workflow `services:` container would mean a second way of starting
Neo4j that only CI uses.

**One set of library versions everywhere.** `uv.lock` pins every package, and
the laptop (`uv sync --locked`), CI and the backend image all install from it.
The image used to install whatever was newest inside the ranges in
`pyproject.toml` on the day it was built, which had drifted a long way from
what tests ran against (pydantic-ai 1.107 in production, 1.56 in tests) and
meant any deploy could pick up a release nobody had tested. Now an upgrade is a
change to `uv.lock` in a pull request, tested like any other change:

```bash
uv lock --upgrade-package pydantic-ai     # one package
uv lock --upgrade                         # everything
```

Both installs use `--locked`, so a `pyproject.toml` edit without a matching
`uv.lock` fails CI and fails the image build. The cost is that upgrades no
longer happen by themselves; someone (or a tool such as Dependabot or Renovate)
has to propose them.

**Tests also run inside the built image.** Same versions, but it is the image
that ships, not the CI virtualenv: a different Python build, system packages
and install step. Test tools are not in the image, so the job mounts `tests/`
and installs pytest at run time.

**No path filters.** Every job runs on every change, even a docs-only one.
Skipping jobs by path saves a few minutes but a skipped job that is also a
required check blocks the merge, and the workaround is more workflow than the
saving is worth at this size.

**Supply chain and permissions.** Actions are pinned to a commit SHA, not a
tag, because a tag can be moved to different code after you reviewed it. The
workflow token is read-only, the checkout does not leave credentials on disk,
and no job reads a secret, so a pull request from a fork runs the same checks
with nothing to steal.

**Cancellation and timeouts.** A new push to a pull request cancels the run it
replaces. Runs on `main` are never cancelled, so each commit there has its own
result. Every job has a timeout a few times its normal duration, so a hung test
fails in minutes instead of holding a runner for six hours.

## Known gaps

- `tests/e2e/api/test_api.py` is deselected: 7 tests fail against the current API.
- No coverage threshold, no `mypy`, no format check.
- No dependency or image vulnerability scan.
- Branch protection is not configured by the workflow; required checks are set
  in the repository settings.
- Live-model eval gates are not part of this workflow.
