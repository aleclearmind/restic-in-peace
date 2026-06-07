import subprocess


def test_emits_bash_for_pending_actions(fake_home, current_user, write_config, rip_bin, test_env):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".vimrc").write_text("set nu\n")

    config = write_config({
        "fix-homes": {
            current_user: {
                "ignore": [".dotfiles"],
                ".dotfiles": [".vimrc"],
            }
        }
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "fix-home"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, result.stderr
    assert 'mv ~/".vimrc" ~/".dotfiles/.vimrc"' in result.stdout
    assert 'ln -s ".dotfiles/.vimrc" ~/".vimrc"' in result.stdout


def test_strict_fails_when_action_needed(fake_home, current_user, write_config, rip_bin, test_env):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".vimrc").write_text("set nu\n")

    config = write_config({
        "fix-homes": {
            current_user: {
                "ignore": [".dotfiles"],
                ".dotfiles": [".vimrc"],
            }
        }
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "fix-home", "--strict"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert "Moving .vimrc" in result.stderr
    # strict mode emits no bash
    assert result.stdout == ""


def test_strict_succeeds_when_state_is_clean(fake_home, current_user, write_config, rip_bin, test_env):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".dotfiles" / ".vimrc").write_text("set nu\n")
    (fake_home / ".vimrc").symlink_to(".dotfiles/.vimrc")

    config = write_config({
        "fix-homes": {
            current_user: {
                "ignore": [".dotfiles"],
                ".dotfiles": [".vimrc"],
            }
        }
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "fix-home", "--strict"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, result.stderr


def test_no_user_section_fails(fake_home, write_config, rip_bin, test_env):
    config = write_config({"fix-homes": {"some-other-user": {".dotfiles": [".vimrc"]}}})
    env = {**test_env, "USER": "nonexistent-user-xyz"}

    result = subprocess.run(
        [rip_bin, "--config", str(config), "fix-home"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    assert "No fix-homes/nonexistent-user-xyz" in result.stderr
