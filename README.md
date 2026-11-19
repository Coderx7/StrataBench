# StrataBench

Compare **Strata version × model config × reasoning setting** on your own PC. Start with a small comparison, then give the strongest combinations more questions.

This folder is self-contained. The runner uses Python's standard library. It launches Strata using your existing Strata Python environment, reuses your model files and packs, and never updates your installation, installs drivers, changes system settings, or edits your original configs. New engines, temporary configs, logs and results stay here.

## Open the graphical app

**Double-click the StrataBench shortcut on your Desktop.** A graphical app opens in your default browser. There is no terminal window and nothing to install. There is also a `StrataBench.desktop` launcher in this folder.

- **New benchmark:** select versions and model configurations, choose a suite, confirm reasoning (default **xhigh**), and click **Start benchmark**. The plan updates as you change selections.
- **Activity:** follow model loading, question progress, correct/incorrect answers, and errors. **Stop & save** keeps completed answers. Click any correct, incorrect, cutoff, request-error, or pending count to open the **Test explorer** while the benchmark is running. The detailed activity panel contains diagnostic output when needed.
- **Results:** view saved reports inside the app, open full reports, download CSV, resume unfinished runs (including those found after reopening the app), or compare selected runs with matching questions/settings. **Inspect tests** opens a searchable card gallery with combination, difficulty, and task-group filters. Each test shows its question, reference answer, model response, reasoning when supplied, and request details. The same clickable counts appear above saved reports.
- **Strata versions:** add a release tag to build it separately, or import an existing build.
- **Model references:** inspect verified published original-model scores, weight precision, evaluation method, and source links. Results reports and the separate references CSV include the same information alongside local group scores.
- **Your setup:** check hardware, verify/download public datasets, or change the Strata folder used to discover configurations.

The app serves only on your own PC. All interface assets are bundled, with no external fonts, scripts, or analytics. Close the browser tab freely: a running benchmark continues in the background, and the desktop shortcut reopens the same app. Use **Quit StrataBench** to shut down the app after its current operation has finished or been stopped. Stop/resume preserves the benchmark runner's original behavior and checks.

The Desktop shortcut starts the required local server automatically. Once it is running, you can open or bookmark `http://127.0.0.1:18770/` in any browser; a fresh browser session connects automatically. Open the shortcut again after a reboot or after choosing Quit. Do not open `stratabench/web/index.html` as a standalone file: it is the app's interface, not a standalone application. Smaller browser windows keep navigation labels and a Start button visible, with the settings available by scrolling.

You can import config JSON or question JSONL files using normal file choosers. Imports are saved as separate copies in this workspace. Imported configs must include an absolute `cwd` field so their model paths resolve correctly. Exclude other difficulty levels to run just the questions you want. Custom question files use their supplied difficulty labels without the preset difficulty filter.

The desktop launcher uses your existing system Python. It does not register a background service, install a system package, change Strata, or add an application-store dependency.

### Original-model references

