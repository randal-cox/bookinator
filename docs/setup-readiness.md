# Setup and readiness

Bookinator should answer one question before it accepts serious work: **can this
computer run the configured local analysis reliably?** First launch, upgrades,
and any newly missing dependency rerun the same versioned readiness assessment.
The result is stored for diagnostics but cheap checks run again at every launch.

## Support policy

The first packaged release should use these conservative product requirements:

- **Memory:** 32 GB physical RAM is the hard floor for model-backed analysis.
  Less memory may run the web application, but Bookinator must not imply that
  the analysis pipeline is supported. Model selection adds its own requirement:
  the selected weights plus runtime/context headroom must fit available unified
  memory, RAM, or VRAM/RAM according to the platform.
- **macOS:** macOS 14 Sonoma or later on Apple silicon. This matches Ollama's
  current macOS floor and avoids promising acceptable local-LLM performance on
  Intel Macs.
- **Windows:** Windows 10 22H2 or later on x86-64, with a supported current GPU
  driver when GPU acceleration is expected. Confirm the precise release matrix
  in CI and on physical test systems before publishing it.
- **Linux:** x86-64 or ARM64 on a named, tested distribution/version matrix.
  Do not call an arbitrary Linux installation supported merely because the
  kernel starts Bookinator. Detect libc, service manager, architecture, GPU,
  and driver/runtime compatibility; show unsupported configurations honestly.
- **Storage:** calculate this rather than publishing one misleading number.
  Require space for Bookinator, its bundled runtimes, the manuscript library,
  temporary ingestion files, and selected model weights, plus at least 10 GB
  working headroom. Show the download size and projected remaining free space
  before every model install.
- **Python:** packaged builds bundle a tested Python runtime and pinned Python
  libraries. Source checkouts require Python 3.11 or newer within the tested
  range and a working package installer (`uv` preferred; `pip` accepted). A
  merely present `python3` executable is not sufficient.

These are Bookinator support decisions, not claims that smaller Ollama models
cannot run on weaker computers. Revisit the floor only after measuring complete
Bookinator pipelines, not isolated prompt demos.

## Readiness manifest

Return one structured manifest whose checks are `ready`, `repairable`,
`warning`, or `blocked`, each with the detected value, requirement, explanation,
and available repair action.

1. Supported OS name, version, edition/distribution, architecture, and current
   platform support tier.
2. Physical RAM, available memory, GPU/backend, VRAM where meaningful, and
   whether the assigned models fit with safe headroom.
3. Free space on the Bookinator data volume and every model/cache volume.
4. Writable data, cache, log, and temporary directories; a usable loopback
   address and Bookinator port; and access to Ollama's local API on port 11434.
5. Bundled/source Python version, environment identity, installer availability,
   and exact versions/import smoke tests for PyMuPDF, Torch, Transformers,
   tokenizers, and the pinned emotion-model files.
6. Ollama installed, version supported, service running, API responsive, and
   configured models present. Run a tiny generate request rather than treating
   a process or model-list response as proof that inference works.
7. Browser launch capability and network reachability only when setup must
   download or repair something. Normal analysis remains local and offline.
8. GPU drivers/backends where applicable: Metal on macOS; supported NVIDIA or
   AMD drivers on Windows/Linux. CPU fallback may be diagnostic, but should not
   silently turn a usable workflow into an hours-long one.

The readiness manifest must distinguish **installed** from **running**, and
**running** from **successfully inferred**. It should also distinguish a missing
optional role/model from a showstopper.

## What ships and what does not

Packaged Bookinator should ship its own Python runtime and pinned application
libraries, including PyMuPDF and the runtime needed by the emotion classifier.
DOCX and EPUB ingestion currently use Python's ZIP/XML facilities; Bookinator
does not require LibreOffice, Pandoc, Node.js, a database server, or a cloud API.

The principal external dependency is **Ollama**, plus model weights downloaded
through it. Windows and Linux machines may also need vendor GPU drivers. Source
development additionally needs a supported Python and `uv`/`pip`; the current
shell launcher uses `curl` for its health check, but the packaged launcher should
perform that request itself so `curl` is not an end-user dependency.

The emotion classifier feels like a model to the user and belongs in **Models**,
even though its runtime and weights are installed through Python and Hugging
Face rather than Ollama.

## Guided repair

Bookinator should do everything safe and reversible itself:

- select the correct signed Ollama installer for the detected OS, launch it,
  return to the checklist, start or locate the service, and verify its API;
- install Bookinator-owned Python packages into its managed environment;
- offer only models that fit the detected machine, disclose sizes, pull the
  selected weights, assign roles, and run smoke tests;
- download and verify the pinned emotion classifier and its checksums;
- retain successful steps across restarts and provide precise Retry and Open
  logs actions.

Bookinator must still obtain explicit consent before large downloads, elevation,
driver installation, or launching a third-party installer. It cannot safely
click through operating-system trust dialogs or license agreements for the
user. “One guided flow with two unavoidable confirmations” is a better goal than
pretending fully silent installation is possible.

## Current implementation gaps

- `physical_memory_gib()` needs a native Windows implementation and tested
  Linux behavior; returning zero must mean “unknown,” not “no memory.”
- `system_status()` needs a capability/support result instead of using
  Apple-silicon detection as the effective platform verdict.
- `./bin/serve` checks only for a `python3` command even though the project
  declares Python 3.11+ and its in-app installers require a working package
  installer.
- Dependency checks currently test imports/presence, not pinned versions,
  checksums, free space, inference, or repairability.
- Ollama presence and API reachability are checked, but its version, model fit,
  inference health, and GPU/backend are not.

