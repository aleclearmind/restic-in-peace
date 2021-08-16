import re
import os

from .command import run_command
from .logging import logger


def get_active_network_interface(for_ip="1.1.1.1"):
    # There are two kinds of responses we expect from ip. The first one has this format, and means that the
    # required IP 1.1.1.1 can be reached using the gateway 192.168.1.254
    # TODO: support ipv6
    # TODO: the resolution should be somehow recursive, to handle VPNs or complex routing

    # First format: 1.1.1.1 via 192.168.1.254 dev wlp3s0 src 192.168.1.151 uid 1000
    routed_ip_regex = re.compile(
        r"^(?P<dst>\d+\.\d+\.\d+\.\d+) "
        r"via (?P<gateway>\d+\.\d+\.\d+\.\d+) "
        r"dev (?P<nic>([^ ])*) "
        r"src (?P<src>\d+\.\d+\.\d+\.\d+)"
    )
    # Second format: 192.168.1.254 dev wlp3s0 src 192.168.1.151 uid 1000
    local_ip_regex = re.compile(
        r"^(?P<dst>\d+\.\d+\.\d+\.\d+) " r"dev (?P<nic>[^ ]*)" r"src (?P<src>\d+\.\d+\.\d+\.\d+)"
    )

    process = run_command(f"env ip route get {for_ip}", shell=True)
    route = routed_ip_regex.match(process.stdout)
    if route is None:
        return None
    else:
        return route.group("nic")


def get_wifi_network():
    interface = get_active_network_interface()
    if interface is None:
        logger.error("Could not determine default network interface")
        return

    with open(os.path.join("/sys/class/net/", interface, "uevent")) as f:
        if "DEVTYPE=wlan" not in f.read():
            logger.info(f"Default interface {interface} was not determined to be wifi")
            return

    process = run_command(f"iw dev {interface} link", shell=True)
    essid_regex = re.compile("SSID: (?P<essid>.*)")
    match = essid_regex.search(process.stdout)
    if match is None:
        logger.error(f"Could not determine network for interface {interface}")
        return
    else:
        network = match.group("essid")
        logger.info(f"Interface {interface} is connected to {network}")
        return network


def network_ok(blacklist=[], whitelist=[]):
    current_network = get_wifi_network()
    if current_network is None:
        logger.info(f"The computer default route does not appear to be a wireless network")
        return True

    for pattern in blacklist:
        if re.search(pattern, current_network):
            logger.info(f"Network {current_network} is blacklisted")
            return False

    if not whitelist:
        logger.info(f"Network {current_network} is not blacklisted and no whitelist supplied, continuing...")
        return True

    for pattern in whitelist:
        if re.search(pattern, current_network):
            logger.info(f"Network {current_network} is whitelisted")
            return True
    else:
        logger.info(f"Network {current_network} is not in the whitelist")
        return False
