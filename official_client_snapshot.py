#!/usr/bin/env python3
"""Create and verify a pinned local snapshot of the public GTA Heist client.

This tool downloads only public browser assets. It does not call gameplay or
score APIs. Every downloaded byte is checked against the repository's pinned
SHA-256 values before it is written. If a snapshot already exists, upstream
bytes must also match that snapshot manifest; changes fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

PINNED_SITE = "https://www.gtaheist.fun/game"
ASSETS = (
    ("game.html", "https://www.gtaheist.fun/game/", "a328e728da7a705a600d648839b8288f214cd6b7fbc5f6e7ea792e943031b3cd"),
    ("campaign.js", "https://www.gtaheist.fun/game/campaign.js", "ff7eb566745a5a2a1316f65637c8e1996f0089aebd3c43b86aee03f7344581e0"),
    ("share-card.mjs", "https://www.gtaheist.fun/game/share-card.mjs", "411c6bbf34722c6fa8174d0177bb38aeae37a1ba22e9ee973a4876b504cb4453"),
)
MANIFEST_NAME = "manifest.json"


def fetch_url(url: str, timeout: int = 30) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def client_hash(asset_records: list[dict]) -> str:
    canonical = json.dumps(
        [(item["name"], item["sha256"], item["bytes"]) for item in asset_records],
        separators=(",", ":"),
    ).encode("utf-8")
    return digest(canonical)


def _manifest_path(out_dir: Path) -> Path:
    return out_dir / MANIFEST_NAME


def _read_manifest(out_dir: Path) -> dict:
    path = _manifest_path(out_dir)
    if not path.is_file():
        raise RuntimeError(f"Missing snapshot manifest: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Invalid snapshot manifest: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported snapshot manifest: {path}")
    return value


def _verify_manifest_shape(manifest: dict) -> None:
    if manifest.get("site") != PINNED_SITE:
        raise RuntimeError("Snapshot site does not match the pinned official site")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or [(x.get("name"), x.get("url")) for x in assets] != [(n, u) for n, u, _ in ASSETS]:
        raise RuntimeError("Snapshot asset list does not match the pinned public client")


def verify_local_snapshot(out_dir: str | Path) -> dict:
    """Verify local files against manifest and immutable repository pins."""
    root = Path(out_dir)
    manifest = _read_manifest(root)
    _verify_manifest_shape(manifest)
    records = []
    for (name, url, pinned), recorded in zip(ASSETS, manifest["assets"], strict=True):
        path = root / name
        if not path.is_file():
            raise RuntimeError(f"Missing snapshot asset: {path}")
        content = path.read_bytes()
        actual = digest(content)
        if actual != pinned:
            raise RuntimeError(f"Snapshot asset differs from immutable pin: {name}")
        if actual != recorded.get("sha256") or len(content) != recorded.get("bytes"):
            raise RuntimeError(f"Snapshot asset differs from manifest: {name}")
        records.append({"name": name, "url": url, "bytes": len(content), "sha256": actual})
    calculated = client_hash(records)
    if calculated != manifest.get("client_hash") or manifest.get("client_version") != f"content-sha256:{calculated}":
        raise RuntimeError("Snapshot client hash does not match its manifest")
    return {"path": str(root), "client_hash": calculated, "assets": records}


def download_snapshot(
    out_dir: str | Path,
    fetcher: Callable[[str], bytes] = fetch_url,
) -> dict:
    """Download, verify, and atomically write the pinned public client snapshot."""
    root = Path(out_dir)
    existing = _read_manifest(root) if root.exists() and _manifest_path(root).exists() else None
    contents: dict[str, bytes] = {}
    records = []
    for name, url, pinned in ASSETS:
        content = fetcher(url)
        actual = digest(content)
        if actual != pinned:
            raise RuntimeError(f"Official client asset changed; refusing snapshot: {name}")
        contents[name] = content
        records.append({"name": name, "url": url, "bytes": len(content), "sha256": actual})
    if existing is not None:
        _verify_manifest_shape(existing)
        old = {item["name"]: item["sha256"] for item in existing["assets"]}
        for item in records:
            if old.get(item["name"]) != item["sha256"]:
                raise RuntimeError(f"Upstream asset differs from existing snapshot; refusing overwrite: {item['name']}")
    combined = client_hash(records)
    manifest = {
        "schema_version": 1,
        "site": PINNED_SITE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_hash": combined,
        "client_version": f"content-sha256:{combined}",
        "assets": records,
    }
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}.", dir=str(root.parent)) as tmp:
        staging = Path(tmp) / root.name
        staging.mkdir()
        for name, content in contents.items():
            (staging / name).write_bytes(content)
        (staging / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if root.exists():
            backup = root.with_name(root.name + ".old")
            if backup.exists():
                shutil.rmtree(backup)
            root.rename(backup)
            try:
                staging.rename(root)
            except Exception:
                backup.rename(root)
                raise
            shutil.rmtree(backup)
        else:
            staging.rename(root)
    return verify_local_snapshot(root)


def verify_live_against_snapshot(out_dir: str | Path, fetcher: Callable[[str], bytes] = fetch_url) -> dict:
    """Verify local snapshot and ensure current public bytes have not changed."""
    local = verify_local_snapshot(out_dir)
    for name, url, pinned in ASSETS:
        content = fetcher(url)
        if digest(content) != pinned:
            raise RuntimeError(f"Live public asset changed; refusing use: {name}")
        if digest(content) != next(x["sha256"] for x in local["assets"] if x["name"] == name):
            raise RuntimeError(f"Live public asset differs from local snapshot: {name}")
    return local


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("download", "verify", "verify-live"):
        p = sub.add_parser(command)
        p.add_argument("--out-dir", default="official-client")
    args = parser.parse_args()
    if args.command == "download":
        result = download_snapshot(args.out_dir)
    elif args.command == "verify":
        result = verify_local_snapshot(args.out_dir)
    else:
        result = verify_live_against_snapshot(args.out_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
