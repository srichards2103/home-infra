# Networking

Apps should bind to `127.0.0.1`. Open a route only to the audience that needs it.
Administrative SSH is separate from application access. No router port-forwarding
rules are needed for either outbound tunnel.

## Private: Tailscale

This repository uses the CLI `tailscaled` variant, managed as a system daemon.
Do not run it alongside either GUI variant. Follow Tailscale's
[macOS variant guidance](https://tailscale.com/kb/1065/macos-variants) before migrating
an existing installation. The playbook refuses a detected `/Applications/Tailscale.app`.
It cannot detect every custom installation; inspect your existing services first.

Set `homeinfra_tailscale_enabled: true` in ignored local inventory and apply. Then
enroll interactively on the Mac:

```sh
sudo /opt/homebrew/bin/tailscale up
sudo /opt/homebrew/bin/tailscale status
sudo /opt/homebrew/bin/tailscale serve --bg http://127.0.0.1:8090
sudo /opt/homebrew/bin/tailscale serve status
```

Use `/usr/local/bin` on Intel. Complete any requested HTTPS/DNS enablement in your
tailnet. Use the resulting HTTPS URL from another tailnet device.
[Tailscale Serve](https://tailscale.com/kb/1312/serve) is private to the tailnet;
Funnel is a separate public feature and is not configured here.

Merge the example `examples/tailnet-policy.hujson` into your actual access policy
after replacing the example operator identity and assigning the `tag:home-server`
tag. It illustrates access to TCP 22 and 443. Do not overwrite an existing policy
blindly. Other permissive grants can still allow traffic; test a denied user/device
as well as your allowed one. Native macOS SSH over Tailscale is the administration
path here; this project does not configure Tailscale SSH.

## Public: Cloudflare Tunnel

You need a domain managed by Cloudflare and a locally managed named tunnel. Follow
Cloudflare's [local tunnel management guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/).
Authenticate and create the tunnel interactively. Keep its account certificate and
tunnel credentials out of Git. Install the tunnel's JSON credentials at
`/etc/home-infra/secrets/cloudflare.json`, owned by root with mode 0600.

In ignored inventory, configure your real UUID and hostname:

```yaml
homeinfra_cloudflare_enabled: true
homeinfra_cloudflare_tunnel_id: REPLACE-WITH-YOUR-TUNNEL-UUID
homeinfra_cloudflare_routes:
  - hostname: demo.example.com
    service: http://127.0.0.1:8090
```

Apply to install and start the daemon. Then create the DNS route using your
authenticated Cloudflare account (`cloudflared tunnel route dns TUNNEL HOSTNAME`).
Only publish this route once the application's intended access controls are ready.
The generated ingress includes a final HTTP 404 rule for unmatched hostnames.

For a private dashboard on a public hostname, configure Cloudflare Access before
publishing it. For machine clients, choose an authentication method they support.
A tunnel supplies transport and reachability; it does not make an unauthenticated
API safe to expose. This repository does not provision Cloudflare Access policies,
OAuth servers, or DNS automatically.

## Verify the boundary

1. Local health works while the app listens only on loopback.
2. An allowed tailnet client can reach the private HTTPS URL.
3. A device outside the tailnet cannot reach that private route.
4. A public hostname exposes only the intended app, with its intended authentication.
5. Restart the Mac and repeat the checks after unlocking it.

Daemon logs are `/var/log/home-infra/tailscaled.log` and `cloudflared.log`. Monitor
their size. Network daemon log rotation is manual in this version to avoid
periodically dropping the very connection used to administer the host.
