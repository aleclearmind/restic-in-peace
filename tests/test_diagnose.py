from __future__ import annotations

import json

from restic_in_peace.diagnose import build_ncdu


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
