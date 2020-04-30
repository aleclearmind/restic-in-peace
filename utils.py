import glob
import re
import sys

import requests
from loguru import logger

from command import run_command

logger.configure(handlers=[
    {"sink": sys.stdout, "format": "<level>{time}|{level}|{extra[logger_name]}|{message}</level>", "level": "INFO"}
])
log = logger.bind(logger_name="utils")


def on_battery():
    for status_filepath in glob.glob("/sys/class/power_supply/BAT*/status"):
        with open(status_filepath) as status_file:
            status = status_file.read()
            if status.strip() == "Discharging":
                return True
    return False


def get_active_network_interface(for_ip="1.1.1.1"):
    # There are two kinds of responses we expect from ip. The first one has this format, and means that the
    # required IP 1.1.1.1 can be reached using the gateway 192.168.1.254
    # TODO: support ipv6
    # TODO: the resolution should be somehow recursive, to handle VPNs or complex routing

    # First format: 1.1.1.1 via 192.168.1.254 dev wlp3s0 src 192.168.1.151 uid 1000
    routed_ip_regex = re.compile(r"^(?P<dst>\d+\.\d+\.\d+\.\d+) "
                                 r"via (?P<gateway>\d+\.\d+\.\d+\.\d+) "
                                 r"dev (?P<nic>([^ ])*) "
                                 r"src (?P<src>\d+\.\d+\.\d+\.\d+)")
    # Second format: 192.168.1.254 dev wlp3s0 src 192.168.1.151 uid 1000
    local_ip_regex = re.compile(r"^(?P<dst>\d+\.\d+\.\d+\.\d+) "
                                r"dev (?P<nic>[^ ]*)"
                                r"src (?P<src>\d+\.\d+\.\d+\.\d+)")

    process = run_command(f"env ip route get {for_ip}", shell=True)
    route = routed_ip_regex.match(process.stdout)
    if route is None:
        return None
    else:
        return route.group("nic")


def get_wifi_network():
    essid_regex = re.compile('ESSID:"(?P<essid>[^"]*)"')
    interface = get_active_network_interface()
    if interface is None:
        log.error("Could not determine default network interface")
        return

    wifi_interfaces_regex = re.compile(r"wlp\ds\d|wlan\d|wifi\d")
    if wifi_interfaces_regex.match(interface) is None:
        log.info(f"Default interface {interface} was not determined to be wifi")
        return

    process = run_command(f"iwconfig {interface}", shell=True)
    match = essid_regex.search(process.stdout)
    if match is None:
        log.error(f"Could not determine network for interface {interface}")
        return
    else:
        network = match.group("essid")
        log.info(f"Interface {interface} is connected to {network}")
        return network


def battery_ok(skip_on_battery):
    if skip_on_battery:
        return not on_battery()
    else:
        return True


def network_ok(blacklist=[], whitelist=[]):
    current_network = get_wifi_network()
    if current_network is None:
        log.info(f"The computer default route does not appear to be a wireless network")
        return True

    for pattern in blacklist:
        if re.search(pattern, current_network):
            log.info(f"Network {current_network} is blacklisted")
            return False

    if not whitelist:
        log.info(f"Network {current_network} is not blacklisted and no whitelist supplied, continuing...")
        return True

    for pattern in whitelist:
        if re.search(pattern, current_network):
            log.info(f"Network {current_network} is whitelisted")
            return True
    else:
        log.info(f"Network {current_network} is not in the whitelist")
        return False


def log_event_to_monitors(event, monitor_urls, additional_data={}):
    for url in monitor_urls:
        data = {"event": event}
        data.update(additional_data)
        try:
            r = requests.post(url, data=data, timeout=5)
        except requests.exceptions.RequestException as e:
            # TODO: this leaks the full URL to the logs, maybe we should parse it and use only the host
            log.error(f"Exception while connecting to {url}: {e}")
