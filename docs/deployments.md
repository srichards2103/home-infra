# Deployments

Provision the service account before deploying. Run the following commands on the
target Mac from the checkout. The Apple silicon example requires Python 3.13 at its
Homebrew path; change the manifest to `/usr/local/...` on Intel.

```sh
uv run homeinfra validate examples/hello/service.json
uv run homeinfra package examples/hello artifacts/hello-v1.tar.gz
shasum -a 256 artifacts/hello-v1.tar.gz
```

Inspect the staging directory before packaging. The packager excludes `.git`,
`.venv`, `.env*` and common caches, but cannot detect arbitrary secrets embedded in
source code. It refuses symlinks and special files. This intentionally excludes
ordinary virtualenv archives; use an application-specific relocatable build or
explicitly provision its runtime dependencies.

Use the digest printed by packaging as `EXPECTED_SHA256` below:

```sh
sudo /opt/home-infra/bin/homeinfra deploy examples/hello/service.json \
  artifacts/hello-v1.tar.gz --version v1 --sha256 EXPECTED_SHA256
sudo /opt/home-infra/bin/homeinfra status hello
curl http://127.0.0.1:8090/healthz
```

Reusing a version with the same archive and manifest is a healthy no-op. Reusing it
with different contents is rejected. To update, build a new archive and use a new
version, ideally the application Git commit SHA. Existing releases remain available:

```sh
sudo /opt/home-infra/bin/homeinfra rollback hello
sudo /opt/home-infra/bin/homeinfra rollback hello --version v1
sudo /opt/home-infra/bin/homeinfra recover hello
```

Rollback checks health too. If both activation and recovery fail, the transaction
journal remains and further deployments stop until `recover` succeeds. Investigate
logs before retrying. A process kill or power failure can also leave this journal.
Rollback restores code and its manifest, **not database state or secrets**. Use
backward-compatible migrations and take application-consistent backups first.

## Deploy from another computer

The included helper uploads the artifact and manifest to a unique private temporary
directory over SSH, then invokes the installed controller with sudo:

```sh
uv run python scripts/deploy_remote.py serveradmin@mini.example.ts.net \
  examples/hello/service.json artifacts/hello-v1.tar.gz --version v1 \
  --sha256 EXPECTED_SHA256
```

Use an SSH config alias if you need a nonstandard port or identity. Host keys are
checked by your normal SSH configuration. You may be prompted for the remote sudo
password. Do not configure unrestricted passwordless sudo merely to automate this.
Both the deployment operator and artifact source are trusted: the digest detects
wrong bytes; it does not establish the publisher's identity.

## Manifest contract

`examples/hello/service.json` is the complete minimal example. Fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently `1` |
| `name`, `user` | Must match the provisioned service policy |
| `command` | Argument array; first entry is an absolute executable or `{release}/...` |
| `environment` | Non-secret strings; runtime receives a minimal environment |
| `secret_env_file` | Optional exact path `/etc/home-infra/secrets/NAME.json` |
| `health.url` | HTTP URL on `127.0.0.1` with explicit port; redirects and proxies disabled |
| `health.timeout` | Maximum retry window, 1–300 seconds, plus an in-flight request timeout |
| `health.expect` | Optional substring expected in the response; use `{version}` to detect stale processes |

Supported placeholders in command, environment and expected response are
`{release}`, `{data}`, `{version}`, `{name}`. No shell evaluation occurs. Use an
explicit script in your artifact if the application needs a launch wrapper.

The runtime sets `HOMEINFRA_SERVICE`, `HOMEINFRA_RELEASE`, `HOMEINFRA_DATA`, `HOME`
and `TMPDIR`. The last two can be overridden by explicit environment configuration.
Secret JSON maps environment names to string values. Install it locally with mode
0600 and the service user as owner. Never pass values on a shell command line or
store them in inventory, a manifest, a plist or a GitHub workflow.

## CI and updating from Git

Every pull request and push to `main` runs checks on Linux and macOS. A successful
Linux job uploads the controller, example application archive and SHA256SUMS as a
workflow artifact. The release workflow publishes the same format when a `v*` tag
is pushed. Artifact names identify the controller commit, not your deployed app.

Updating Git alone does not update a running service. Download/build a reviewed
release and deploy it explicitly. This keeps a compromised or broken branch from
automatically executing on the home server. A later automation can call the same
deployment interface with a narrowly scoped deployment identity.
