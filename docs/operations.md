# Operations and recovery

## Observe services

```sh
sudo /opt/home-infra/bin/homeinfra status hello
sudo launchctl print system/org.homeinfra.hello
sudo tail -n 100 /var/log/home-infra/hello/stderr.log
df -h /opt/home-infra
```

`status` returns a failing exit code for unhealthy services or a pending recovery.
launchd restarts exited processes, but does not restart a process merely because its
HTTP endpoint becomes unhealthy. External uptime/alerting is not bundled. Set it
up before relying on unattended services; also alert on backup age and free space.

Application logs can be rotated with `homeinfra rotate NAME`: when either stream
exceeds 10 MiB, the controller takes the deployment lock, stops the app, rotates
both streams (keeping five histories), restarts and checks health. This causes a
brief interruption. It is an explicit operation, not a hard disk quota or scheduled
job. Monitor log sizes and invoke it in a maintenance window. Network and backup
daemon logs require separate manual rotation while their jobs are stopped.

## Encrypted backups

Copy `examples/backup.example.json` to `/etc/home-infra/backup.json` on the target
and edit the repository and paths. Own it as root, mode 0600. Create a strong restic
password in `/etc/home-infra/secrets/restic-password`, root-owned mode 0600, and
store an independent copy in your password manager. An optional `environment_file`
can reference another private JSON file for storage credentials.

The SFTP example assumes root's SSH key and known_hosts are provisioned for the
backup destination; SSH host verification stays enabled. A root backup job does
not inherit your interactive shell or SSH agent. Configure explicit credentials.

```sh
sudo /opt/home-infra/bin/homeinfra backup init /etc/home-infra/backup.json
sudo /opt/home-infra/bin/homeinfra backup run /etc/home-infra/backup.json
sudo /opt/home-infra/bin/homeinfra backup check /etc/home-infra/backup.json
sudo /opt/home-infra/bin/homeinfra backup snapshots /etc/home-infra/backup.json
```

After the first successful backup and restore drill, set
`homeinfra_backup_enabled: true` and apply to schedule daily backups at 03:15 local
time. Override hour/minute in inventory if needed. Loading the schedule does not
immediately run a backup. Check `/var/log/home-infra/backup.log` and snapshot age;
the schedule itself does not send failure notifications.

The example backs up persistent app data and `/etc/home-infra`, including secrets,
inside the encrypted repository. Application backups may need a database-native
dump or quiescing first: copying a live database's files is not a consistency
guarantee. Tailscale account enrollment and OS configuration are not covered by
these paths. Re-enroll network agents on a replacement machine.

```sh
sudo /opt/home-infra/bin/homeinfra backup restore /etc/home-infra/backup.json \
  --snapshot latest --destination /private/tmp/home-infra-restore-drill
sudo /opt/home-infra/bin/homeinfra backup retention-plan /etc/home-infra/backup.json
```

Restore requires a nonexistent absolute destination and never overwrites live
data. Inspect restored files and verify application behavior in isolation. Restic
`check` checks repository structure by default; periodically run restic's
`check --read-data` directly for full content verification. Retention only previews
7 daily, 4 weekly and 12 monthly snapshots per tagged group; pruning is deliberately
an explicit operator action. Capacity planning must account for retained data.

## Rebuild a replacement Mac

1. Recover this repo, your ignored inventory, restic password and storage credentials
   from locations independent of the failed Mac. Keep a private copy of inventory
   and the deployed release/digest list in your recovery kit.
2. Follow first boot and provision service users/directories with network and backup
   flags initially disabled.
3. Restore the chosen snapshot into a separate directory. Review its contents.
4. With services stopped, copy application data into the provisioned data directories.
   Reapply ownership by account name; numeric UIDs can differ between Macs. Restore
   only the needed secrets with their correct owner and mode.
5. Rebuild or retrieve the recorded application releases, verify their digests and
   deploy. The default backup does not include release binaries: keep them in your
   release registry or add them to your backup configuration.
6. Re-enroll Tailscale, restore/reissue Cloudflare credentials and verify routes.
7. Perform local, private and public checks; enable backups and run a fresh snapshot.

Test this process before the old machine is gone. Keep FileVault recovery access
and a means to reach the machine if its primary tunnel fails.

## Updates

Review and update the repo and locked development dependencies, run `make check`,
then apply to update the installed controller. `state: present` does not upgrade
existing Homebrew packages. Upgrade Homebrew formulas and macOS deliberately in a
maintenance window and verify service health afterward. The current controller
must remain compatible with stored manifests; schema migrations need an explicit
plan. Releases and data are never automatically garbage-collected.

## Decommissioning

Enable flags mean “manage/install this feature”; changing one to false leaves an
already-installed daemon untouched. This avoids accidentally disconnecting remote
administration or deleting data through an inventory omission.

To retire a feature, first run `sudo launchctl bootout system/org.homeinfra.NAME`
using the relevant name (`hello`, `tailscaled`, `cloudflared`, or `backup`), remove
its managed plist from `/Library/LaunchDaemons`, and remove/disable its inventory
entry. Stop jobs before rotating their logs. Revoke external credentials and DNS
routes if retiring a tunnel. Retain verified backups before manually deleting
service data, releases or accounts. Never stop your only remote access path until
you have another way in.
