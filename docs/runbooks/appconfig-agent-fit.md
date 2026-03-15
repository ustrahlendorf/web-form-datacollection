# AppConfig Agent Fit Assessment

Technical and operational fit evaluation for adopting AWS AppConfig Agent in this repository's Lambda runtime read path.

## Current state (Yes/No on usage)

- **AppConfig Agent currently in use:** **No**
- Runtime config reads use direct AppConfigData SDK calls (`start_configuration_session` + `get_latest_configuration`) in:
  - `src/handlers/auto_retrieval_handler.py`
  - `src/handlers/auto_retrieval_config_handler.py`
- Infrastructure currently sets AppConfig identifiers and IAM for direct calls, but does not configure an AppConfig Agent Lambda extension/layer or `localhost:2772` runtime path.

## Existing Lambda call pattern fit

### Observed pattern

- `SchedulerOnceDailyStack` invokes `src.handlers.auto_retrieval_handler.lambda_handler` on a daily cron.
- `SchedulerFrequentStack` invokes the same handler every 15 minutes (within active windows).
- The frequent path can trigger two AppConfigData reads in one invocation when not skipped:
  - `_check_active_window_and_maybe_skip()` -> `_load_appconfig()`
  - `_load_config()` -> `_load_appconfig()` again
- Config API GET (`src/handlers/auto_retrieval_config_handler.py`) also reads effective config via AppConfigData on demand.

### Why this matters

- Frequent scheduler traffic amplifies repeated AppConfigData reads for the same configuration document.
- AppConfig Agent can serve the document from local cache (`localhost`) with background refresh, reducing per-invocation data-plane calls and read latency variance.

## Technical fit

### Pros for this repository

- Reduces repetitive AppConfigData calls in frequent scheduler runtime path.
- Improves consistency/latency of config reads by serving from local endpoint.
- Keeps existing AppConfig hosted profile and deployment workflow unchanged.
- Can retain existing fallback behavior (SSM fallback flags) as migration safety net.

### Technical costs/risks

- Adds Lambda extension dependency (versioning, rollout, and runtime compatibility management).
- Requires runtime read-path change from boto3 AppConfigData calls to local HTTP fetch path.
- Requires startup/failure-mode handling for extension availability during cold starts.
- Needs additional observability to distinguish "agent unavailable" vs "stale config served" vs "AppConfig service issue."

## Operational fit

### Positive operational impact

- Lower AppConfigData call volume for scheduled workloads (especially frequent scheduler).
- Less coupling between invoke frequency and AppConfigData API usage.
- Better behavior under transient AppConfigData API throttling/network jitter because reads are local-first.

### Operational trade-offs

- One more moving part in Lambda runtime lifecycle (extension health and upgrades).
- Runbooks/on-call checks must include agent endpoint and extension logs.
- Deployment validation must verify both extension startup and config freshness behavior.

## Recommendation

**Adopt now for scheduler runtime reads (`auto_retrieval_handler`), keep direct SDK in config-management API handler.**

Rationale:

- The frequent scheduler pattern creates repeated reads and is the clearest benefit target.
- Migration scope stays small if limited to the scheduled runtime path first.
- Direct SDK in `auto_retrieval_config_handler` is low-frequency and operationally clear for management APIs.

If minimizing operational complexity is currently the top priority, defer only until extension ownership/monitoring is explicitly assigned; otherwise this is a good incremental adoption candidate.

## Minimal migration scope (if adopting)

1. **Infrastructure**
   - Add AWS AppConfig Agent Lambda extension/layer to both scheduler Lambdas:
     - `infrastructure/stacks/scheduler_once_daily_stack.py`
     - `infrastructure/stacks/scheduler_frequent_stack.py`
   - Add only required agent environment tuning (if needed), keep existing AppConfig IAM permissions initially.

2. **Runtime**
   - Update `src/handlers/auto_retrieval_handler.py` to fetch config from local agent endpoint first.
   - Keep existing direct SDK and/or SSM fallback as controlled fallback path during rollout.
   - Avoid changing `src/handlers/auto_retrieval_config_handler.py` in phase 1.

3. **Operations**
   - Add CloudWatch log checks for extension startup and local fetch failures.
   - Validate cold-start behavior and stale/empty-config fallback handling.
   - Run one full daily cycle and one full frequent-window cycle before disabling any fallback path.
