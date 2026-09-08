# Contributing

Use Python 3.13 and uv. Run `make setup` and `make check` before opening a pull
request. Keep runtime dependencies in the standard library unless a concrete need
justifies increasing the trusted deployment surface.

Tests must use temporary directories and injected backends. Never point tests at
the real `/Library/LaunchDaemons`, `/etc/home-infra` or `/opt/home-infra`.
Changes to activation must exercise both failed deployment and failed recovery.

Include the user-visible behavior, relevant tests and any required migration in
your PR. Use example domains and identities. Do not attach personal inventory,
credentials, tunnel IDs, screenshots containing account details or health data.

For local real-host trials, use a disposable Mac and record which acceptance checks
were performed. CI passing is not equivalent to factory-reset or reboot validation.
