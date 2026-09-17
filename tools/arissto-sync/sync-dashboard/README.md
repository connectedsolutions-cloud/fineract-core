# Arissto Sync Runs dashboard

A lightweight local interface for the workflow state preserved under
`.arissto-sync/cycles/`. Its reporting queries open SQLite files with `mode=ro`
and enable SQLite `query_only`.

From `tools/arissto-sync/`:

```bash
.venv/bin/python sync-dashboard/server.py
```

Then open <http://127.0.0.1:8787>. Use `--port` or `--state-dir` to override the
defaults.

The dashboard shows preserved cycles and workflow runs, the latest attempt for
each service, run-level metrics, and a paginated/filterable failure ledger. The
"All attempts" filter reveals the complete retry history.

The failure ledger distinguishes retryable system failures from structural
data, validation, configuration, and target-state failures. Unknown signatures
that recur unchanged are marked persistent rather than automatically declared
structural. Service attempt numbers are workflow executions created by resume or
automatic recovery; they do not imply that every entity was blindly retried.

## Planning a fresh/clean run or full re-sync

The dashboard supports **Fresh/clean run** and local **Full re-sync** modes. A fresh run creates a
fresh cycle after the whole disposable tenant has been restored from its
captured baseline. The operator names the
restored baseline and either confirms that local Fineract was already restored,
or enables **Reset local Fineract first**. The optional reset requires a
disposable tenant plus the exact `TENANT:DATABASE` confirmation. It stops
Fineract, invokes the whole-tenant baseline restore, restarts Fineract, verifies
readiness, and only then creates the cycle. Without that option, cycle creation
only records tracking state and does not reset Fineract.

Full re-sync selects an existing open cycle and never restores or resets the
tenant. Every selected service must have an accepted checkpoint in that cycle;
the saved plan freezes those checkpoints and applies only new or changed source
hashes. Missing checkpoints, undeclared contracts, and unsupported drift fail
closed. Resumed sync remains a CLI recovery operation for an incomplete run.
The mode contracts are documented in
[`ARISSTO_SYNC_RUN_MODES.md`](../../../../docs/ARISSTO_SYNC_RUN_MODES.md).
Next, select the desired services and prepare the immutable plan. Approving the
reviewed plan immediately launches the sync. Required dependencies are selected
and locked automatically. For example, selecting `loans` produces
`clients → employees → loans` without adding savings or mobile collections.
The dashboard hard-codes `--target local`, refuses to create a fresh cycle while
any local workflow is queued/running, and never offers production.
Planning can read Arissto and local Fineract during preflight; launching starts
the existing detached orchestrator and can write synchronized records to local
Fineract. Cross-origin requests are rejected and every POST requires the
per-process launch token.
