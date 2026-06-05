from __future__ import annotations

import json

from restic_in_peace.diagnose import build_ncdu, significant_items


def test_build_ncdu_groups_by_directory() -> None:
    doc = build_ncdu([
        ("/home/a/big.bin", 1000, 4096),
        ("/home/a/small.txt", 100, 4096),
        ("/home/b/other.bin", 50, 4096),
    ])
    # ncdu v1.2 envelope: [major, minor, info, tree]
    assert doc[0] == 1 and doc[1] == 2
    assert doc[2]["progname"] == "restic-in-peace"

    tree = doc[3]
    # Root is `/`, a directory: head dict (no asize/dsize) + child arrays/dicts.
    assert isinstance(tree, list)
    assert tree[0] == {"name": "/"}

    home = tree[1]
    assert isinstance(home, list)
    assert home[0] == {"name": "home"}

    a, b = home[1], home[2]
    assert a[0] == {"name": "a"}
    assert b[0] == {"name": "b"}

    a_files = {entry["name"]: (entry["asize"], entry["dsize"]) for entry in a[1:]}
    assert a_files == {"big.bin": (1000, 4096), "small.txt": (100, 4096)}
    b_files = {entry["name"]: (entry["asize"], entry["dsize"]) for entry in b[1:]}
    assert b_files == {"other.bin": (50, 4096)}


def test_build_ncdu_empty_input() -> None:
    doc = build_ncdu([])
    assert doc[0] == 1 and doc[1] == 2
    assert doc[3] == [{"name": "rip-diagnostic"}]


def test_directory_entry_appearing_after_its_children_does_not_clobber() -> None:
    doc = build_ncdu([
        ("/home/file.txt", 100, 4096),
        ("/home", 4096, 4096),
    ])
    tree = doc[3]
    assert tree[0] == {"name": "/"}
    home = tree[1]
    assert isinstance(home, list)
    assert home[0] == {"name": "home"}
    files = {e["name"]: (e["asize"], e["dsize"]) for e in home[1:]}
    assert files == {"file.txt": (100, 4096)}


def test_build_ncdu_emits_valid_json() -> None:
    doc = build_ncdu([("/a/b.txt", 10, 4096)])
    encoded = json.dumps(doc)
    assert json.loads(encoded) == doc


def test_significant_items_reports_big_file_not_its_parent() -> None:
    # 80 bytes total, big.bin is 60% — should be reported, /home should not.
    doc = build_ncdu([
        ("/home/big.bin", 60, 60),
        ("/home/a.txt", 10, 10),
        ("/home/b.txt", 10, 10),
    ])
    sig = significant_items(doc, threshold_fraction=0.1)
    paths = [p for p, _ in sig]
    assert "/home/big.bin" in paths
    assert "/home" not in paths
    assert "/" not in paths


def test_significant_items_reports_deepest_aggregating_dir() -> None:
    # 100 bytes total; no single file >= 10. Inside `bigdir/`, the four 25-byte
    # files each are 25% — each is itself reportable as a single file.
    doc = build_ncdu([
        ("/home/bigdir/a", 25, 25),
        ("/home/bigdir/b", 25, 25),
        ("/home/bigdir/c", 25, 25),
        ("/home/bigdir/d", 25, 25),
    ])
    sig = significant_items(doc, threshold_fraction=0.1)
    paths = [p for p, _ in sig]
    # Each 25% file shows up; bigdir/ does NOT because its children did.
    assert set(paths) == {"/home/bigdir/a", "/home/bigdir/b", "/home/bigdir/c", "/home/bigdir/d"}


def test_significant_items_aggregates_many_small_files() -> None:
    # 100 bytes total; each cache file is 1% (below threshold), but the
    # /var/cache dir aggregates to 30% — report the directory, not the files.
    items = [(f"/var/cache/f{i}", 1, 1) for i in range(30)]
    items.append(("/home/big.bin", 70, 70))
    doc = build_ncdu(items)
    sig = significant_items(doc, threshold_fraction=0.1)
    paths = {p for p, _ in sig}
    assert paths == {"/home/big.bin", "/var/cache"}


def test_significant_items_sorted_by_size() -> None:
    doc = build_ncdu([
        ("/big.bin", 50, 50),
        ("/medium.bin", 30, 30),
        ("/small.bin", 20, 20),
    ])
    sig = significant_items(doc, threshold_fraction=0.1)
    sizes = [s for _, s in sig]
    assert sizes == sorted(sizes, reverse=True)


def test_significant_items_no_significant_nodes() -> None:
    # All files exactly 5% — none reach 10%; the / parent does (100%), but the
    # children make it report at child level — wait, no child crosses threshold
    # so / itself is the smallest "containing" node above threshold, which IS
    # reported (the whole tree).
    doc = build_ncdu([(f"/x{i}", 5, 5) for i in range(20)])
    sig = significant_items(doc, threshold_fraction=0.1)
    # No individual child >= 10%, so the deepest aggregating dir (the root) wins.
    assert [p for p, _ in sig] == ["/"]
