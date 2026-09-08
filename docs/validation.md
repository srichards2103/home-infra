# Validation

Automated validation runs in temporary directories. No test applies the playbook
to the developer's Mac or changes its real launchd services.

The suite covers strict manifests, deterministic packages, malicious archives,
digest mismatch, idempotent deployment, immutable versions, health-check failure,
rollback, interrupted recovery, lock contention, secret permissions, plist rendering,
backup command construction and a real HTTP process deployment/rollback exercise.
Ansible syntax checking and template parsing supplement controller tests.

Run `make setup && make check`, `bash -n bootstrap.sh`, and build/run the zipapp
before publishing changes. CI runs portable checks on both Linux and macOS. Its
process integration uses an injected subprocess backend, **not system launchd**.

## Pending host acceptance

The following require a disposable Mac or an explicitly scheduled maintenance
window. They have not been claimed as passed by this repository's initial build:

- Apply from a clean installation and verify a second apply reports no changes.
- Verify hidden service accounts cannot log in and apps cannot write release files.
- Cold boot with the chosen FileVault configuration and recover remote access.
- Deploy a healthy release through actual launchd; deploy a broken release and
  confirm the prior release returns on the same port.
- Interrupt activation and verify `recover` restores the documented state.
- Test private-route allow/deny policy from separate clients and public authentication.
- Run a scheduled backup, full-content integrity check and replacement-host restore.
- Check log growth, disk space, package upgrades and alerting in sustained operation.

Apple silicon is the primary configuration. Paths for Intel are supported by the
provisioner, but the example application manifest must be adjusted as documented.
