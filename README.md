# StrataBench

Compare **Strata versions × model configurations** on the same questions, then inspect the answers behind each score. StrataBench runs on your own computer, provides a browser GUI, and saves enough information to repeat or resume a comparison.

The interface and benchmark runner use Python’s standard library. There is no Node.js setup, web build step, cloud account, or paid judging service. Strata itself has separate runtime dependencies and hardware requirements.

## Quick start

1. Download this repository as a ZIP and extract it, or clone it with Git.
2. Install **Python 3.11 or newer**, if it is not already installed. Use a normal writable folder for StrataBench.
3. Open the launcher for your system:

| System | Open the app |
| --- | --- |
| Windows 10/11 | Double-click **`StrataBench.pyw`**. If `.pyw` files are not associated with Python, double-click **`start.bat`**. Install Python’s launcher when installing Python. |
| Linux | Open **`start.sh`** with your file manager’s “Run” option. If needed, run `sh start.sh` once. |
| Either | `python -m stratabench` also opens the GUI; on Linux the command is usually `python3 -m stratabench`. |

4. Open **Your setup** and choose how to obtain Strata, as described below.
5. Prepare one version, then select or import a model configuration in **New benchmark**.
6. Start with **Smoke test**, confirm the reasoning setting, and run it. Then move to a larger suite.

The launcher starts a server bound to `127.0.0.1` and opens your default browser. Its usual address is `http://127.0.0.1:18770/`; if that port is occupied, it chooses another free port and opens the correct address. Reopening the launcher reconnects to the running app. Do **not** open `stratabench/web/index.html` directly: the interface needs its local server.

On Linux, `python3 make-shortcut.py` creates a `StrataBench.desktop` launcher with paths for your checkout. Copy it to your Desktop and allow launching if your desktop asks. The generated file is intentionally ignored by Git. On Windows, a normal shortcut to `StrataBench.pyw` or `start.bat` works.

## Requirements

| Feature | Requirements |
| --- | --- |
| GUI, generated smoke questions, scoring and reports | Python 3.11+, a browser, a writable app folder |
| Existing Strata build | A working engine, matching Python server and tokenizer helper, compatible model files/configs |
| Portable release | Internet access, a matching Linux/Windows portable engine archive, a compatible GPU/driver, and Strata’s Python runtime dependencies. **Git and a compiler are not required.** |
| Build from a repository | Git, CMake 3.24+, a supported C++ compiler, NVIDIA CUDA Toolkit with `nvcc`, and a compatible NVIDIA GPU/driver |
| Build from a local Git folder | The same build tools, plus the desired revision already present locally |
| Public benchmark suites | Internet access for the initial dataset download; cached data is reused afterward |

Source builds currently target **CUDA**. AMD HIP and Intel SYCL can be used through compatible portable packages or an existing build. Not every Strata release provides every operating-system, architecture, or backend combination. Model and backend compatibility remain properties of the chosen Strata version.

On Windows, CUDA source builds need Visual Studio C++ Build Tools and a CMake-compatible compiler environment. If the compiler is not found when opening the GUI normally, launch from a configured developer environment or use portable releases instead. StrataBench does not install compilers, drivers, system packages, or change system PATH.

## Choose how Strata is obtained

Open **Your setup → Strata connection**. Source preferences are stored in the ignored `settings.json` file in this app folder. There is no required machine-specific Strata path. [settings.example.json](settings.example.json) documents the file format; the GUI writes `settings.json` when you save.

### 1. Existing build

Use this if Strata already works on your computer.

- Select **Existing build** and enter its installation folder.
- **Detect** checks the entered/saved folder, `STRATABENCH_STRATA_ROOT`, `STRATA_HOME`, a sibling `Strata` folder, `~/Strata`, and installations found through `strata` on PATH.
- Enter the folder containing your model JSON files separately if needed.
- Choose an existing Python environment, or let StrataBench create an isolated one.
- Enter a build label and choose **Save & prepare version**.

A usable installation contains either:

```text
Strata/                         Strata/
  serve/server.py                 terminal/serve/server.py
  tools/strata_tokenizer.py        terminal/tools/strata_tokenizer.py
  engine/strata                   engine/strata.exe
```

The left layout illustrates Linux; the right illustrates Windows and the newer repository layout. Both server layouts work on either OS. Engine detection checks `engine/`, the installation root, `bin/`, `build/`, `build/Release/`, and the equivalent `engine/build/` locations, using `strata.exe` on Windows and `strata` on Linux.

