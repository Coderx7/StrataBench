# StrataBench

Compare **Strata versions × model configurations** on the same questions, then inspect the answers behind each score. StrataBench runs on your own computer, provides a browser GUI, and saves enough information to repeat or resume a comparison.

The interface and benchmark runner use Python’s standard library. There is no Node.js setup, web build step, cloud account, or paid judging service for the standard suites. Writing-quality judging is an optional, separately configured feature. Strata itself has separate runtime dependencies and hardware requirements.

## Quick start

1. Download this repository as a ZIP and extract it, or clone it with Git.
2. Install **Python 3.11 or newer**, if it is not already installed. Use a normal writable folder for StrataBench.
3. Open the launcher for your system:

| System | Open the app |
| --- | --- |
| Windows 10/11 | Double-click **[start.bat](start.bat)** in the extracted project folder, beside this README. **[StrataBench.pyw](StrataBench.pyw)** is another launcher if Python file associations are configured. Install Python’s launcher when installing Python. |
| Linux | Open **`start.sh`** with your file manager’s “Run” option. If needed, run `sh start.sh` once. |
| Either | `python -m stratabench` also opens the GUI; on Linux the command is usually `python3 -m stratabench`. |

4. On first launch, the welcome window explains setup. Choose **Configure Strata** to open **Your setup**, then follow the three-step checklist. Existing installations with prepared versions keep their normal startup.
5. Prepare one version, then select or import a model configuration in **New benchmark**.
6. Start with **Smoke test**, confirm the reasoning setting, and run it. Then move to a larger suite.

On Windows, use **Extract All** before launching. If Explorer hides file extensions, `start.bat` may appear as **start**, with type **Windows Batch File**. The launcher is in the project’s top-level folder, not inside `stratabench/` or `stratabench/web/`. It also supports installations where only `py` or `python` is on PATH.

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

Open **Your setup → Strata connection**. The checklist tracks whether you have saved a source, prepared a version, and connected model configs. Choosing **Explore first** closes the welcome window; setup remains available in **Your setup**. The welcome acknowledgment is saved locally, so it does not repeat after reopening the app.

Source preferences are stored in the ignored `settings.json` file in this app folder. There is no required machine-specific Strata path. [settings.example.json](settings.example.json) documents the file format; the GUI writes `settings.json` when you save.

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

The runner evaluates one version/config combination and one question at a time. Each managed combination gets a fresh server session and the same unscored warm-up. Standard suites are graded locally. When you enable the optional writing judge, only that suite’s writing brief and response are sent to the judge endpoint you configure.

### Suites and difficulty

| Suite | Default questions per combination | Purpose |
| --- | ---: | --- |
| Smoke test | 7 | Check loading, requests, scoring and saving across difficulty levels. Not a model-quality ranking. |
| Quick comparison | 69 | Screen a set of versions/configs. |
| Standard | 276 | Compare a shortlist with more coverage. |
| Deep evaluation | 648 | More coverage, including all included AIME problems. |
| Full suite | 4,363 | Every included public/generated question. |
| Long context | 12 | Retrieval at configurable context lengths. |
| Writing style | 20 | Explicit writing constraints across professional, friendly, instructional and neutral briefs; optional quality judge. |
| Vision | 20 | Generated PNG counting, spatial, grid and chart questions. |
| Tool use | 15 | Multi-step customer/order/tax workflows with controlled function calls. |
| Agentic coding | 10 | Small Python repair projects with file tools, visible tests and hidden acceptance tests. |

### Standard benchmark library

Open **Benchmark library** in the sidebar. Everything needed to download and prepare the standard suites is available there on **Windows and Linux**; no separate terminal preparation or pre-downloaded files are required.

1. Open **Library settings**. Choose a **Benchmark download folder**, or leave it empty to use `benchmarks/` inside the app folder. Full paths with spaces are supported, such as `D:\Benchmark files` on Windows or `/home/you/Benchmark files` on Linux. The app creates the folder when setup starts. Changing the folder does not move or delete existing downloads.
2. Select which suites should appear in **New benchmark**. These choices are saved across restarts. Selection alone starts no downloads. You can also change each suite’s **Include in New benchmark** checkbox directly on its library card. SWE-bench is off by default.
3. Click **Download & prepare** for any suite you want. The app downloads its pinned data/source and creates its private evaluator environment in the selected folder. **Activity** shows setup stages and details, with a **Stop setup** button. No model evaluation starts during this operation.
4. Once the card says **Ready**, choose **Use this suite**. The selected suite is now available for a normal version/config comparison.
5. Use **Check installation** to verify downloaded checksums and private evaluator dependencies without downloading anything. **Repair / reprepare** reinstalls the private evaluator and prepares the data again. A stopped or failed installation shows **Retry setup** after restarting the app; cached package/dataset downloads are reused where supported.

