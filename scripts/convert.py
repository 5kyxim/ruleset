#!/usr/bin/env python3
"""Convert one immutable clash-rules checkout to sing-box source rule sets."""

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
from pathlib import Path

import yaml

DOMAIN_FILES = {
    "apple", "direct", "gfw", "google", "greatfire", "icloud", "private",
    "proxy", "reject", "tld-not-cn",
}
IP_FILES = {"cncidr", "lancidr", "telegramcidr"}
FILES = DOMAIN_FILES | IP_FILES | {"applications"}
SING_BOX_VERSION = "1.14.1"
FORMAT_VERSION = 2

# Shared namespaces do not establish that every tenant should connect directly.
# Match only these entries, never their more specific descendants.
DIRECT_EXCLUDED_SUFFIXES = frozenset({
    "in.th", "zone.id", "1kapp.com", "appchizi.com", "applinzi.com",
    "heiyu.space", "mycloudnas.com", "nett.to", "nyat.app", "sinaapp.com",
    "vicp.fun", "vipsinaapp.com", "zicp.fun", "3322.org", "vicp.net",
})


def convert(name, text):
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or set(data) != {"payload"}:
        raise ValueError(f"{name}: expected only a payload field")
    payload = data["payload"]
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{name}: empty or invalid payload")
    fields = {}
    for value in payload:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{name}: invalid entry {value!r}")
        if name in DOMAIN_FILES:
            key = "domain_suffix" if value.startswith("+.") else "domain"
            value = value[2:] if key == "domain_suffix" else value
            # This upstream uses ASCII domains, including private names with underscores.
            if not re.fullmatch(r"[-_A-Za-z0-9]+(?:\.[-_A-Za-z0-9]+)*", value):
                raise ValueError(f"{name}: unsupported domain {value!r}")
            value = value.lower()
            if name == "direct" and key == "domain_suffix" and (
                "." not in value or value in DIRECT_EXCLUDED_SUFFIXES
            ):
                continue
        elif name in IP_FILES:
            key = "ip_cidr"
            if "/" not in value:
                raise ValueError(f"{name}: expected CIDR {value!r}")
            value = str(ipaddress.ip_network(value, strict=True))
        elif name == "applications":
            key = "process_name"
            if not value.startswith("PROCESS-NAME,"):
                raise ValueError(f"{name}: unsupported rule {value!r}")
            value = value[len("PROCESS-NAME,"):]
            if not value or "," in value or any(ord(c) < 32 for c in value):
                raise ValueError(f"{name}: invalid process name")
        else:
            raise ValueError(f"unknown rule set: {name}")
        fields.setdefault(key, set()).add(value)
    # Separate clauses preserve OR semantics if a source gains another match category.
    rules = [{key: sorted(values)} for key, values in sorted(fields.items())]
    return {"version": FORMAT_VERSION, "rules": rules}, len(payload)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def build(source, output, sing_box):
    actual = {p.stem for p in source.glob("*.txt")}
    if actual != FILES:
        raise ValueError(f"source files changed: missing={FILES - actual}, extra={actual - FILES}")
    version = subprocess.check_output([sing_box, "version"], text=True).splitlines()[0]
    if version != f"sing-box version {SING_BOX_VERSION}":
        raise ValueError(f"unexpected compiler: {version}")
    source_sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True):
        raise ValueError("upstream checkout must be clean")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    manifest = {
        "upstream": "https://github.com/Loyalsoldier/clash-rules",
        "upstream_commit": source_sha,
        "sing_box_version": SING_BOX_VERSION,
        "format_version": FORMAT_VERSION,
        "converter_sha256": sha256(Path(__file__)),
        "files": {},
    }
    for name in sorted(FILES):
        path = source / f"{name}.txt"
        rule_set, count = convert(name, path.read_text())
        json_path, srs_path = output / f"{name}.json", output / f"{name}.srs"
        write_json(json_path, rule_set)
        subprocess.run([sing_box, "rule-set", "compile", "--output", str(srs_path), str(json_path)], check=True)
        if not srs_path.stat().st_size:
            raise ValueError(f"empty SRS: {name}")
        manifest["files"][name] = {
            "input_count": count,
            "output_count": sum(len(v) for r in rule_set["rules"] for v in r.values()),
            "source_sha256": sha256(path),
            "json_sha256": sha256(json_path),
            "srs_sha256": sha256(srs_path),
        }
    root = Path(__file__).resolve().parent.parent
    (output / "LICENSE").write_bytes((root / "LICENSE").read_bytes())
    (output / "README.md").write_text("")
    write_json(output / "manifest.json", manifest)
    print(f"Built {len(FILES)} rule sets from {source_sha}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sing-box", default="sing-box")
    args = parser.parse_args()
    build(args.source, args.output, args.sing_box)
