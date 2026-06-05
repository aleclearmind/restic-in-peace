from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import IO, Any

from . import profile as profile_mod
from . import version


def collect_items(
    config: dict[str, Any],
    name: str,
    progress_sinks: list[IO[str]] | None = None,
) -> list[tuple[str, int, int]]:
    """Stream `restic backup --dry-run --verbose=2 --json` for profile `name`
    and return [(path, asize, dsize), ...] for every file restic would add.

    asize is the file's apparent size (st_size); dsize is its actual disk
    usage (st_blocks * 512). ncdu's default view is the disk-usage one, so
    we have to provide dsize or it shows 0.0 B for everything.

    If `progress_sinks` is given, a one-line progress update is written to
    each sink at most once per second (running file/byte counters during the
    scan, then a final "scan complete" line).
    """
    settings, env = profile_mod.resolve(config, name, "backup")
    flags, positionals = profile_mod.to_argv(settings, "backup", drop_keys=profile_mod.RIP_ONLY)
    # --no-lock so a stale lock from a previous run doesn't block the diagnostic.
    cmd = ["restic", "backup", "--dry-run", "--verbose=2", "--json", "--no-lock", *flags, *positionals]

    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.items()})

    process = subprocess.Popen(
        cmd, env=proc_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    assert process.stdout is not None

    interesting_actions = {"new", "modified", "changed"}
    items: list[tuple[str, int, int]] = []
    last_progress = 0.0

    def emit(text: str) -> None:
        if not progress_sinks:
            return
        for sink in progress_sinks:
            sink.write(text)
            sink.flush()

    for line in process.stdout:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        action = msg.get("action")
        if action in interesting_actions:
            item = msg.get("item")
            if item and not item.endswith("/"):
                try:
                    st = os.stat(item)
                    items.append((item, st.st_size, st.st_blocks * 512))
                except OSError:
                    items.append((item, 0, 0))

        if action == "scan_finished":
            emit(
                f"  dry-run scan complete: {msg.get('total_files', 0)} files, "
                f"{msg.get('data_size', 0)} bytes\n"
            )
            last_progress = time.monotonic()
        elif msg.get("message_type") == "status":
            now = time.monotonic()
            if now - last_progress >= 1.0:
                last_progress = now
                tf, fd = msg.get("total_files", 0), msg.get("files_done", 0)
                tb, bd = msg.get("total_bytes", 0), msg.get("bytes_done", 0)
                phase = "scanning" if fd == 0 else "processing"
                emit(f"  dry-run {phase}: {fd}/{tf} files, {bd}/{tb} bytes\n")

    process.wait()
    return items


def build_ncdu(items: list[tuple[str, int, int]]) -> list[Any]:
    """Build an ncdu v1.2 JSON document from a flat list of
    (file_path, asize, dsize) tuples.

    ncdu format reference: https://dev.yorhel.nl/ncdu/jsonfmt
    - A file entry is `{"name": ..., "asize": <bytes>, "dsize": <bytes>}`.
    - A directory entry is `[{"name": ..., }, child, child, [subdir-head, ...]]`.
    - ncdu computes a directory's displayed total by summing its descendants,
      so we deliberately leave `asize`/`dsize` off directory heads.
    """
    root: dict[str, Any] = {}

    for path, asize, dsize in items:
        parts = PurePosixPath(path).parts
        if not parts:
            continue
        current = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            entry = current.setdefault(part, {"asize": 0, "dsize": 0, "children": {}})
            if is_last:
                # Don't overwrite a directory we already saw (defensive).
                if not entry["children"]:
                    entry["asize"] = asize
                    entry["dsize"] = dsize
                    entry["children"] = None
            else:
                if entry["children"] is None:
                    entry["children"] = {}
                current = entry["children"]

    def to_ncdu(name: str, entry: dict[str, Any]) -> Any:
        if entry["children"] is None:
            return {"name": name, "asize": entry["asize"], "dsize": entry["dsize"]}
        return [{"name": name}] + [to_ncdu(n, e) for n, e in sorted(entry["children"].items())]

    if len(root) == 1:
        name, entry = next(iter(root.items()))
        tree: Any = to_ncdu(name, entry)
    else:
        tree = [{"name": "rip-diagnostic"}] + [to_ncdu(n, e) for n, e in sorted(root.items())]

    return [
        1,
        2,
        {"progname": "restic-in-peace", "progver": version, "timestamp": int(time.time())},
        tree,
    ]


def _join(path: str, name: str) -> str:
    if name == "/":
        return "/"
    if not path:
        return name
    return str(PurePosixPath(path) / name)


def significant_items(ncdu_doc: list[Any], threshold_fraction: float = 0.05) -> list[tuple[str, int]]:
    """Return the most-specific (path, size) pairs whose apparent size is at
    least `threshold_fraction` of the total.

    Post-order DFS: a node is reported iff its asize >= threshold AND none of
    its descendants is reported. So a big leaf file gets reported (not its
    parent); a directory full of many small files gets reported once it
    aggregates past the threshold — but only when no single child is itself
    over the threshold.

    Returned list is sorted by descending size.
    """
    tree = ncdu_doc[3]

    def total_size(node: Any) -> int:
        if isinstance(node, dict):
            return int(node.get("asize", 0))
        return sum(total_size(c) for c in node[1:])

    grand_total = total_size(tree)
    threshold = grand_total * threshold_fraction

    def walk(node: Any, path: str) -> tuple[int, list[tuple[str, int]]]:
        if isinstance(node, dict):
            name = node["name"]
            size = int(node.get("asize", 0))
            full = _join(path, name)
            return size, ([(full, size)] if size >= threshold else [])
        head = node[0]
        full = _join(path, head["name"])
        node_total = 0
        children_sig: list[tuple[str, int]] = []
        for child in node[1:]:
            c_total, c_sig = walk(child, full)
            node_total += c_total
            children_sig.extend(c_sig)
        if children_sig:
            return node_total, children_sig
        if node_total >= threshold:
            return node_total, [(full, node_total)]
        return node_total, []

    _, sig = walk(tree, "")
    return sorted(sig, key=lambda x: -x[1])


def write_diagnostic(config: dict[str, Any], name: str, output_path: Path) -> None:
    """Collect new items for `name` and write the ncdu JSON to output_path."""
    items = collect_items(config, name)
    document = build_ncdu(items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document) + "\n")