These controls are also linked from **Your setup → Benchmark downloads & setup**. The app selects the Windows (`Scripts/python.exe`) or Linux (`bin/python`) private runtime layout automatically. It does not install Python packages globally or change Strata/model files. The original diagnostic suites remain available for quick checks. **Full suite** continues to mean the existing accuracy task collection; it does not silently add standard suites or SWE-bench. Existing downloads on this computer are reused, but new installations do not depend on them. If a download folder is moved between operating systems, choose **Repair / reprepare** to recreate the evaluator for that computer.

Changing the download folder switches the library to that location. To reuse an existing library, choose its original folder. Saved benchmark results are preserved. Keep the matching downloaded suite available when resuming runs that require it.

| Standard suite | Full configured coverage | Reported score |
| --- | --- | --- |
| [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) | Original 541 prompts | Official prompt/instruction strict and loose metrics; prompt strict is primary. |
| [BFCL](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) | 1,000 v4 cases across `simple_python`, `multiple`, `parallel`, `parallel_multiple` | Official Python AST checker accuracy for these categories. This integration does not report BFCL overall, Java/JavaScript, live, multi-turn, memory or web-search scores. |
| [MMMU](https://github.com/MMMU-Benchmark/MMMU) | 900 validation questions across all 30 subjects | Accuracy using the upstream multiple-choice/open-answer parser and checker. Original images are sent to the selected vision model. |
| [WritingBench](https://github.com/X-PLUG/WritingBench) | 1,000 prompts with their published per-question criteria | Mean rubric quality score on a 100-point scale, using the upstream judge prompts. Requires a separately configured judge. |
| [SWE-bench Lite](https://www.swebench.com/lite.html), optional | 300 test issues | Percentage resolved, using the pinned official test specification and acceptance-test grader with the StrataBench terminal agent. |

The default is a **seeded sample of 50 questions**. Change the sample size or select **Run the full configured split** in New benchmark. The selection is identical for every version/config in a comparison. Reports state **seeded sample** or **full configured split**, the selected/full counts, source and dataset revisions, environment package snapshot and run settings. Standard suites retain their original categories and do not receive invented Easy–Extreme labels. MMMU-Pro is not included in this integration.

The runner uses a StrataBench generation adapter with the pinned upstream scoring functions. It preserves IFEval prompts, supplies BFCL functions through the native tool-call API, and sends MMMU questions/options and their images through the multimodal API. Generation settings, system prompts, parser seeds, tool formats, budgets, sampling and agent scaffolding can differ from a publisher’s leaderboard setup. **Full coverage is not a claim of exact leaderboard replication.** Compare published numbers only when the evaluation protocol and model precision also match. Existing published model references remain unavailable wherever a verified matching reference is absent.

WritingBench uses its own published 1–10 criterion rubrics, rather than the original diagnostic suite’s four-dimension 1–5 judge. It normally makes five judge calls per response. The writing brief, response and criteria are sent to the judge endpoint you configure; the API key stays in memory. A successful rating is a **rated response**, with no arbitrary correct/incorrect threshold. Reports show quality, scored coverage and judge errors separately. Incomplete judge coverage is excluded from rankings. Resuming a judge failure reuses the saved model response and retries its judging; it does not generate a different writing sample. Keep the same judge/model/rubric across comparisons.

Standard metrics appear in the report and in `standard-metrics.json` / `standard-metrics.csv`, alongside the existing saved answers and inspection views. IFEval instruction-level metrics count individual instructions across the split. Standard accuracy scores include missing/error/cutoff questions in the denominator. Writing quality is the mean of successfully judged responses and always includes its coverage. Time estimates include broad allowances for multi-turn work and judge calls; downloads, package installation and SWE image preparation are excluded.

MMMU images are stored once per selected question in the run’s `cases.json`. Saved request records use `case-image:N` references and data-URL hashes instead of repeating the image bytes for every version/config/repeat. Actual API requests still contain the original image data, and the inspector reads images from the saved cases. Full vision splits can still produce large result folders.

### Optional SWE-bench: off by default

SWE-bench is **not included in normal preparation, dataset downloads, or suite choices**. To use it:

1. Open **Benchmark library**, then turn on **Include optional SWE-bench in my suite choices**. This only reveals the option and saves your preference; it downloads nothing.
2. Choose **Download & prepare** on the SWE-bench card. This downloads the small issue dataset and the isolated official evaluator environment, not the large issue images.
3. Choose **Use this suite**, select versions/configs, and start with a small sample. Set the model-turn budget and acceptance-test timeout as needed. The GUI defaults to 30 model turns when selecting this suite; the command-line default remains 8 unless overridden.
4. Starting the run explicitly prepares Docker images for the selected issues **before loading the model**. Each resolved immutable image ID is recorded and required on resume. The app uses upstream prebuilt x86-64 Linux images; it does not silently build unavailable images from source.

Plan for **at least 120 GB free in Docker storage**, following the [official harness requirements](https://github.com/SWE-bench/SWE-bench/blob/main/docs/reference/harness.md). Your Docker data drive can differ from the app drive. Full runs can take hours or days, and images can consume substantial bandwidth and disk. A notice appears before the preparation/run controls. The app never prunes unrelated Docker images or volumes. Disabling the option hides the suite without deleting its downloads or saved results; manage retained images through Docker Desktop or your usual Docker tools.

Docker must be running in **Linux-container mode** on Linux or Windows; Windows uses Docker Desktop’s Linux containers. The terminal agent operates in an issue-specific container with no network or host-folder/Docker-socket mounts, dropped capabilities, 2 CPUs, 4 GB RAM and a 256-process limit. Commands have 120-second limits and bounded output. The agent edits repository files and runs visible tests inside that container. Its patch is then tested in a **fresh container**, using the official hidden test patch, test commands and resolution grader. The gold patch and hidden tests are not included in the model prompt. Acceptance tests default to a 900-second timeout, configurable up to 3,600 seconds. This is the `stratabench-terminal-v1` agent, not a reproduction of another agent’s published SWE-bench result.

If image preparation fails or storage is insufficient, the run stops with saved diagnostics. Resume requires the original image IDs to remain available. There is no host-execution fallback. Only the app’s own labelled task containers are cleaned up.

**Thinking budgets:** In **New benchmark → Reasoning & repetition**, **Use default thinking budgets** is checked initially. Every field shows the app’s default. Uncheck it to edit the values, then click **Apply budgets**. Reasoning effort (xhigh by default) and thinking-token caps are separate controls.

| Difficulty | Default thinking tokens | Automatic total generation tokens |
| --- | ---: | ---: |
| Easy | 1,024 | 2,048 |
| Medium | 3,072 | 4,096 |
| Hard | 7,168 | 8,192 |
| Very hard | 11,264 | 12,288 |
| Extreme | 15,360 | 16,384 |
| Original benchmark category (standard suites) | 7,168 | 8,192 |

These are StrataBench defaults, not a claim about the model publisher’s evaluation settings. Tool use, agentic coding and SWE-bench default to at most 3,072 thinking tokens and 4,096 total tokens **per model turn** (Easy remains 1,024/2,048). Standard suites retain their original categories; their **Original benchmark category** field controls all questions rather than inventing difficulty ratings.

Custom caps accept positive whole numbers up to 1,000,000. Automatic total generation allows the chosen thinking cap plus 1,024 tokens for answer/wrap-up, including for agent tasks. An explicit **Answer token limit** overrides that automatic total; custom thinking must remain below it. Default thinking caps adapt to a smaller overall limit to leave answer space. **Reasoning Off** disables thinking, ignores the configured thinking caps, and keeps the ordinary total output limits. Requests use Strata’s `reasoning_budget_tokens`; the overall `max_tokens` limit still includes thinking and the final answer.

The app checks the **selected configs** against the budgets for the actual difficulty levels in the selected suite. It reads the config’s `--max-context` declaration; config-level `max_tokens` and `reasoning_budget_tokens` are defaults, not hard capacity limits. Checks allow another 1,024 prompt tokens. A warning lists each incompatible config and the required/available capacity. Editing does not change selections. **Apply budgets & deselect … incompatible configs** accepts the new budgets and removes just those selections; compatible configs remain selected. If none remain, select a compatible config before starting. Unknown context sizes are reported and stay selected. Long prompts, images and multi-turn histories can need more space than this planning allowance, so Strata also checks the actual request at runtime. The server and command-line runner repeat the capacity check before starting a benchmark.

Applied budgets are saved with the run, used in time estimates and preserved by Resume. Timing history must match both the thinking cap and total output limit. **Time by configuration** stays expanded across automatic refreshes and plan changes until you close it.

Default counts depend on the pinned dataset selection and difficulty filters. Long-context sizes are **words**, not tokens, and must fit the selected model configuration. The app shows a time range per configuration and for the whole matrix. Unmeasured estimates use an RTX 3080 / 64 GB planning baseline; other hardware can differ substantially. Observed timings for the same version/config/reasoning/budget improve estimates. Reasoning can make hard questions take much longer than easy ones.

Included public tasks are GSM8K, OpenBookQA, eight BIG-Bench Hard tasks, the numeric/text-only subset of MATH-500, and AIME 2024. Generated tasks cover arithmetic, JSON transformations, Python tracing, graphs, combinatorics, exact scheduling, Persian arithmetic and long-context retrieval. Difficulty labels are heuristic.

**Your setup → Verify / download public datasets** prepares the cache. A run needing public data also prepares it automatically. The generated smoke suite works without public downloads. Pinned URLs, hashes and dataset notices live in `datasets/sources.lock.json` and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Scores and answer inspection

**Activity** shows progress and clickable counts for Correct, Incorrect, Cutoffs, Request errors and Pending. **Results** and saved reports expose the same test explorer.

The explorer provides **Grid** and **List** views, search, combination/difficulty/task-group filters, pagination and a detailed view of each question, reference answer, model response, extracted answer, supplied reasoning, request settings and token usage. The selected layout is remembered in that browser, and filters/pagination stay in place when you switch layouts. It updates while a run is active. Retried requests count once using their latest saved attempt; earlier attempts remain in the raw log.

Correctness uses known reference answers and deterministic graders. Numeric equivalents, supported exact/choice answers and structured JSON are checked by the appropriate grader. A response cut off by its token limit counts as a failure. Request errors are tracked separately. Missing work earns no credit and incomplete combinations are excluded from rankings. The report includes ordinary accuracy, balanced task-group accuracy and uncertainty/comparison information.

These results are **local protocol scores**, not official leaderboard replications: prompts, reasoning, budgets, numeric-only filtering and sampled subsets can differ from published protocols. Small sampled differences should be checked with more questions and repeats.

### Writing, vision, tools and agentic coding

These four suites are **original StrataBench diagnostics**, separate from the existing accuracy suite. They are not official IFEval, BFCL, SWE-bench or general vision benchmark scores. Their difficulty tiers are relative to these small diagnostic tasks. The [IFEval work](https://github.com/google-research/google-research/tree/master/instruction_following_eval) provides background on verifiable instruction-following; the [Berkeley Function Calling Leaderboard](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) provides background on tool-call evaluation. This app does not copy their datasets or claim their scores.

**Writing style:** strict correctness means every explicit rule passes. A separate constraint-compliance score shows the fraction of rules satisfied. Rules cover word ranges, titles, list structure, required phrases, forbidden wording, sentence length and text blocks. These checks do not establish that prose is natural, persuasive or artistically good.

Enable **Add an independent writing-quality judge** to add ratings for clarity, tone, coherence and effectiveness, each from 1 to 5. Enter an OpenAI-compatible `/v1` endpoint, a model name and optionally its API key. The judge may be a separate local server or a remote service. It receives the writing brief and response. Its key stays in browser/app/worker memory and is not saved in settings, command-line arguments or reports; alternatively launch the app with `STRATABENCH_JUDGE_API_KEY` set. The rubric, judge model, endpoint, ratings, coverage and errors are recorded. Judge ratings never replace deterministic correctness. Compare them only with the same judge and rubric; remote services may charge for calls, and local judges need their own available resources. If you restart the app before resuming a run that needs a key, Resume asks for the original judge’s key again. Judge errors leave local scores intact and are inspectable separately.

**Vision:** the runner sends actual generated PNG images through the multimodal API and enables the configured image encoder automatically. The inspector displays each image. Select configs with working `vision` settings and existing image-encoder weights. The runner prefers a prepared version’s `strata-vision` executable; if absent, it can reuse the explicitly configured encoder. The encoder executable and projector metadata are recorded so engine comparisons can use a fixed encoder. No vision model weights are downloaded automatically.

**Tool use:** the model must actually look up customer IDs, retrieve orders, select the requested records, obtain tax where needed, and call the calculation tool. A guessed final number without the required calls does not pass. The provided tools operate on generated test data and expose no external services or host commands. Schema errors, required calls, filtered inputs and turn limits are checked. The inspector shows the full model/tool conversation.

**Agentic coding:** the model uses `list_files`, `read_file`, `write_file` and `run_tests` on a small project. Only `solution.py` is editable. Final scoring uses separate hidden acceptance inputs, including seeded variations. The tasks include arithmetic repairs, order-preserving deduplication, medians, interval merging, bracket validation, knapsack, edit distance, LRU behavior and weighted scheduling. This measures small tool-assisted repairs, not broad autonomous repository engineering.

Coding requires **Docker running in Linux-container mode**, including on Windows through Docker Desktop. Select **Prepare coding runtime** in the Coding suite to download the Python image once. The default is `python:3.12-slim`; its resolved immutable image ID is recorded for a run and reused on resume. Test containers use no host-folder mounts or network, a read-only root, one CPU, 256 MB memory, a process limit and time/output limits. See Docker’s [run options](https://docs.docker.com/engine/containers/run/) and [resource limits](https://docs.docker.com/engine/containers/resource_constraints/). The app never falls back to executing generated code on the host.

Tool/coding suites have a configurable maximum model-turn count (default 8). Their automatic output budget is at most 4,096 tokens per turn; custom thinking budgets or a custom overall answer limit override it. Multi-turn tasks and optional judging increase runtime. Their timing history is kept separate from the ordinary accuracy suite. Agent rows include tool/test time; optional judge time is recorded separately from model-generation latency.

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

Required fields: `id`, `group`, `difficulty`, `prompt`, `answer`, `grader`. IDs must be unique. Difficulty is `easy`, `medium`, `hard`, `very_hard` or `extreme`; grader is `numeric`, `exact`, `choice` or `json`. JSON tasks can use objects/lists as their reference answer. The documented imported-case format describes single-turn reference-answer checks; the built-in Tool use and Agentic coding suites provide the controlled multi-turn workflows.

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

Advanced runs accept `--thinking-budgets '{"easy":1024,"hard":12000,"extreme":24000}'` (omitted levels use app defaults), `--max-tokens`, `--timeout`, `--startup-timeout`, `--temperature`, `--seed`, `--only`, `--context-words`, `--tasks`, `--port` and `--dry-run`. Capability suites also support `--agent-turns`, `--coding-image`, `--style-judge-endpoint` and `--style-judge-model`. `python -m stratabench run --help` lists them. Source preparation also accepts `--jobs`, `--python` and repeated `--cmake-arg=-DNAME=value` options.

Standard-suite commands are optional; the GUI provides the same controls:

```sh
python -m stratabench prepare-suite ifeval
python -m stratabench run --profile ifeval --standard-limit 50 --versions VERSION --configs CONFIG.json
python -m stratabench run --profile ifeval --standard-limit 0 --versions VERSION --configs CONFIG.json
```

`--standard-limit 0` selects the complete configured split. `--swe-test-timeout` sets the optional SWE acceptance-test limit; `--agent-turns` controls its agent budget. SWE preparation also requires the explicit `optional_swebench: true` setting written by the GUI. Difficulty filters do not apply to standard-suite profiles. A dry run never pulls SWE issue images.

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

The suite uses temporary files and local fake API servers; it does not download model weights or need a GPU/compiler. The tests include persisted source settings, first-run guidance, both inspector layouts, generated capability cases, tool orchestration and optional-judge separation. Native batch-launcher checks run on Windows. For actual container checks with an already prepared image, set `STRATABENCH_DOCKER_TEST_IMAGE=python:3.12-slim` when running tests; these checks do not pull images automatically. The optional cached-public-data check is skipped when the raw dataset cache is absent. GitHub Actions is configured for Linux and Windows with Python 3.11, 3.12 and 3.13. Native GPU/driver/Strata integration still depends on the selected engine package and machine.

For interface syntax checks, Node is optional:

```bash
node --check stratabench/web/app.js
node --check stratabench/web/setup.js
node --check stratabench/web/outcomes.js
node --check stratabench/web/helpers.js
```

Local settings, model files, downloaded binaries, virtual environments, runtime credentials, logs, the default benchmark download folder and benchmark results are excluded from Git. Public source URLs and upstream references are retained for reproducibility. No benchmark output is uploaded by default. Enabling a writing judge sends that writing brief and response to its configured endpoint. Dataset downloads, Git source retrieval, release downloads and isolated Python package installation are the network operations used during preparation. For development or an isolated test installation, `STRATABENCH_SETTINGS_FILE` can point to a separate settings file; app workers inherit the same file automatically.

Strata, model weights, runtime packages and datasets retain their respective licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the licenses in prepared version sources.
