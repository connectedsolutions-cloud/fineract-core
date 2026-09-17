# Production deployment

This directory packages the sync engine as a one-shot container controlled by
systemd. The timer invokes a new immutable plan on every run; it never reuses a
historical plan and never performs a fresh/clean reset.

Two production workflows are packaged. `prod-party-resync` is the conservative
default and contains `clients`, `employees`, `client-staff-assignments`,
`client-pep`, and `client-family-references`. `prod-full-resync` contains all 15
available services and mirrors the dependency-complete local delta graph. Every
selected service declares a reviewed `full_resync` contract; the broader
workflow must still pass the production-like acceptance gates below before it
is selected by the service or timer.

## Build and publish

From `tools/arissto-sync`:

```bash
docker build --pull --build-arg ARISSTO_SYNC_RELEASE=GIT_SHA \
  -t REGISTRY/credesal/arissto-sync:GIT_SHA .
docker push REGISTRY/credesal/arissto-sync:GIT_SHA
```

Deploy immutable image tags. Do not schedule `latest`.

## Host layout

The expected Linux host paths are:

```text
/etc/arissto-sync/prod.env       root:root 0600; database and API credentials
/etc/arissto-sync/service.env    root:root 0600; image tag and production fingerprint
/var/lib/arissto-sync/           persistent state and workflow logs
/var/backups/arissto-sync/       consistent SQLite backups
/etc/systemd/system/arissto-sync-prod.service
/etc/systemd/system/arissto-sync-prod.timer
/etc/systemd/system/arissto-sync-backup.service
/etc/systemd/system/arissto-sync-backup.timer
```

`ARISSTO_SYNC_PROD_WORKFLOW` in `service.env` selects the packaged workflow.
The example deliberately defaults to `prod-party-resync`. Do not change it to
`prod-full-resync` until the full workflow has passed unchanged replay, load,
cutoff, quarantine, and recovery acceptance against the production candidate.

Copy the two example environment files and the systemd units, fill the values,
then protect the environment files:

```bash
sudo install -d -o root -g root -m 0750 /etc/arissto-sync
sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/arissto-sync
sudo install -d -o 10001 -g 10001 -m 0750 /var/backups/arissto-sync
sudo install -m 0600 deploy/prod.env.example /etc/arissto-sync/prod.env
sudo install -m 0600 deploy/service.env.example /etc/arissto-sync/service.env
sudo install -m 0644 deploy/arissto-sync-prod.service /etc/systemd/system/
sudo install -m 0644 deploy/arissto-sync-prod.timer /etc/systemd/system/
sudo install -m 0644 deploy/arissto-sync-backup.service /etc/systemd/system/
sudo install -m 0644 deploy/arissto-sync-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arissto-sync-backup.timer
```

The backup timer creates a consistent SQLite backup every day at 01:30 and keeps
30 days. The state contains mappings, accepted checkpoints, plan/run identities,
reconciliation summaries, and failure history. Copy backups to separate durable
storage according to the server's disaster-recovery policy.

## Establish the production baseline

Full re-sync is continuation after an accepted initial migration. For each
selected service, bootstrap its first checkpoint from an existing production
child run whose reconciliation is `ok: true`:

```bash
docker run --rm \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint bootstrap \
  --workflow prod-party-resync --service clients --run CLIENT_RUN_ID \
  --target prod --confirm-production TARGET_FINGERPRINT

docker run --rm \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint bootstrap \
  --workflow prod-party-resync --service employees --run EMPLOYEE_RUN_ID \
  --target prod --confirm-production TARGET_FINGERPRINT

docker run --rm \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint bootstrap \
  --workflow prod-party-resync --service client-staff-assignments \
  --run CLIENT_STAFF_RUN_ID --target prod \
  --confirm-production TARGET_FINGERPRINT

docker run --rm \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint bootstrap \
  --workflow prod-party-resync --service client-pep --run PEP_RUN_ID \
  --target prod --confirm-production TARGET_FINGERPRINT

docker run --rm \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint bootstrap \
  --workflow prod-party-resync --service client-family-references \
  --run FAMILY_REFERENCE_RUN_ID --target prod \
  --confirm-production TARGET_FINGERPRINT
```

The command refuses a failed, unreconciled, wrong-service, or wrong-target run.
Review the frozen baseline:

```bash
docker run --rm --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow checkpoint show --workflow prod-party-resync --target prod
```

The full production workflow has its own checkpoint namespace. Before it can be
planned, repeat the bootstrap command with `--workflow prod-full-resync` for
every one of these services, using that service's accepted production child run:

```text
clients
employees
client-staff-assignments
client-pep
client-family-references
client-personal-family-references
membership-share-capital
savings-deposits
savings-account-parties
native-share-capital
aml-alerts
loans
dte-history
mobile-collections
accounting-journal-entries
```

For `accounting-journal-entries`, the checkpoint command accepts the workflow
service ID while validating the underlying `accounting` child-run block. All 15
accepted child plans must carry the same accounting cutoff. Planning fails
closed if a checkpoint is absent or the cutoffs differ.

## Acceptance before scheduling

Keep the timer disabled. First inspect the complete production definition and
create an immutable plan for review:

```bash
docker run --rm --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow inspect --workflow prod-full-resync \
  --target prod --run-mode full-resync

docker run --rm --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow plan --workflow prod-full-resync \
  --target prod --run-mode full-resync \
  --confirm-production TARGET_FINGERPRINT
```

Only after plan review, run one synchronous full re-sync manually with the timer
still disabled:

```bash
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --security-opt no-new-privileges \
  --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow run --workflow prod-full-resync --target prod \
  --run-mode full-resync --confirm-production TARGET_FINGERPRINT
```

Require a completed workflow, successful reconciliation for every service, and
no unreviewed quarantine. Run it a second time with no Arissto changes and
require zero unintended writes. Also prove bounded runtime and target load,
retry/recovery from an interrupted non-production rehearsal, and exact cutoff
continuity across all financial-service checkpoints.

After those gates pass, set
`ARISSTO_SYNC_PROD_WORKFLOW=prod-full-resync` in `/etc/arissto-sync/service.env`,
run `sudo systemctl start arissto-sync-prod.service` once, and review its result.
Changing this variable is the explicit deployment promotion; merely shipping
the workflow definition does not schedule it.

The production timer is set to 06:00 in `America/El_Salvador`. Verify the parsed
schedule on the EC2 instance before enabling it:

```bash
systemd-analyze calendar '*-*-* 06:00:00 America/El_Salvador'
```

Only after acceptance:

```bash
sudo systemctl enable --now arissto-sync-prod.timer
systemctl list-timers arissto-sync-prod.timer
```

## Operations

Run history and recurring failures remain in the persistent SQLite state:

```bash
docker run --rm --env-file /etc/arissto-sync/prod.env \
  --mount type=bind,src=/var/lib/arissto-sync,dst=/var/lib/arissto-sync \
  IMAGE workflow history --workflow prod-party-resync --target prod
```

A non-zero service exit marks the systemd unit failed. Connect the host's
standard systemd failure notification mechanism to the approved destination.
The deployment does not embed Slack, email, or paging credentials.

Production retention preserves plan/run/checkpoint/failure identities. It may
compact successful historical item payloads, but must not delete the audit
trail required to compare runs.
