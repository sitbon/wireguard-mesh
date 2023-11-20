from hashlib import sha3_512
from ipaddress import IPv4Interface, IPv6Interface, IPv6Address, IPv4Network, IPv6Network, ip_interface
from itertools import islice
from math import log2, ceil
from random import getrandbits
from typing import Iterator


def interface_name(key: str) -> str:
    return sha3_512(key.encode()).hexdigest()[:15]


class RandomIPv6Address(IPv6Address):
    def __init__(self):
        super().__init__(b'\xfd' + getrandbits(120).to_bytes(15, 'big'))


def generate_subnets(network: IPv4Network | IPv6Network, count: int) -> Iterator[IPv4Network | IPv6Network]:
    """Generate a list of subnets from a network.

    Args:
        network (IPv4Network | IPv6Network): The network to generate subnets from.
        count (int): The number of subnets to generate.

    Returns:
        list[IPv4Network | IPv6Network]: The list of generated subnets.
    """
    return network.subnets(
        new_prefix=network.prefixlen + ceil(log2(count))
    )


def generate_hosts(network: IPv4Network | IPv6Network, count: int, prefixlen: int | None = None) -> Iterator[IPv4Interface | IPv6Interface]:
    """Generate a list of host interfaces from a network.

    Args:
        network (IPv4Network | IPv6Network): The network to generate hosts from.
        count (int): The number of hosts to generate.
        prefixlen (int | None, optional): The prefix length to use for the generated hosts. Defaults to ``None``.

    Returns:
        list[IPv4Interface | IPv6Interface]: The list of generated host interfaces.
    """
    return islice(
        map(
            lambda addr: ip_interface((addr, prefixlen if prefixlen is not None else network.prefixlen)),  # type: ignore[arg-type]  # noqa: E501
            network.hosts()
        ),
        count
    )
