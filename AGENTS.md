# Working on Home Infra

- The repository is public. Never commit host inventory, credentials, tunnel IDs,
  real health data, personal email addresses, backup endpoints or machine logs.
- Runtime code stays standard-library-only. Development dependencies belong in
  the `dev` group and `uv.lock`.
- Use argv arrays, not shell interpolation, for runtime commands.
- Host provisioning and deployment are explicit operator actions. Tests must use
  temporary directories and injected process backends, never real launchd jobs,
  system accounts, power settings or network configuration.
- Preserve root-owned immutable releases and service-owned data separation.
- Changes to activation must test rollback, rollback failure and recovery.
- Run `make check`, `bash -n bootstrap.sh`, and build/run the zipapp before pushing.
- Describe verification honestly. CI does not establish a successful factory-reset
  bootstrap, reboot, FileVault recovery or restored off-device backup.
