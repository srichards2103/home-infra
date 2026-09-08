# Security

Do not post credentials or exploit details involving a live installation in a
public issue. Use GitHub's private vulnerability reporting for this repository
when enabled. If that option is unavailable, open a minimal issue requesting a
private reporting channel without disclosing sensitive details.

Supported development is currently on `main`; there is no long-term support
promise. Review changes before applying them as an administrator.

See [architecture](docs/architecture.md) for trusted components and limitations.
`.gitignore` is a convenience, not a secret scanner. Review staged content before
every commit. If a credential reaches Git, revoke it; deleting the file in a later
commit does not remove it from history.
