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
    # Root is `/`, which contains a single `home` subdir.
    assert isinstance(tree, list)
    assert tree[0]["name"] == "/"
    assert tree[0]["asize"] == 1150

    home = tree[1]
    assert isinstance(home, list)
    assert home[0]["name"] == "home"
    assert home[0]["asize"] == 1150

    names = {child[0]["name"]: child[0]["asize"] for child in home[1:]}
    assert names == {"a": 1100, "b": 50}


def test_build_ncdu_empty_input() -> None:
    doc = build_ncdu([])
    assert doc[0] == 1 and doc[1] == 2
    assert doc[3] == [{"name": "rip-diagnostic", "asize": 0}]


def test_build_ncdu_emits_valid_json() -> None:
    doc = build_ncdu([("/a/b.txt", 10)])
    # Round-trip via json to make sure the structure is serializable.
    encoded = json.dumps(doc)
    assert json.loads(encoded) == doc
