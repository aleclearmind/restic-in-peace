import glob


def on_battery():
    for status_filepath in glob.glob("/sys/class/power_supply/BAT*/status"):
        with open(status_filepath) as status_file:
            status = status_file.read()
            if status.strip() == "Discharging":
                return True
    return False


def battery_ok(skip_on_battery):
    if skip_on_battery:
        return not on_battery()
    else:
        return True
