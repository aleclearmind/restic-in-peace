import subprocess


def test_collect_partitions_files(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, write_config, test_env
):
    backed = fake_home / "in-backup"
    backed.mkdir()
    (backed / "wanted.txt").write_text("a\n")
    (backed / "noisy.tmp").write_text("b\n")
    skipped_root = fake_home / "outside-backup"
    skipped_root.mkdir()
    (skipped_root / "stray.txt").write_text("c\n")
    cache = backed / "huge-cache"
    cache.mkdir()
    (cache / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    (cache / "blob.bin").write_text("d\n")

    config_path = write_config({
        "profiles": {
            "common": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
                "backup": {
                    "exclude": ["*.tmp"],
                    "exclude-if-present": ["CACHEDIR.TAG"],
                },
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(backed)]},
            },
        },
    })

    out = tmp_path / "out"
    env = {**test_env, "RIP_COLLECT_ROOTS": str(fake_home)}

    result = subprocess.run(
        [rip_bin, "--config", str(config_path), "collect-non-backuped-files", str(out)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    all_files = set((out / "all-files").read_text().splitlines()) - {""}
    backed_up = set((out / "all-backuped-files").read_text().splitlines()) - {""}
    non_backed_up = set((out / "non-backuped-files").read_text().splitlines()) - {""}
    implicit = set((out / "implicitly-non-backuped-files").read_text().splitlines()) - {""}

    assert str(backed / "wanted.txt") in all_files
    assert str(backed / "wanted.txt") in backed_up

    # exclude pattern: *.tmp is dropped by restic AND by our implicit filter
    assert str(backed / "noisy.tmp") in non_backed_up
    assert str(backed / "noisy.tmp") not in implicit

    # exclude-if-present: the cache dir is skipped by restic; the implicit
    # filter recognizes the marker and treats files there as deliberate.
    assert str(cache / "blob.bin") in non_backed_up
    assert str(cache / "blob.bin") not in implicit

    # A file outside any source is genuinely not backed up — should show up
    # in the implicit set.
    assert str(skipped_root / "stray.txt") in implicit
