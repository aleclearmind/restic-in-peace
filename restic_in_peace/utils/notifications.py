from .command import run_command


def send_notification(message, title=None, icon=None, urgency="normal"):
    cmd = ["notify-send"]
    if icon:
        cmd += ["-i", icon]
    if urgency:
        cmd += ["-u", urgency]
    if title:
        cmd.append(title)
    cmd.append(message)
    run_command(cmd)