The bundled, revision-pinned reference catalog is `datasets/reference-scores.json`. The verified original post-trained **Qwen/Qwen3.8-Flash-Next BF16** reference currently included is **GSM8K: 96.92%**, from [ISTA-DASLab's evaluation of the original BF16 weights](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-P48NVFP4-MoESQ/blob/80266c60ab7b2b357ab01c3675eec5f12afef4b4/README.md#openllm-leaderboard-v1-6-task-average). This is an independent original-weight result, not a Qwen vendor-reported score and not the quantized MoESQ model's result. BF16 means bfloat16; it is distinct from FP16, FP32 and INT8. Both weight and KV precision are recorded when the source supplies them.

That reference uses 5-shot chat with thinking off, greedy sampling and strict matching, averaged over three few-shot seeds. Our suite uses different zero-shot prompts, reasoning settings, token budgets and often smaller question subsets. Published scores are therefore labelled **Context only**. No quantization-loss percentage or synthetic overall original-model score is derived from them. The local leaderboard and its rankings remain based entirely on your own matched runs.

No verified precision-labelled score for this exact MATH-500 numeric/text-only subset, AIME 2024, OpenBookQA or the included individual BBH tasks was found. These entries explicitly say **Not available**, with a reason. Pretrained Base-model aggregates, other AIME years, combined-year results and other quantizations are not substituted. Generated and custom tasks have no published reference. The Qwen model card, original checkpoint dtype and technical report were checked; additional reference results can be curated into the catalog when the original weights, precision and evaluation setup can be verified.

### Version sorting and custom ordering

The default is **Newest first**, sorted numerically (`v0.1.40.12` follows `v0.1.40.4` correctly). On **Strata versions**, select **Oldest first** or **Custom order**. Drag cards, or use **Move earlier / Move later** for keyboard-accessible reordering. Moving a card switches to Custom order and saves it in the local settings. Newly added versions go to the end of a custom order; switching back to a numbered sort includes them automatically. The same order is used by the version selector and for starting the selected benchmark combinations.

### Approximate suite duration

Each suite card shows an approximate range for your selection. Each config card shows the selected suite's estimated time across the selected versions, and the evaluation plan sums the sequential matrix with a per-config breakdown. Changing reasoning, repeats, difficulty selection, token limit, context sizes, versions or configs updates the estimates.

These are **planning ranges**, not promised completion times. Initial assumptions distinguish model/quantization families on your RTX 3080 / 64 GB PC; untested settings within a family can share a range. Larger disk-streamed quants receive slower throughput assumptions. Each combination includes loading and warm-up; version builds and dataset/model downloads are excluded. A local timing history automatically refines estimates only for the same config hash, version, reasoning setting, difficulty and token budget. Errors are excluded; completed and cut-off responses can inform duration. A few short arithmetic measurements do not calibrate hard reasoning. Default/server reasoning is kept separate from explicitly selected xhigh timings.

The intervals are deliberately broad when there are few measurements or untested difficulty levels. Thinking length, context paging, adaptive expert caches, SSD speed and other PC activity can move real time outside a displayed range. Long-context estimates also include approximate document-reading time and a context-capacity notice when applicable. Estimating never starts a model or downloads a dataset.

## Optional terminal interface

Open a terminal in this folder and run:

```bash
./start.sh
```

This now opens the graphical app. To use the original terminal menu instead, run `./bench`. Choose **1 — Run benchmarks**, select one or more prepared versions and configs, and choose a preset. The menu **asks for reasoning on every new run**, with **xhigh** as the default. Press Enter to accept defaults. Choose `off`, `low`, `medium`, `high`, `xhigh`, or `default` to leave reasoning to the server/config. On your current Qwen template, `high` maps to `xhigh`.

Your current **v0.1.40.4** engine and matching server are already copied into `versions/v0.1.40.4/`. The menu discovers your original model configs in:

```text
/media/hossein/SSD/strarta_stuff/Strata
```

The public datasets have already been downloaded and verified. Benchmark runs can work offline. Adding an uncached Strata version needs internet access once.

**Close other model servers before a managed run.** The runner uses one model and one request at a time, which suits your RTX 3080 10 GB and 64 GB RAM. It stops only the server and engine it starts. To test an already running server, use the attached-server command below instead.

After a run, choose **5 — Open a report**. Results include an HTML comparison, CSV leaderboard, JSON summary, full questions, raw API responses, settings, cutoffs and errors. Choose **8** to compare saved runs made with identical questions/settings/scoring code. This lets you test one version today and another later.

## Add any release without changing your installation

Choose **2 — Add a Strata version**, enter a release tag, and wait for its one-time build. Or:

```bash
./bench add-version v0.1.44.1
```

That tag is an **example**, not a recommendation. Pick the versions you want to investigate. The builder uses the existing CUDA compiler, CMake, C++ compiler and Git. It builds for your RTX 3080 (`sm_86`) with four compile jobs, downloads the version's pinned ggml source into this folder, and reuses your existing Python environment. It does not run Strata's installer or update script. The original Git repository is read for already available tags; missing tags are fetched into a separate repository here.

Each version gets **its own matching Python server**, engine, source commit, binary checksum and build log. It is a full server-and-engine version comparison. Keeping a new server while merely swapping an old binary could otherwise distort the comparison.

Build progress is in `versions/TAG/build.log`. If a release requires changed dependencies or has an incompatible source layout, the build stops with the reason; nothing is installed automatically. You can specify an existing compatible Python environment and additional build flags:

```bash
./bench add-version v0.1.44.1 --jobs 4 --python /path/to/existing/python \
  --cmake-arg=-DSTRATA_MMQ_KQUANTS=ON
```

Build defaults use Release, CUDA architecture 86, native experts, K-quant MMQ and Q6K experts. These broadly match your installed build. CMake may ignore options unavailable in older versions. Build flags and ggml revisions are saved; compiler versions and engine defaults may still differ between releases. To compare custom builds with exactly your preferred flags, build them yourself in separate folders and import them:

```bash
./bench snapshot --name my-build --source /path/to/Strata \
  --exe /path/to/Strata/engine/strata --python /path/to/Strata/.venv/bin/python
```

Snapshotting copies the engine and server; it never replaces a previously registered version. Give changed builds a new label. Vision tests are not included; imported snapshots also copy an available image encoder, but a new text-only build does not compile one.

## Presets

| Preset | Questions per combination | Purpose |
| --- | ---: | --- |
| `smoke` | 7 | One generated check per group, across all five difficulties; validates the workflow. |
| `quick` | 69 | A first screen. Scores are noisy at this size. |
| `standard` | 276 | A more useful comparison of shortlisted combinations. |
| `deep` | 648 | More questions, including all 30 AIME 2024 problems. |
| `full` | 4,363 | All included public and generated cases; can take days on slower configs. |
| `context` | 12 | Retrieval at three positions in each of four long-text sizes. |

Public tasks: **GSM8K test**, eight **BIG-Bench Hard** tasks, **OpenBookQA test**, **AIME 2024**, and the **346 numeric/rational, text-only questions from MATH-500**. Generated tasks cover arithmetic, structured JSON, Python tracing, graph paths, subset counting, exact scheduling and a narrow Persian arithmetic check.

Generated tasks change when you change `--seed`, and have independently calculated reference answers. Default seed is `20261119`. Sampling is deterministic and stratified by task group and difficulty. Public source revisions are pinned where available; all downloads are locked by SHA-256, including the AIME dataset viewer snapshot. Changed cached data is rejected. Seed changes both generated questions, sampled public questions and generation seeds, so use the same seed for every comparison.

Difficulty labels for generated problems and BBH groups are approximate. MATH levels 1–5 map to easy through extreme; AIME supplies competition-level extreme problems. A high score on arithmetic alone says little about the hardest cases.

These are **custom zero-shot diagnostic scores**, not official benchmark leaderboard numbers. Well-known public questions may have been in training data. Algorithm tasks test reasoning about programs and algorithms; the suite does not execute model-written programs, test software patches, use an LLM judge, measure creative writing, or test vision/tool use. Add examples from your real work for a more relevant decision.

## Repeatable command-line runs

```bash
# Your current version with an existing config; no model/config edits.
./bench run --versions v0.1.40.4 \
  --configs strata-iq3_s_q4_262k_cpu_vision \
  --profile quick --reasoning xhigh

# After preparing the second version: all four combinations, sequentially.
./bench run --versions v0.1.40.4 v0.1.44.1 \
  --configs strata-iq3_s_q4_262k_cpu_vision strata-unsloth-ud-iq4_xs-v31 \
  --profile standard --reasoning xhigh --repeats 3

# Inspect the exact scope without loading a model.
./bench run --configs strata-iq3_s_q4_262k_cpu_vision \
  --profile standard --reasoning xhigh --dry-run

# Only the extreme-difficulty questions from the deep preset.
./bench run --configs strata-iq3_s_q4_262k_cpu_vision \
  --profile deep --only extreme --reasoning xhigh

# Extend long-context tests. Sizes are WORDS, not tokenizer tokens.
./bench run --configs strata-iq3_s_q4_262k_cpu_vision \
  --profile context --context-words 2000 8000 16000 32000 64000 \
  --reasoning xhigh
```

The menu prints an equivalent command before each run. Configs can be full paths, names with or without `.json`, or `--configs all` for all discovered configs except symlink aliases. Some old configs may point to missing model files; these are reported as failures, not silently repaired. A config's GPU allocations may still fail on a particular release: that is useful compatibility evidence and is shown explicitly.

CLI runs prompt for reasoning when omitted in an interactive terminal. Noninteractive use defaults to xhigh. To compare reasoning settings, run each setting separately. Saved reports with different reasoning settings are deliberately kept separate because the evaluation budget changed; view the reports side by side.

## Thinking budgets and timing

Default maximum answer tokens, **including thinking**, are 2,048 / 4,096 / 8,192 / 12,288 / 16,384 for easy / medium / hard / very hard / extreme. Set `--max-tokens 32768` to use a larger common limit. Some extremely hard problems will need it. A cutoff is counted as incorrect even if an early candidate answer was correct. Review cutoff rates before concluding that a model is weaker.

Default sampling is temperature 0, top-p 1, positive seed; other sampling defaults from your config remain in effect and are recorded. Repeats use consecutive generation seeds. Temperature 0 can make repeats identical, and GPU arithmetic/adaptive expert caches can still make runs differ. For variability testing, use e.g. `--temperature 0.6 --repeats 3` consistently for all combinations. More distinct questions is usually more useful than identical greedy repeats.

Per-request timeout is 30 minutes; startup timeout is 15 minutes. Change with `--timeout` / `--startup-timeout` (seconds). Timeout/disconnect/server errors stop that combination to avoid queuing requests behind a stuck generation; the runner proceeds to the next combination after shutting down its own server. HTTP request errors are saved without retries; three consecutive errors stop the combination. There is no automatic retry that could hide reliability problems.

Reports show **end-to-end output throughput**, calculated from the server's completion-token usage and total request time. This includes prefill, and may include reasoning in token usage. It is not pure decode speed, time to first token, or energy usage. Initial model loading and the fixed unscored warm-up are saved separately and excluded from answer timing.

## Reading the scores

The **balanced score** is the mean accuracy across task groups; large datasets do not drown out smaller groups. The ordinary accuracy is also shown. Every planned answer is in the denominator. Errors, cutoffs and unanswered questions score zero. Incomplete combinations are excluded from ranking.

The report shows per-difficulty and per-group accuracy, then compares the best observed complete combination with other complete combinations using a paired, stratified question-level bootstrap interval. Repeats of the same question stay together. This is uncertainty for this task mix, not proof of general superiority. Very small samples and all-identical outcomes can produce deceptively narrow intervals. Use quick runs to shortlist, then standard/deep and new seeds to check that a lead persists.

The final answer is scored against a known answer, never hidden reasoning. Numeric integers, decimal values and simple rational fractions are compared exactly. The suite accepts a final JSON answer, a boxed math answer, a `Final answer:` line or a short standalone answer. It does not guess the answer by scanning arbitrary prose for numbers. Equivalent symbolic expressions outside supported numeric forms can be marked wrong; inspect extracted answers in the report when that matters. JSON formatting is recorded separately from content accuracy. Structured-data questions require exact field/value types.

Each answer row includes the full request, raw API response, expected answer, extracted answer, latency, usage and failure flags. Metadata includes source config, runtime overrides, version/server/tokenizer/library hashes, model-file sizes and modification times, hardware, build settings, inherited engine environment variables and scoring-code hash. Huge GGUFs/packs are **not fully hashed or duplicated**; keep their contents fixed between runs. Resume rejects changed configs, tokenizer files, known input metadata, code, settings or inherited engine environment. Recorded weights metadata is not a cryptographic guarantee that every shard/pack stayed unchanged.

## Stop, resume and compare later

In the GUI, choose **Stop & save** in Activity, then **Resume** from Activity, Results, or the Test explorer. Unfinished runs are also discovered after an app restart or a crash. Resume uses the saved questions, reasoning, settings, and configurations; it never substitutes the current New benchmark selections. Correct, incorrect, and cutoff answers remain saved; pending evaluations and request errors are retried. The test counts and lists use the latest attempt for each question, combination, and repeat.

From the terminal, press **Ctrl+C**. Completed answers are flushed to disk individually. Your original installation and any unrelated server are left alone.

```bash
./bench resume /absolute/path/to/results/RUN_FOLDER
./bench report /absolute/path/to/results/RUN_FOLDER
./bench compare /absolute/path/to/results/RUN_A /absolute/path/to/results/RUN_B
```

Resume uses the exact saved questions/options and validates the original target inputs. It keeps scored answers, retries transport/server-error answers, and restarts failed or unfinished combinations. Previous error attempts remain in the JSONL log; reports use the latest attempt per question/repeat. A resumed engine has fresh in-memory expert/prompt-cache state, so it is not guaranteed to reproduce the uninterrupted trajectory. That session's effective config and logs are saved in a new subfolder.

Only runs with identical question sets, request settings, inherited engine environment and scoring code can be combined into a ranked report. Differences in hardware are recorded but not used to block comparison: compare accuracy across PCs carefully and compare timing on the same PC. If the same combination appears several times, a combined report uses the latest complete run, or the latest incomplete run if none is complete.

## Test an already running server

```bash
./bench run --endpoint http://127.0.0.1:8080/v1 \
  --label 'v0.1.40.4 / my-config' --profile quick --reasoning xhigh
```

This mode never starts or stops your server. The version/config label is user supplied and is marked as such; the runner cannot verify the underlying executable or config. Set `STRATABENCH_API_KEY` if that server needs a key. Use `--model NAME` if its API requires a particular model name. Leave that server idle while benchmarking. A timed-out attached-server request may continue generating; stop it yourself before resuming.

## Add your own problems

Copy `examples/custom-tasks.jsonl` and add questions with known answers. Each line needs a unique `id`, `group`, `difficulty`, `prompt`, `answer`, and `grader` (`numeric`, `choice`, `exact`, or `json`).

```bash
./bench run --configs strata-iq3_s_q4_262k_cpu_vision \
  --tasks examples/custom-tasks.jsonl --reasoning xhigh
```

Use `./bench configs`, `./bench versions`, `./bench tasks --profile standard`, `./bench doctor`, or `./bench --help` for inspection. `doctor` only reads system state. Managed text tests disable the separate image encoder consistently while preserving the engine's `--vision` flag and other allocation settings. Use `--keep-vision` only with a prepared matching encoder if you want its memory overhead included. Working directories, logs, saved-profile outputs and temporary files are redirected into the result folder. Existing learned profiles are copied as initial state. Pack/model inputs remain shared read-only inputs to the engine; this is process isolation, not an operating-system write-protection boundary for arbitrary third-party engine code.

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Tests cover answer extraction, exact numeric grading, no credit for hidden thinking/cutoffs, generated reference answers, config isolation, resumability, failure handling, incompatible-run rejection and report generation with a local fake API. A two-question **real GPU smoke test** on your copied v0.1.40.4 / IQ3_S 262K config also passed with xhigh reasoning. This verifies operation, not a meaningful ranking. Additional versions are prepared when you choose them; no cross-version winner has been measured yet.