For an unusual engine location, use **Strata versions → Import existing build**, which accepts an explicit engine and Python path.

The engine, shared libraries, server and tokenizer helpers are copied into `versions/<label>/`. Model weights stay in place. A label names the build you selected; entering another release number does **not** turn that existing binary into that release. Choose one of the following methods to obtain different releases.

### 2. Portable release

Use this to avoid compilation.

1. Select **Portable release**.
2. Enter the GitHub repository, normally `https://github.com/Niko1221/Strata.git`.
3. Choose the binary backend: CUDA 12, CUDA 13, HIP, or SYCL. It must match your hardware and driver.
4. Enter a published release tag, or `latest`, and select **Check release**.
5. Leave **Portable asset** on Auto if exactly one file matches. Otherwise select a specific compatible asset.
6. Choose **Save & prepare version**.

The app queries GitHub release metadata, selects an archive for the current OS/architecture/backend, verifies its published SHA-256, and extracts it into its own version folder. It also retrieves server source from the **same release tag resolved to a source commit**. It supports portable ZIP, `.tar.gz`, and `.tgz` packages. It does not run installers, AppImages, shell installation scripts, or PowerShell installation scripts.

Checksums come from the GitHub asset digest or a release checksum file. If neither is published, preparation stops unless **Allow portable packages with no published SHA-256 checksum** is enabled explicitly. A published checksum is always checked; enabling that option never ignores a mismatch. The observed archive hash and whether it was verified are recorded in `version.json`.

Current Strata releases may use different numbers for the desktop app and engine. The selected release tag, source commit, asset filename/hash and the engine’s available build metadata are recorded separately. The GUI does not assume that an app release number is an engine version number.

Some older releases offer only Windows packages. If **Check release** finds no compatible file, choose another release/backend, use an existing build, or build from source. An ambiguous package selection stops with an explanation instead of choosing another GPU variant automatically.

This method uses public GitHub releases. For a private repository, use a local Git source folder or an existing build.

### 3. Clone & build

Use this to compare committed versions from a Git repository or a Strata fork.

- Select **Clone & build** and enter an HTTPS Git repository URL.
- Set **Parallel build jobs** and **CUDA architecture**.
- Optionally enter additional CMake definitions, one `-DNAME=value` per line.
- Enter a tag, commit or branch name, then choose **Save & prepare version**.

StrataBench clones into an app-owned Git cache under `versions/_git/`, fetches the requested revision, resolves its commit, exports a separate source tree and builds there. It never checks out or edits an existing external repository. Prepared versions stay pinned; the same label is not silently rebuilt when an upstream branch or tag moves.

`native` asks CMake to detect the installed GPU. For an RTX 3080, `86` is an explicit alternative. Multiple targets use CMake’s semicolon format, for example `86;89`. Some older toolkit/CMake combinations require an explicit number. Source builds use the CUDA backend; the portable-backend dropdown does not change the source-build backend.

The build handles both the original top-level CMake project and the newer `engine/CMakeLists.txt` layout. Older revisions with a `third_party/ggml/VERSION.txt` dependency pin receive that pinned dependency in the app’s cache. Forks need a compatible Strata server/config/CMake layout.

Build logs are saved per version. If preparation fails, diagnostic build logs are retained under `versions/_failed/`, while the incomplete version directory is removed so the same label can be tried again. Download caches are reused and verified. If a process was forcibly stopped during preparation, the next attempt preserves that app-owned partial folder under `versions/_failed/` before retrying. An unrelated unregistered folder is left untouched.

### 4. Build from folder

Use this for a Strata Git checkout already on your machine.

- Select **Build from folder** and enter the repository folder.
- Enter a tag, branch name or commit that already exists in that repository.
- Configure build jobs/architecture and prepare the version.

The app exports the selected commit with Git and builds the export. It does not fetch into your checkout, switch its branch, or include uncommitted changes. To benchmark an uncommitted custom build, compile it yourself and import it as an **Existing build** with a distinct label.

### Python runtime choice

StrataBench itself has no pip requirements. Strata’s Python server does.

- **Create an isolated environment per version:** creates `versions/<version>/.venv/` using the selected Python, then installs the runtime requirements from that Strata source. For older layouts without a runtime requirements file, it installs `jinja2`, `regex`, and `numpy`. It does not install global packages or build tools.
- **Reuse an existing environment:** validates the core server imports and reuses the selected interpreter. With no explicit executable, it looks for `.venv` in the installation or its `terminal/` folder, then uses the app’s Python. Additional dependencies required by a particular Strata revision must already be installed there.

