from __future__ import annotations

import json

from restic_in_peace.diagnose import build_ncdu


def test_build_ncdu_groups_by_directory() -> None:
    doc = build_ncdu([
        ("/home/a/big.bin", 1000),
        ("/home/a/small.txt", 100),
        ("/home/b/other.bin", 50),
    ])
    # ncdu v1.2 envelope: [major, minor, info, tree]
    assert doc[0] == 1 and doc[1] == 2
    assert doc[2]["progname"] == "restic-in-peace"

    tree = doc[3]
    # Root is `/`, a directory: head dict (no asize) + child arrays/dicts.
    assert isinstance(tree, list)
    assert tree[0] == {"name": "/"}

    home = tree[1]
    assert isinstance(home, list)
    assert home[0] == {"name": "home"}

    a, b = home[1], home[2]
    assert a[0] == {"name": "a"}
    assert b[0] == {"name": "b"}

    a_files = {entry["name"]: entry["asize"] for entry in a[1:]}
    assert a_files == {"big.bin": 1000, "small.txt": 100}
    b_files = {entry["name"]: entry["asize"] for entry in b[1:]}
    assert b_files == {"other.bin": 50}


def test_build_ncdu_empty_input() -> None:
    doc = build_ncdu([])
    assert doc[0] == 1 and doc[1] == 2
    assert doc[3] == [{"name": "rip-diagnostic"}]


def test_directory_entry_appearing_after_its_children_does_not_clobber() -> None:
    # restic's dry-run emits an entry for every ancestor directory in
    # addition to the files. collect_items already filters out trailing
    # slashes, but build_ncdu's own defense in depth: if a path is seen
    # both as a leaf and as an ancestor, the directory wins (we don't
    # discard the children).
    doc = build_ncdu([
        ("/home/file.txt", 100),
        ("/home", 4096),  # would-be parent re-asserted as a leaf
    ])
    tree = doc[3]
    assert tree[0] == {"name": "/"}
    home = tree[1]
    assert isinstance(home, list)
    assert home[0] == {"name": "home"}
    files = {e["name"]: e["asize"] for e in home[1:]}
    assert files == {"file.txt": 100}


def test_build_ncdu_emits_valid_json() -> None:
    doc = build_ncdu([("/a/b.txt", 10)])
    encoded = json.dumps(doc)
    assert json.loads(encoded) == doc
