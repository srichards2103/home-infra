import json
import plistlib
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]


def environment():
    env = jinja2.Environment(  # noqa: S701 - Ansible YAML/plist templates, not HTML
        loader=jinja2.FileSystemLoader(ROOT),
        undefined=jinja2.StrictUndefined,
    )
    env.filters["to_json"] = json.dumps
    return env


def test_all_yaml_is_parseable():
    for root in ("roles", "inventory", ".github"):
        for path in (ROOT / root).rglob("*.yml"):
            yaml.safe_load(path.read_text())
    yaml.safe_load((ROOT / "site.yml").read_text())


def test_system_plists_render_on_both_architectures():
    env = environment()
    for prefix in ("/opt/homebrew", "/usr/local"):
        for filename in (
            "roles/networking/templates/tailscale.plist.j2",
            "roles/networking/templates/cloudflare.plist.j2",
            "roles/backups/templates/backup.plist.j2",
        ):
            rendered = env.get_template(filename).render(
                homeinfra_brew_prefix=prefix,
                homeinfra_backup_config="/etc/home-infra/backup.json",
                homeinfra_backup_hour=3,
                homeinfra_backup_minute=15,
            )
            plist = plistlib.loads(rendered.encode())
            assert plist["Label"].startswith("org.homeinfra.")
            assert isinstance(plist["ProgramArguments"], list)
            if "backup" in filename:
                assert "KeepAlive" not in plist
                assert not plist.get("RunAtLoad", False)
                assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
            else:
                assert plist["ProgramArguments"][0].startswith(prefix)
                assert plist["KeepAlive"] is True


def test_cloudflare_routes_end_in_deny():
    config = yaml.safe_load(
        environment()
        .get_template("roles/networking/templates/cloudflare.yml.j2")
        .render(
            homeinfra_cloudflare_tunnel_id="00000000-0000-0000-0000-000000000000",
            homeinfra_cloudflare_credentials_file="/etc/home-infra/secrets/cloudflare.json",
            homeinfra_cloudflare_routes=[
                {"hostname": "demo.example.com", "service": "http://127.0.0.1:8090"}
            ],
        )
    )
    assert config["ingress"][-1] == {"service": "http_status:404"}
    assert config["ingress"][0]["service"] == "http://127.0.0.1:8090"
