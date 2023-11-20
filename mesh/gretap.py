from ipaddress import IPv4Interface, IPv6Interface, IPv4Address, IPv6Address


def gretap_up(
        gretap_name: str,
        bridge_name: str,
        local: IPv4Address | IPv6Address,
        remote: IPv4Address | IPv6Address,
        bridge_addr: IPv4Interface | IPv6Interface,
) -> list[str]:
    six = local.version == 6 and remote.version == 6

    return [
        f"ip link add dev {gretap_name} type {'ip6gretap' if six else 'gretap'} local {local} remote {remote}",
        f"ip link set dev {gretap_name} up",
        (
            f"if [ ! -f /sys/class/net/{bridge_name}/bridge/bridge_id ]; then "
            f"  ip link add name {bridge_name} type bridge stp 1; "
            f"  ip link set dev {bridge_name} up; "
            f"  ip addr add {bridge_addr} dev {bridge_name}; fi"
        ),
        f"ip link set dev {gretap_name} master {bridge_name}",
    ]


def gretap_down(gretap_name: str, bridge_name: str) -> list[str]:
    return [
        f"ip link set dev {gretap_name} nomaster",
        f"ip link del dev {gretap_name}",
        (
            f"if ! ip a | grep -q 'master {bridge_name}'; then "
            f"  ip link del dev {bridge_name}; fi"
        ),
    ]
