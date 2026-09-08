# Architecture and trust boundaries

## Layout

| Path | Owner / purpose |
| --- | --- |
| `/opt/home-infra/bin` | Root; controller zipapp and launcher |
| `/opt/home-infra/apps/NAME/releases/VERSION` | Root; immutable application content and manifest |
| `/opt/home-infra/apps/NAME/current` | Root; atomic symlink to active release |
| `/opt/home-infra/apps/NAME/state.json` | Root; current and previous versions |
| `/opt/home-infra/apps/NAME/transaction.json` | Root; interrupted deployment recovery journal |
| `/opt/home-infra/apps/NAME/policy.json` | Root; provisioned execution identity |
| `/opt/home-infra/data/NAME` | Service user; mutable state and temporary files |
| `/etc/home-infra/secrets/NAME.json` | Service user, 0600; application environment secrets |
| `/Library/LaunchDaemons/org.homeinfra.NAME.plist` | Root; startup definition with no secret values |
| `/var/log/home-infra/NAME` | Service user; stdout and stderr |

## Deployment transaction

1. Validate the manifest and provisioned identity; acquire a per-service file lock.
2. Copy the supplied archive to root-owned staging, then verify that copy's digest.
3. Extract only regular files/directories, rejecting traversal, links, special files,
   duplicates and archives over the entry or expanded-byte limit.
4. Persist the release manifest and digest; atomically rename staging into releases.
5. Persist a journal containing the prior release and state.
6. Stop the old job; atomically change the current symlink; install the plist and start.
7. Require HTTP 200 and, when configured, a release-specific response substring.
8. Commit state and remove the journal. On failure, restore and health-check the prior
   release. If recovery fails, retain the journal and block further deployments.

This gives recoverable application activation, not filesystem/database transactions
or zero downtime. After abrupt power loss, the host may boot the prior or target
plist before an operator runs recovery. `status` reports pending recovery even when
the process is healthy. File contents and atomic writes are fsynced; full
power-failure behavior still needs hardware testing.

## Trust model

The administrator, their Homebrew installation, provisioner, controller source,
application manifest and artifact publisher are trusted. Application processes run
unprivileged. They cannot replace root-owned releases or controller files, but can
read their own secrets and alter their own data/logs. This is Unix account isolation,
not a sandbox for hostile workloads.

The root launchd job executes a Homebrew Python interpreter. Its administrator-owned
installation is therefore inside the root trust boundary. Do not give untrusted users
write access to Homebrew or use this design for shared multi-tenant hosting.

The digest is an integrity check supplied by a trusted operator, not a signature.
HTTP health is not proof of complete application correctness. A release-specific
expectation reduces false positives from stale processes but is still app-reported.
Archives over 2 GiB expanded or 100,000 entries are rejected; operators should also
check compressed input size and free space before deployment.

Network exposure and authentication are separate. Tailscale policies restrict
private connectivity; public apps must provide suitable authentication or an
appropriate access gateway. Backup encryption protects repository contents but
does not prevent an administrator or stolen live credentials from deleting them.
Use independent storage access controls and retention where needed.

## Deliberate scope

The first implementation supports native processes with loopback HTTP health checks.
It does not manage Linux VMs/containers, distributed scheduling, database migrations,
OAuth, fleet MDM enrollment, external alerting or automatic production deployments.
These can be added independently without coupling personal account details to the
public provisioning code.
