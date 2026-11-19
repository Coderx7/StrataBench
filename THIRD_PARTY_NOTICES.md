# Dataset provenance

Raw source data and available license texts are cached in `datasets/raw/`. Exact download URLs, revision information, SHA-256 checksums and retrieval times are in `datasets/sources.lock.json`. Scoring runs locally by default. If the optional writing judge is enabled, writing briefs and responses are sent to the configured judge endpoint; model configuration files are not sent.

The standard benchmark library is downloaded only through its explicit preparation controls. Pinned upstream source, license files, data and isolated evaluator environments are stored in the ignored `benchmarks/` folder. Each suite’s `ready.json` records its revision, source checksums and package snapshot. Dataset and source revisions are also saved in run manifests. These integrations use upstream scoring code with a StrataBench generation adapter; sampled or adapted scores are labelled accordingly.

| Integration | Upstream | Terms |
| --- | --- | --- |
| IFEval | [Google Research](https://github.com/google-research/google-research/tree/master/instruction_following_eval) | Apache-2.0 source; see the pinned upstream license. |
| BFCL Python AST categories | [Berkeley Gorilla](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) | Apache-2.0; the full leaderboard is not replicated. |
| MMMU validation | [MMMU](https://github.com/MMMU-Benchmark/MMMU), [dataset card](https://huggingface.co/datasets/MMMU/MMMU) | Upstream code license and dataset/source-image terms apply independently. |
| WritingBench | [X-PLUG](https://github.com/X-PLUG/WritingBench) | See the downloaded upstream license and source-material terms. Published judge prompts and per-question rubrics are used; judge-model terms also apply. |
| SWE-bench Lite, optional | [SWE-bench](https://github.com/SWE-bench/SWE-bench), [dataset card](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite) | MIT evaluator; issue repositories and container contents retain their own licenses. No issue images are bundled with this project. |

WritingBench requires an explicitly configured judge endpoint and sends the writing brief, model response and rubric there. The separate writing diagnostic keeps its judge optional. SWE-bench preparation is disabled by default and downloads its issue images only when an explicitly enabled SWE run is started.

| Material | Source | Terms / attribution |
| --- | --- | --- |
| GSM8K test split | [OpenAI grade-school-math](https://github.com/openai/grade-school-math) | MIT; retained in `gsm8k-LICENSE`. Cobbe et al., *Training Verifiers to Solve Math Word Problems* (2021). |
| Eight BBH tasks | [BIG-Bench Hard](https://github.com/suzgunmirac/BIG-Bench-Hard) | MIT; copyright (c) 2022 suzgunmirac; retained in `bbh-LICENSE`. Suzgun et al., *Challenging BIG-Bench Tasks and Whether Chain-of-Thought Can Solve Them* (2022). |
| OpenBookQA test split | [AllenAI OpenBookQA](https://github.com/allenai/OpenBookQA) | Apache-2.0 license retained in `openbookqa-LICENSE`; official dataset archive URL from the repository download script. Mihaylov et al., *Can a Suit of Armor Conduct Electricity?* (2018). |
| MATH-500 | [HuggingFaceH4 snapshot](https://huggingface.co/datasets/HuggingFaceH4/MATH-500), [OpenAI PRM800K splits](https://github.com/openai/prm800k#math-splits) | Upstream MATH/PRM800K terms apply. This suite reads the cached source and selects only numeric/rational text-only examples; it does not claim an official score or relicense competition questions. Hendrycks et al., *Measuring Mathematical Problem Solving With the MATH Dataset* (2021); Lightman et al., *Let's Verify Step by Step* (2023). |
| AIME 2024 | [math-ai/aime24](https://huggingface.co/datasets/math-ai/aime24) | Dataset card declares Apache-2.0; competition problem rights remain with their original owners. AIME is an MAA competition. Rows snapshot is checksum-locked locally. |

The generated arithmetic, JSON transformation, Python tracing, graph, subset-counting, scheduling, Persian arithmetic and context-retrieval tasks are authored for this suite. Their difficulty labels are heuristic.

Strata itself is a separate project: [Niko1221/Strata](https://github.com/Niko1221/Strata). Its license is copied alongside version snapshots or included in fetched sources. Model/GGUF licenses are unchanged; models are reused from your existing installation.
