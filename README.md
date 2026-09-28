# Bookinator

**Finding the plot holes before your readers fall in.**

Bookinator is a local-first manuscript analysis workbench for authors and
editors. It imports a book, preserves its chapter structure, builds durable
summaries and dossiers, tracks entities and narrative questions across the
manuscript, and links editorial findings back to the source text.

The manuscript and model output stay on the user's computer. Model-backed
analysis runs locally through Ollama; Bookinator does not require an account or
a cloud manuscript upload.

## Project status

Version **0.1.0** is the first working milestone: **Holy Crap, that Worked**.

This is a real, usable development snapshot rather than an alpha, beta, or
release candidate. It is not yet a polished end-user distribution. In
particular, the Reviewer annotation workflow, portable model-free reports, and
additional output tools are still being built.

What works now includes:

- PDF, DOCX, EPUB, TXT, and Markdown manuscript import
- page extraction and editable chapter detection
- chapter and whole-book summaries
- structured chapter and whole-book dossiers
- chapter emotions, tags, and editorial smells
- cross-chapter entity, location, and time indexes
- connections and questions-and-payoffs inference
- linked source inspection and pipeline provenance
- branded book-level and individual-report PDF exports
- restartable, inspectable local analysis queues

Bookinator's findings are editorial leads, not verdicts. A missing warning does
not prove that a manuscript is sound, and an automated finding does not replace
an author or editor's judgment.

## Requirements for a source checkout

- Python 3.11 or newer
- `curl`, used by the current development launcher for its local health check
- a modern browser
- [Ollama](https://ollama.com/) for model-backed analysis

The application shell and documentation run without Ollama. Analysis requires
Ollama to be installed and running, plus at least one compatible local model.
Bookinator's **Machine** page checks the computer, manages Bookinator-owned
Python dependencies, shows installed models, and explains what still needs
attention.

Local language models are demanding. The current conservative support target is
32 GB of physical memory, although the application itself and smaller models may
run on less capable hardware. See the served setup documentation for the latest
and more nuanced requirements.

## Install and launch

Clone the repository and start its loopback-only server:

```sh
git clone https://github.com/randal-cox/bookinator.git
cd bookinator
./bin/serve
```

During the current paired-development phase, `bin/serve` delegates to
Inator Commons. The launcher prefers the eventual project-home layout with the
Commons checkout beside this repository as `../inator`; during the folder
migration it also recognizes the current `../../inator` location. Set
`INATOR_COMMONS_DIR` to an absolute path to override either lookup. This
temporary development-source dependency will be replaced by the urgent,
versioned `@inator/dev-tools` installer. It does not make the running product
call back to Commons or to a remote service.

On macOS the launcher opens Bookinator in Safari. On other systems, or if a
browser does not open, visit the local URL printed in the terminal. The default
port is deterministic for this checkout and is usually near `4890`.

Leave that terminal running while using Bookinator. Press `Ctrl-C` to stop the
server.

Useful launch variants:

```sh
# Print the URL without opening Safari.
NO_OPEN=1 ./bin/serve

# Choose a specific port.
PORT=4747 ./bin/serve

# Replace a surviving Bookinator server from this checkout.
./bin/serve --highlander
```

For isolated development or automated inspection, use:

```sh
./bin/codex_serve
```

That launcher uses a separate port and data directory so automation cannot
mutate the ordinary Bookinator library.

## First run

1. Open **Machine** and review the readiness checks.
2. Install and start Ollama if it is not already available.
3. Choose a **Primary reader** for substantive analysis and **Fast intake &
   utilities** for inexpensive work. One model may fill both roles.
4. Return to **Books**, choose **Add Book**, and select a manuscript.
5. Inspect and approve the detected chapter structure.
6. Run the desired pipelines under **Analysis**.
7. Inspect the resulting summaries, connections, questions, emotions, and
   reports under **Explore**.

Analysis can take a long time on large manuscripts and large local models.
Bookinator saves completed work incrementally and exposes status, timing,
failures, retries, model identity, and source ranges instead of hiding the queue
behind a spinner.

## Documentation inside Bookinator

The served application contains substantially more documentation than this
README. Start Bookinator, then use the footer links:

- **About** explains the editorial premise, what Bookinator does, and its trust boundaries.
- **Guide** walks through first-run setup, the book workspace, long-running jobs, and sharing.
- **Docs** maps the local architecture, book artifacts, pipeline, models, and data boundaries.
- **Roadmap** exposes the live product backlog and priorities.
- **Releases** records what each milestone made possible and why it mattered.
- **Resources** includes the one-pager, presentations, and project briefs.

Serve these pages through `./bin/serve`; do not open the HTML files directly.
The server exposes only the public `web/` and `docs/` trees. Local manuscripts
and analysis records are not served as static files.

## Local data and privacy

Book records, imported manuscripts, generated chapter artifacts, model output,
and queue state are stored beneath `.bookinator/` in the checkout. They survive
server restarts and are intentionally excluded from Git.

Bookinator uses loopback networking for its interface and Ollama integration.
Normal analysis remains local. Installing dependencies or models may require
network access, and the interface identifies those actions before they occur.

## Development

Create the development environment and run the tests with:

```sh
uv sync
.venv/bin/python -m pytest -q
node --check web/app.js
```

The repository also contains a documented public-domain demo corpus, product
briefs, interface policy, research notes, and the living implementation backlog
under `docs/`.

## License

Bookinator 0.1.0 is source-available under the **Business Source License 1.1**.
Personal, educational, research, and internal business production use is
permitted. Offering Bookinator as a commercial hosted or managed service, or
selling it as part of a competing commercial product, requires a separate
commercial license.

On September 24, 2030, this version converts to **GPL-3.0-or-later**. See
[`LICENSE`](LICENSE) for the controlling terms.
