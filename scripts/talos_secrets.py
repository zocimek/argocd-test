#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import hvac
except ImportError:
    print("hvac is required. Install with: pip install hvac", file=sys.stderr)
    sys.exit(1)


def flatten_dict(d, prefix=""):
    """
    Recursively flatten a nested dict into {JOINED_KEYS: value}
    using "_" as separator and UPPERCASE keys.
    Example:
        {"cluster": {"id": "xxx"}}
        -> {"CLUSTER_ID": "xxx"}
    """
    flat = {}
    for k, v in d.items():
        new_key = f"{prefix}_{k}".upper() if prefix else k.upper()
        if isinstance(v, dict):
            flat.update(flatten_dict(v, new_key))
        elif isinstance(v, list):
            flat[new_key] = ",".join(map(str, v))
        else:
            flat[new_key] = "" if v is None else str(v)
    return flat


def ensure_kv2(client: hvac.Client, mount: str):
    """Best-effort check that mount is KV v2."""
    try:
        cfg = client.sys.read_mount_configuration(path=mount)
        t = cfg.get("data", {}).get("type")
        if t != "kv":
            print(f"[warn] Mount '{mount}' type is '{t}', not 'kv'.", file=sys.stderr)
        else:
            opts = cfg.get("data", {}).get("options", {})
            if opts.get("version") != "2":
                print(f"[warn] Mount '{mount}' is kv version={opts.get('version')}, expected 2.", file=sys.stderr)
    except Exception as e:
        print(f"[info] Could not verify mount '{mount}' is kv v2 ({e}). Continuing…", file=sys.stderr)


def authenticate(client, args):
    token = args.token or os.getenv("VAULT_TOKEN")
    if token:
        client.token = token
        return
    if args.approle_role_id and args.approle_secret_id:
        client.auth.approle.login(role_id=args.approle_role_id, secret_id=args.approle_secret_id)
        return
    print("No auth provided. Use --token or AppRole, or set VAULT_TOKEN.", file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="Flatten YAML into a single Vault KV v2 secret with UPPERCASE keys.")
    ap.add_argument("yaml_file", help="Path to input YAML file.")
    ap.add_argument("--address", default=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"), help="Vault address.")
    ap.add_argument("--namespace", default=os.getenv("VAULT_NAMESPACE"), help="Vault namespace.")
    ap.add_argument("--token", help="Vault token (or $VAULT_TOKEN).")
    ap.add_argument("--approle-role-id", help="AppRole role_id.")
    ap.add_argument("--approle-secret-id", help="AppRole secret_id.")
    ap.add_argument("--mount", default="secrets", help="KV v2 mount name (default: secrets).")
    ap.add_argument("--path", default="kubernetes/talos", help="KV path under mount.")
    ap.add_argument("--tls-skip-verify", action="store_true", help="Disable TLS verification.")
    ap.add_argument("--ca-cert", help="Custom CA cert.")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = ap.parse_args()

    ypath = Path(args.yaml_file)
    if not ypath.exists():
        print(f"YAML file not found: {ypath}", file=sys.stderr)
        sys.exit(1)

    try:
        data = yaml.safe_load(ypath.read_text())
    except Exception as e:
        print(f"Failed to parse YAML: {e}", file=sys.stderr)
        sys.exit(1)

    flat = flatten_dict(data)

    client = hvac.Client(
        url=args.address,
        namespace=args.namespace,
        verify=False if args.tls_skip_verify else (args.ca_cert or True),
    )
    authenticate(client, args)
    if not client.is_authenticated():
        print("Authentication failed.", file=sys.stderr)
        sys.exit(3)

    ensure_kv2(client, args.mount)

    if args.dry_run:
        print(f"[dry-run] Would write to {args.mount}/{args.path}:")
        for k, v in flat.items():
            print(f"  {k}: {'***' if v else ''}")
        return

    try:
        client.secrets.kv.v2.create_or_update_secret(
            path=args.path,
            secret=flat,
            mount_point=args.mount,
        )
        print(f"[ok] wrote {len(flat)} UPPERCASE keys to {args.mount}/{args.path}")
    except Exception as e:
        print(f"[err] Failed to write secret: {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