An optional Python executable controls the reused interpreter or the interpreter used to create the isolated environment. On Windows this is normally a `python.exe`, not a folder. Existing saved installations keep the existing-environment preference when their settings are first migrated.

## Connect model configurations

Strata source settings determine how an **engine/server** is prepared. Model JSON files determine which **weights, tokenizer and inference settings** it uses.

- Set **Model configuration folder** to discover `strata-*.json` files.
- Or use **New benchmark → Import config** to copy an individual JSON file into the app.
- Imported configurations require an absolute `cwd` so relative model paths have a clear base.
- The runner substitutes the prepared version’s executable and creates a separate effective config for each session. Your original config is preserved.
- Model weights, packs, tokenizers and optional prediction models must already exist. Preparing an engine never downloads model weights.
- Configs contain local paths: update those paths when moving between computers or between Linux and Windows.

A Strata configuration includes `exe`, `cwd`, and an `args` array, plus the fields required by that model/version. Start with a config that already works in Strata. StrataBench records its hash and input metadata rather than treating a config filename as proof of identity.

## Run a comparison

1. Open **Strata versions**, prepare any additional versions, and choose the ordering. Numeric version sorting and custom ordering are available; drag tiles or use **Move earlier/later**.
2. Open **New benchmark**, select versions and model configs, and choose a suite.
3. Confirm **Reasoning effort**. The default is **xhigh**; off, low, medium, high, xhigh and server/config defaults are available.
4. Set repeats and, if needed, advanced seed, temperature, answer-token budget and timeouts.
5. Choose **Start benchmark**.

The runner evaluates one version/config combination and one question at a time. Each managed combination gets a fresh server session and the same unscored warm-up. It never sends answers to an external LLM judge.

### Suites and difficulty

| Suite | Default questions per combination | Purpose |
| --- | ---: | --- |
| Smoke test | 7 | Check loading, requests, scoring and saving across difficulty levels. Not a model-quality ranking. |
| Quick comparison | 69 | Screen a set of versions/configs. |
| Standard | 276 | Compare a shortlist with more coverage. |
| Deep evaluation | 648 | More coverage, including all included AIME problems. |
| Full suite | 4,363 | Every included public/generated question. |
| Long context | 12 | Retrieval at configurable context lengths. |

Default counts depend on the pinned dataset selection and difficulty filters. Long-context sizes are **words**, not tokens, and must fit the selected model configuration. The app shows a time range per configuration and for the whole matrix. Unmeasured estimates use an RTX 3080 / 64 GB planning baseline; other hardware can differ substantially. Observed timings for the same version/config/reasoning/budget improve estimates. Reasoning can make hard questions take much longer than easy ones.

Included public tasks are GSM8K, OpenBookQA, eight BIG-Bench Hard tasks, the numeric/text-only subset of MATH-500, and AIME 2024. Generated tasks cover arithmetic, JSON transformations, Python tracing, graphs, combinatorics, exact scheduling, Persian arithmetic and long-context retrieval. Difficulty labels are heuristic.

**Your setup → Verify / download public datasets** prepares the cache. A run needing public data also prepares it automatically. The generated smoke suite works without public downloads. Pinned URLs, hashes and dataset notices live in `datasets/sources.lock.json` and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Scores and answer inspection

**Activity** shows progress and clickable counts for Correct, Incorrect, Cutoffs, Request errors and Pending. **Results** and saved reports expose the same test explorer.

The explorer provides cards, search, combination/difficulty/task-group filters, pagination and a detailed view of each question, reference answer, model response, extracted answer, supplied reasoning, request settings and token usage. It updates while a run is active. Retried requests count once using their latest saved attempt; earlier attempts remain in the raw log.

Correctness uses known reference answers and deterministic graders. Numeric equivalents, supported exact/choice answers and structured JSON are checked by the appropriate grader. A response cut off by its token limit counts as a failure. Request errors are tracked separately. Missing work earns no credit and incomplete combinations are excluded from rankings. The report includes ordinary accuracy, balanced task-group accuracy and uncertainty/comparison information.

These results are **local protocol scores**, not official leaderboard replications: prompts, reasoning, budgets, numeric-only filtering and sampled subsets can differ from published protocols. Small sampled differences should be checked with more questions and repeats.

### Original-model references

**Model references** records published reference scores with their dataset, source, evaluation method and weight precision. Missing scores remain unavailable; quantized scores are not presented as original-model results.

