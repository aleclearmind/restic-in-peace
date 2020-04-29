import glob
import subprocess
import sys
import re

from loguru import logger

logger.configure(handlers=[
    {"sink": sys.stdout, "format": "<level>{time}|{level}|{extra[logger_name]}|{message}</level>", "level": "ERROR"}
])
utils_logs = logger.bind(logger_name="utils")


def on_battery():
    for status_filepath in glob.glob("/sys/class/power_supply/BAT*/status"):
        with open(status_filepath) as status_file:
            status = status_file.read()
            if status.strip() == "Discharging":
                return True
    return False


def run_command(args, shell=False):
    utils_logs.debug(f"About to execute {args}")
    process = subprocess.run(args, capture_output=True, universal_newlines=True, shell=shell)
    return process


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
        utils_logs.error("Could not determine default network interface")
        return

    wifi_interfaces_regex = re.compile(r"wlp\ds\d|wlan\d|wifi\d")
    if wifi_interfaces_regex.match(interface) is None:
        utils_logs.info(f"Default interface {interface} was not determined to be wifi")
        return

    process = run_command(f"iwconfig {interface}", shell=True)
    match = essid_regex.search(process.stdout)
    if match is None:
        utils_logs.error(f"Could not determine network for interface {interface}")
        return
    else:
        network = match.group("essid")
        utils_logs.info(f"Interface {interface} is connected to {network}")
        return network
