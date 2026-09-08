# First boot

This workflow starts after a normal macOS installation. It does not erase a disk
or bypass Setup Assistant. For organizational zero-touch enrollment, Apple's
[Automated Device Enrollment](https://support.apple.com/guide/deployment/dep73069dd57/web)
and an MDM are a separate provisioning layer.

## Prepare the target

1. Finish Setup Assistant on a dedicated Mac, connect Ethernet, apply macOS updates,
   and create an administrator account. Store its credentials in your password manager.
2. Decide on FileVault and retain the recovery key outside this machine. Leave the
   firewall enabled. Use a UPS if power interruptions matter.
3. Install Apple's command-line tools with `xcode-select --install`. Complete its UI.
4. Install Homebrew using the instructions at [brew.sh](https://brew.sh/), as the
   administrator, not root. Review the installer before running it.
5. Clone this repository and run `./bootstrap.sh`. The bootstrap installs uv and
   Python 3.13 through Homebrew, syncs locked development dependencies, installs the
   pinned Ansible collection and builds the runtime archive.

The target needs Homebrew and Python before Ansible can configure it. For a remote
target, install `python@3.13` through Homebrew there as well. The controller may be
another Mac or Linux machine using `make setup`.

## Configure inventory

Copy `inventory/example.yml` to `inventory/local.yml` if bootstrap has not already.
It is ignored by Git. For initial provisioning on the machine itself:

```yaml
all:
  children:
    mac_servers:
      hosts:
        mini:
          ansible_connection: local
          ansible_python_interpreter: /opt/homebrew/opt/python@3.13/bin/python3.13
          homeinfra_hostname: home-mini
          homeinfra_services:
            - name: hello
              user: hi_hello
```

On Intel Macs, use `/usr/local/opt/python@3.13/bin/python3.13`. For remote operation,
use `ansible_host` and `ansible_user` from the example instead of the local connection.
Enable macOS **Remote Login** for the administrator in System Settings and install
your SSH public key. Verify host keys; do not turn off SSH host-key checking.

All defaults live in `inventory/group_vars/all.yml`. Local host variables override
them. Service names and users must be unique. Removing a service from inventory
does not delete its data or stop an existing release; decommission it explicitly.

```sh
make plan
make apply
make plan
```

Ansible prompts for sudo. Check mode is a preview, not a complete simulation: an
unprovisioned host can fail checks involving files or users that would be created.
After applying, a second plan should show no pending changes for enabled features.

The power flags opt into configuring AC sleep prevention and restart after power
failure. Setting them false stops managing those settings; it does not restore
previous values. Network and backup enable flags also opt into management; see
[decommissioning](operations.md#decommissioning) before disabling them.

## Reboots and encrypted startup

System LaunchDaemons run without a desktop login **after the system volume is
unlocked**. Do not assume a Tailscale daemon can unlock its own FileVault-protected
Mac. Apple's [FileVault deployment documentation](https://support.apple.com/guide/deployment/dep82064ec40/web)
describes supported SSH unlock behavior on newer Apple silicon/macOS combinations;
validate it on your actual OS and network. Keep physical access or a separate
reachable recovery device until a cold-boot recovery test passes.

Automatic macOS updates, TCC/Full Disk Access prompts and disk encryption policy
remain deliberate administrator choices. This repository does not click through them.
