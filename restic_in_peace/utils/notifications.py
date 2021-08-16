import notify2
from notify2 import URGENCY_LOW, URGENCY_NORMAL, URGENCY_CRITICAL


notification = notify2.Notification("")


def get_progress_bar(progress, width=30, full_char="▰", empty_char="▱"):
    n_done_bars = int(progress / 100 * width)
    return full_char * n_done_bars + empty_char * (width - n_done_bars)


def show_notification(
    summary,
    message="",
    icon="",
    urgency=notify2.URGENCY_NORMAL,
    timeout=notify2.EXPIRES_DEFAULT,
    progress=None,
    replace=None,
):
    if not notify2.is_initted():
        notify2.init("restic-in-peace")

    if progress is not None:
        message += "\n" + get_progress_bar(progress)

    notification.summary = summary
    notification.message = message
    notification.icon = icon
    notification.set_urgency(urgency)
    notification.set_timeout(timeout)
    notification.show()
    return notification
