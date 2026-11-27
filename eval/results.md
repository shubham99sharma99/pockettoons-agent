# Eval results

Not run yet: the build environment had no Anthropic API key. Run:

```bash
python -m eval.run_eval
```

This runs all 21 golden questions through the live agent, scores numeric answers
within tolerance against reference SQL recomputed from the database, grades
behaviour with an LLM judge, and overwrites this file with the pass/fail table and
failure analysis.
