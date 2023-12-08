from hashlib import sha3_512
from itertools import islice
from math import log2, ceil
from typing import Iterator

from .types import Network, Interface, ip_interface


def interface_name(key: str) -> str:
    return sha3_512(key.encode()).hexdigest()[:15]


def generate_subnets(network: Network, count: int) -> Iterator[Network]:
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


def generate_hosts(network: Network, count: int, prefixlen: int | None = None) -> Iterator[Interface]:
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
            lambda addr: ip_interface(
                (addr, prefixlen if prefixlen is not None else network.prefixlen)
            ),
            network.hosts()
        ),
        count
    )
