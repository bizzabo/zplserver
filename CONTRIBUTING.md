# Contributing

## Getting set up

The project uses [uv](https://docs.astral.sh/uv/), which fetches a suitable
Python itself, so there is nothing to install first.

```sh
uv sync          # create the environment, including development dependencies
uv run pytest    # run the test suite
uv run bizzabo-zpl # run from the checkout
```

`uv sync` installs the `dev` dependency group by default, so `pytest` needs no
extra flags. `uv build` produces a wheel and a source distribution.

## Running it while working on it

```sh
uv run bizzabo-zpl                                # web interface on :8082
uv run bizzabo-zpl --headless --no-open-labels    # terminal only, no image viewer
uv run bizzabo-zpl -v                             # log every decoded command
```

The interface is the default. `--headless` gives you the terminal and opens each
rendered label in your image viewer; add `--no-open-labels` when there is no
viewer to open, such as over SSH or in a container.

## Tests

```sh
uv run pytest              # the whole suite, about a second
uv run pytest tests/test_framing.py -v
```

**No test may reach the network.** An autouse fixture replaces the renderer for
every test. Note that `bizzabo_zpl.printer` imports `render_zpl` into its own
namespace, so both names are patched — patching only `bizzabo_zpl.render` would
leave the server calling the rendering service for real.

| File | Covers |
| --- | --- |
| `tests/test_zpllib.py` | The command table and `parse_zpl` |
| `tests/test_framing.py` | `split_stream`, including forward progress |
| `tests/test_control.py` | `! U1 ...` handling and printer configuration |
| `tests/test_server.py` | The protocol over real sockets, lifecycle, events |
| `tests/test_web.py` | The web interface over real HTTP, including SSE |
| `tests/test_cli.py` | Argument parsing |

Most of the suite is regressions, and each of those tests carries a docstring
saying what it once got wrong. **Please don't delete a test that looks like it is
asserting something obvious** — it is there because that exact thing was once
broken.

Four things that will cost you time otherwise:

- **Prefer `settle(predicate)` over sleeping.** Rendering happens off the request
  path, so results arrive a tick later. A fixed sleep is either flaky or slow.
- **Never use blocking `urllib` against the web interface under test.** The
  server shares the test's event loop, so it never gets a chance to answer and
  the test deadlocks rather than failing. Use the aiohttp test client.
- **`StateLogHandler` is attached by `run_ui`, not by `build_app`.** A test that
  builds the app directly has to attach it too, or every assertion about the log
  panel silently sees an empty list and passes for the wrong reason.
- The forward-progress tests in `test_framing.py` **hang rather than fail** if the
  guards in `split_stream` are removed. That is inherent: an infinite loop cannot
  report itself.

## Architecture, and the three rules worth keeping

**`printer.py` must never learn that a user interface exists.** It publishes
events to an `EventBus`, and subscribers decide what to do with them. The
terminal subscribes through `reporting.report`; the web interface subscribes
twice, once for log text and once to collect labels. Adding a third front end
should need no change to the protocol layer.

**Rendering and displaying are separate.** `render.render_zpl` returns PNG bytes,
which every front end needs. `render.open_image` spawns a platform image viewer,
which only the terminal wants. Please don't fold them back together.

**`split_stream` has a contract.** It never emits a partial message, it always
leaves a partial one in the returned tail, and it always makes forward progress.
It is pure, so it can be exercised without a socket. Nothing may assume that a
network read boundary is also a message boundary — a label can arrive split across
packets, several labels can arrive in one write, and a control command can share a
read with a label.

## Naming and documentation

ZPL is a printer control language originally developed by another company; see the
disclaimer in `README.md`, which is the only place that company is named. Please
keep it that way in code, comments, docstrings, CLI help, and commit messages, and
refer to the language neutrally.

**Command descriptions in `bizzabo_zpl/zpllib.py` must be written in your own
words.** Do not paste descriptions, parameter documentation, or prose from vendor
documentation. Consult it for behaviour if you need to, then describe that
behaviour yourself.

## Submitting a change

If you are outside the organization, fork the repository and open a pull request
from your fork. Organization members can push a branch directly.

`main` is protected: changes arrive through a pull request with an approving
review from a code owner. Force pushes and deletions are blocked.

Commit messages should say **what changed and why it matters to somebody reading
the code**, rather than recounting how the change was arrived at. A reader a year
from now wants the reasoning behind the code, not the sequence of attempts that
produced it.

## Releasing

Releases are automatic. Bump `version` in `pyproject.toml` in a pull request, and
when it merges the workflow tests the code, builds it, tags it, creates a GitHub
release, and publishes to PyPI.

```toml
[project]
version = "1.1.0"   # was 1.0.0
```

Run `uv lock` after changing the version so the lock file agrees, or the release
job's `uv sync --frozen` will fail.

The trigger is *"no tag exists for the current version"*, not *"the version
changed"*. That makes it idempotent: a re-run cannot publish twice. Tags are
created only by the release workflow, are immutable once created, and always
correspond to a published release.

Authentication uses PyPI trusted publishing, so there is no API token anywhere.
Uploads carry provenance attestations linking the artifacts back to the workflow
run that built them.

If a release fails after its tag exists, delete the tag and the GitHub release,
then re-run the workflow from the Actions tab. A failed upload consumes nothing,
but **a version number that has been published successfully can never be reused.**
