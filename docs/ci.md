# Continuous integration

Two workflows, split by what they cost:

| Workflow | Runs | Calls a model | Blocks a merge |
|---|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | every pull request, every push to `main` | no | yes |
| [`evals.yml`](../.github/workflows/evals.yml) | on demand, or on a pull request labelled `run-evals` (no schedule yet) | yes | no (see [Live evals](#live-evals)) |

Neither deploys anything; deploys stay manual.

## CI (free, every change)

`ci.yml` uses no secrets and makes no model calls, so it costs nothing and is
safe to run on any change, including one from a fork.

### What runs

| Job | What it checks | Rough time |
|---|---|---|
| Backend (lint, unit, e2e) | `uv sync --locked`, ruff (new findings only), eval suites load, `tests/unit` and `tests/e2e` | 2 min |
| Backend (integration, Neo4j) | `tests/integration` against a real Neo4j, including the eval harness end to end with a mocked model | 2 min |
| Frontend (types, lint, build) | `npm ci`, `tsc -b`, ESLint (new findings only), `vite build` | 1 min |
| Docker images (build only) | Both Dockerfiles build. Nothing is pushed | 2 to 8 min |
| Backend tests inside the image | Unit and e2e tests again, inside the built backend image | 2 min |

The first four run in parallel; the fifth waits for the image build so it can
reuse its layer cache. A pull request is ready when all five are green.

### Running the same checks locally

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

### Choices, and why

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

## Live evals

`evals.yml` runs the eval harness ([evals.md](evals.md)) against the real
model. A model's output varies from run to run and each run costs money, so
this tier is opt-in instead of running on every push.

### What runs

| Job | Suites | Passes when | Manual | `run-evals` label |
|---|---|---|---|---|
| Gates, once per engine (`fsm`, `loop`) | `incidents`, `injection` | every case passes every attempt | yes, 2 attempts | yes, 1 attempt |
| Statistical suites | `routing`, `tool_selection`, `memory_retrieval`, `entity_resolution`, `e2e_tasks` | no suite is clearly worse than the baseline, and none is below 50% | with `tier: all` | no |

**There is no nightly schedule yet, deliberately.** A scheduled run spends
money with nobody watching, and the key in use is the app's own with no
separate budget; the first full run drained the account. The usual shape
(gates and statistical suites every night) comes back by restoring the
`schedule:` block that is commented out at the top of the workflow, once
`EVAL_OPENAI_API_KEY` is a dedicated key with a spending limit. Until then,
run it by hand before a release and after any change to routing or prompts.

A first job, "Should this run?", decides whether the others start. It skips a
pull request without the label, refuses a pull request from a fork, and makes
one tiny billable call to confirm the key works and the account has credits.

**A run that could not reach the model is an error, not a result.** With a bad
key or no credits the harness does not crash: each case just fails. A first
run in that state would be saved as the baseline, and a later one would look
like a regression. This happened on the first full run, when the account ran
out of credits part-way through and the last suite scored 3 of 10 with zero
tokens. So the preflight call is a real one (listing models succeeds with no
credits), and after each eval step the job fails outright if the log shows the
provider refusing calls. A failed job never updates the baseline.

To run it by hand: Actions tab, **Evals (live)**, **Run workflow**. To run the
gates on a pull request, add the `run-evals` label; they rerun on each push
while the label stays on.

### Why two kinds of pass

**The gates are pass or fail.** `incidents` replays real production failures
against frozen data, and `injection` feeds the agent canned hostile web
content. Both are scored by deterministic checks with no judge, and the right
answer is not a matter of degree, so one failing case fails the job. A pass
rate would let one returning bug hide among passes.

**The statistical suites are compared, not thresholded.** They have 10 to 20
cases each, so a single run's pass rate is a rough estimate (9 of 10 is
consistent with anything from 60% to 98%). A fixed bar such as "at least 80%"
would fail at random on a good night and pass a real regression on a lucky
one. Instead each suite is compared case by case with the last good run on
`main`, and the job fails only when the paired test says clearly worse. The 50%
floor is only there to catch a run that did not work at all.

The price of not crying wolf is sensitivity: on a 10-case suite about six
cases have to get worse, with none getting better, before the verdict is
"worse". Smaller regressions pass. More cases and more attempts per case
(`repeats`) are what narrow that, not a stricter rule.

### How the baseline is carried

Eval results live in the app database, and a CI job starts with an empty one.
The comparison only needs pass or fail per case, so the run writes that to a
small JSON file (`--export`), the file is stored in the Actions cache, and the
next run reads it back (`--baseline-file`).

- The baseline moves forward only when the job passes, and only from `main`.
  A regression keeps failing against the last good run until it is fixed.
- To accept a change as the new normal, run the workflow by hand with
  `reset_baseline` ticked.
- The first run has nothing to compare against and becomes the baseline.
- GitHub drops a cache entry not read for 7 days. With no schedule, a baseline
  therefore expires a week after the last full run, and the next run starts a
  fresh one with nothing to compare against. Each run also uploads its
  results as an artifact, kept 30 days.

### What blocks a merge

Nothing in this workflow, by design. The gates take a few minutes and real
money, and they answer "is this safe to release", so the place they are
required is before a deploy: run them on the commit you are about to ship, or
label the pull request. If one check from here were made required, it should
be the gates and never the statistical suites.

A failed run is a signal to look, not a broken build: read the job summary
for the failing case ids, then the uploaded log for the turn-by-turn trace.

### The key, and what it costs

One repository secret, `EVAL_OPENAI_API_KEY` (Settings, Secrets and variables,
Actions). It is the only secret either workflow uses.

- It is passed only to the steps that call the model, never to install or
  summary steps. GitHub masks it in logs.
- Pull requests from forks never receive it. The label only works on branches
  of this repository, which only collaborators can push to.
- Use a key from a dedicated OpenAI project with a monthly budget set on the
  OpenAI side. That budget is the only hard spend cap; everything in the
  workflow (one run at a time per branch, job timeouts, fixed attempt counts)
  limits how fast money can be spent, not how much.
- The first gates run (both engines, two attempts per case) made 236 model
  calls and used about 421k input and 29k output tokens in 7 minutes. The
  harness prints tokens and a cost line per suite in the job summary, but the
  dollar figure is a lower bound until every model in use has a price in
  `MODEL_PRICING_JSON`; the OpenAI usage page has the real number. The
  statistical suites add a judge call per rubric per case and have not been
  measured yet.

Logs are public on a public repository. Eval runs print the prompts and replies
of the synthetic test users, which contain nothing private, but do not point
this workflow at real user data.

### Running the same thing locally

Needs Neo4j, a database and a key in `.env`:

```bash
CHAT_ENGINE=fsm  python -m agent_system.evals run --suite incidents --judge none --no-analysis
CHAT_ENGINE=loop python -m agent_system.evals run --suite injection --judge none --no-analysis --fail-under 1.0
python -m agent_system.evals run --suite routing --judge openai \
  --baseline-file baseline.json --fail-on-regression --export baseline-new.json
```

## Known gaps

- `tests/e2e/api/test_api.py` is deselected: 7 tests fail against the current API.
- No coverage threshold, no `mypy`, no format check.
- No dependency or image vulnerability scan.
- Branch protection is not configured by the workflow; required checks are set
  in the repository settings.