The included Qwen3.8-Flash-Next GSM8K reference is labeled **BF16**, with its independent evaluation method and a **Context only** comparison label. BF16 is distinct from FP16, FP32 and INT8. The reference catalog does not assert that a small local subset, xhigh reasoning or a local quantized model reproduces that published evaluation. References also appear in reports and a separate CSV.

## Stop, resume and keep results

- Closing the browser tab does not stop a running benchmark. Reopen the launcher to reconnect.
- Choose **Stop & save** in Activity to stop the owned worker and preserve saved answers.
- Choose **Resume** from Activity, Results or the Test explorer to continue the saved run. Unfinished runs are discovered again after restarting the app.
- Correct, incorrect and cutoff answers stay in place. Pending evaluations and request errors are retried.
- Resume uses the original saved questions, configurations, versions and request settings, not the current selections in New benchmark.
- Each resume opens a new model session; engine caches and learned session state may differ from an uninterrupted session.

On Linux, stopping requests a graceful interrupt. On Windows, the app stops its owned worker process tree; a request still in flight may have no saved row and is retried later. Saved answer rows are flushed individually. A process-ending crash can leave a manifest marked running; without a held run lock it is shown as unfinished again.

Resume validates source/config/model fingerprints, inherited engine environment and benchmark code. **Finish or stop a run before updating StrataBench, and keep the original app revision to resume old runs if a code update changes the protocol.** It refuses to mix changed scoring code, changed model inputs or changed settings into the same run.

Reports and raw files are under `results/<run-id>/`:

| File | Contents |
| --- | --- |
| `manifest.json` | Saved plan, target identities, hardware, status and protocol hashes |
| `cases.json` | Exact questions and reference answers |
| `<target>/answers.jsonl` | Durable per-request answer/error attempts and raw responses |
| `<target>/session-*/` | Effective configs, launch details and server/engine logs |
| `report.html`, `report.txt` | Readable reports |
| `summary.json`, `leaderboard.csv` | Machine-readable summaries |
| `reference-scores.csv` | Published original-model context alongside local task scores |

Only runs with matching questions, settings, environment and scoring protocol can be combined with **Compare selected**. Prepared versions and result folders are never silently overwritten.

## Custom questions

Use **New benchmark → Choose file** to import JSONL, with one object per line. See [examples/custom-tasks.jsonl](examples/custom-tasks.jsonl).

```json
{"id":"my-task-001","group":"my_work","difficulty":"easy","prompt":"What is 6 times 7?","answer":42,"grader":"numeric"}
```

Required fields: `id`, `group`, `difficulty`, `prompt`, `answer`, `grader`. IDs must be unique. Difficulty is `easy`, `medium`, `hard`, `very_hard` or `extreme`; grader is `numeric`, `exact`, `choice` or `json`. JSON tasks can use objects/lists as their reference answer. These are single-turn answer checks, not an agent/tool-use benchmark.

## Optional command line

The GUI is the normal workflow. The same operations are available through `python -m stratabench ...` or `python bench ...`. Replace `python` with `python3` where appropriate. Quote paths containing spaces.

```bash
# Configure portable releases, then prepare a pinned release.
python -m stratabench source --method release --repository https://github.com/Niko1221/Strata.git --backend cuda12 --python-mode managed
python -m stratabench add-version v0.2.16

# Clone and build source for a specific CUDA architecture.
python -m stratabench source --method repository --repository https://github.com/Niko1221/Strata.git --cuda-architectures 86 --build-jobs 4
python -m stratabench add-version v0.1.45

# Build a committed revision from a local checkout.
python -m stratabench source --method folder --folder "/path/to/Strata" --config-folder "/path/to/model-configs"
python -m stratabench add-version v0.1.45

# Import an existing build with explicit paths if needed.
python -m stratabench snapshot --name my-build --source "/path/to/Strata" --exe "/path/to/strata" --python "/path/to/venv/bin/python"

# List the current preferences, prepared versions and discovered configs.
python -m stratabench source
python -m stratabench versions
python -m stratabench configs
python -m stratabench doctor

# Cache public data, inspect task counts, or run a comparison.
python -m stratabench datasets
python -m stratabench tasks --profile quick
python -m stratabench run --versions v0.1.45 --configs "/path/to/model-config.json" --profile quick --reasoning xhigh --repeats 3

# Resume or regenerate reports from saved files.
python -m stratabench resume "/path/to/results/RUN_ID"
python -m stratabench report "/path/to/results/RUN_ID"
python -m stratabench compare "/path/to/results/RUN_A" "/path/to/results/RUN_B"
```

