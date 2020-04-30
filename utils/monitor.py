import requests

from .logging import logger


def log_event_to_monitors(event, monitor_urls, additional_data={}):
    for url in monitor_urls:
        data = {"event": event}
        data.update(additional_data)
        try:
            r = requests.post(url, data=data, timeout=5)
        except requests.exceptions.RequestException as e:
            # TODO: this leaks the full URL to the logs, maybe we should parse it and use only the host
            logger.error(f"Exception while connecting to {url}: {e}")
