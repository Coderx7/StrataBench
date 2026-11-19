# Dataset provenance

Raw source data and available license texts are cached in `datasets/raw/`. Exact download URLs, revision information, SHA-256 checksums and retrieval times are in `datasets/sources.lock.json`. The benchmark does not upload model prompts, answers or local configs to an external judge.

| Material | Source | Terms / attribution |
| --- | --- | --- |
| GSM8K test split | [OpenAI grade-school-math](https://github.com/openai/grade-school-math) | MIT; retained in `gsm8k-LICENSE`. Cobbe et al., *Training Verifiers to Solve Math Word Problems* (2021). |
| Eight BBH tasks | [BIG-Bench Hard](https://github.com/suzgunmirac/BIG-Bench-Hard) | MIT; copyright (c) 2022 suzgunmirac; retained in `bbh-LICENSE`. Suzgun et al., *Challenging BIG-Bench Tasks and Whether Chain-of-Thought Can Solve Them* (2022). |
| OpenBookQA test split | [AllenAI OpenBookQA](https://github.com/allenai/OpenBookQA) | Apache-2.0 license retained in `openbookqa-LICENSE`; official dataset archive URL from the repository download script. Mihaylov et al., *Can a Suit of Armor Conduct Electricity?* (2018). |
| MATH-500 | [HuggingFaceH4 snapshot](https://huggingface.co/datasets/HuggingFaceH4/MATH-500), [OpenAI PRM800K splits](https://github.com/openai/prm800k#math-splits) | Upstream MATH/PRM800K terms apply. This suite reads the cached source and selects only numeric/rational text-only examples; it does not claim an official score or relicense competition questions. Hendrycks et al., *Measuring Mathematical Problem Solving With the MATH Dataset* (2021); Lightman et al., *Let's Verify Step by Step* (2023). |
| AIME 2024 | [math-ai/aime24](https://huggingface.co/datasets/math-ai/aime24) | Dataset card declares Apache-2.0; competition problem rights remain with their original owners. AIME is an MAA competition. Rows snapshot is checksum-locked locally. |

The generated arithmetic, JSON transformation, Python tracing, graph, subset-counting, scheduling, Persian arithmetic and context-retrieval tasks are authored for this suite. Their difficulty labels are heuristic.

Strata itself is a separate project: [Niko1221/Strata](https://github.com/Niko1221/Strata). Its license is copied alongside version snapshots or included in fetched sources. Model/GGUF licenses are unchanged; models are reused from your existing installation.