For Windows paths, use values such as `"C:\Models\Strata"`, `"C:\Python312\python.exe"` and `"C:\Models\venv\Scripts\python.exe"`. The commands themselves are the same; no Bash environment is required.

Advanced runs accept `--max-tokens`, `--timeout`, `--startup-timeout`, `--temperature`, `--seed`, `--only`, `--context-words`, `--tasks`, `--port` and `--dry-run`. `python -m stratabench run --help` lists them. Source preparation also accepts `--jobs`, `--python` and repeated `--cmake-arg=-DNAME=value` options.

To attach to a server you manage yourself:

```bash
python -m stratabench run --endpoint http://127.0.0.1:8080/v1 --label my-existing-server --profile smoke --reasoning xhigh
```

External endpoints are not started or stopped by StrataBench. Their version/config identity is user supplied rather than a verified binary fingerprint. `STRATABENCH_API_KEY` supplies authentication for such an endpoint without embedding the key in a saved config.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Page is incomplete after opening a local HTML file | Open the app launcher instead. It starts the local server. |
| No Strata installation is detected | Enter its folder explicitly. Existing-build mode needs both the engine and matching server/tokenizer files. |
| No model configs appear | Set Model configuration folder or import a JSON file. Config discovery looks for `strata-*.json`. |
| No compatible release file | Check OS/architecture/backend and release tag. Some releases have no Linux binaries or several HIP variants. Use the asset picker, another tag, or source mode. |
| GitHub release lookup fails | Check the URL, published tag, network, and public GitHub API rate limit. An ordinary Git tag is not necessarily a published release. |
| Checksum mismatch | The package is rejected and its cached download removed. Retry after checking the upstream release. A mismatching checksum cannot be overridden. |
| CMake, nvcc or C++ compiler missing | Use portable binaries, or install/configure the build tools yourself. Windows source builds may need a developer environment. |
| CUDA architecture detection fails | Set an explicit supported architecture, for example `86` for RTX 3080. |
| Server exits while loading | Read Activity and the saved server/engine logs. Check model paths, quantization support, Python dependencies, driver/backend and RAM/VRAM. |
| Existing Python lacks dependencies | Select a working Strata interpreter or switch to the isolated-environment option. |
| Revision missing from a local source folder | Fetch it yourself in that checkout, then retry; or use Clone & build mode. |
| Version label already exists | Use that prepared version or select another label for a distinct build. It is not overwritten. |
| Run cannot resume after an update | Return to the original StrataBench revision and original inputs/settings, or start a new run. Do not edit a manifest to bypass identity checks. |
| Long-context test gets a context error | Reduce context words or answer-token budget, or use a config with sufficient context capacity. |
| Other hardware is slower than the estimate | Start with smoke/quick and let matching local timing history accumulate. Unmeasured ranges are planning estimates. |

## Development and repository contents

```text
stratabench/                 Python runner, scoring, acquisition and local GUI server
stratabench/web/             Bundled interface assets; no frontend build required
stratabench/acquisition.py   Local/Git/release preparation and source settings
stratabench/platforms.py     Linux/Windows process, lock and path adapters
examples/custom-tasks.jsonl  Sample user questions
datasets/                   Source lock and original-model reference catalog
versions/                   Local source exports, engines, Python environments and caches (ignored)
results/                    Local benchmark output (ignored)
settings.json               Machine-specific preferences and registered versions (ignored)
```

Run the checks with:

```bash
python -m unittest discover -s tests -v
```

The suite uses temporary files and local fake API servers; it does not download model weights or need a GPU/compiler. The optional cached-public-data check is skipped when the raw dataset cache is absent. GitHub Actions is configured for Linux and Windows with Python 3.11, 3.12 and 3.13. Native GPU/driver/Strata integration still depends on the selected engine package and machine.

For interface syntax checks, Node is optional:

```bash
node --check stratabench/web/app.js
node --check stratabench/web/setup.js
node --check stratabench/web/outcomes.js
node --check stratabench/web/helpers.js
```

Local settings, model files, downloaded binaries, virtual environments, runtime credentials, logs and benchmark results are excluded from Git. Public source URLs and upstream references are retained for reproducibility. Nothing is published or uploaded by the GUI. Dataset downloads, Git source retrieval, release downloads and isolated Python package installation are the network operations used during preparation.

Strata, model weights, runtime packages and datasets retain their respective licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the licenses in prepared version sources.
