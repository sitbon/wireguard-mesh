from ipaddress import (
    IPv4Interface, IPv6Interface, IPv4Address, IPv6Address, IPv4Network, IPv6Network, ip_address, ip_interface, ip_network,
)
from random import getrandbits
from typing import Any, Self

from attrs import define, field

Network = IPv4Network | IPv6Network
Interface = IPv4Interface | IPv6Interface
Address = IPv4Address | IPv6Address

__all__ = (
    "IPv4Interface", "IPv6Interface", "IPv4Address", "IPv6Address", "IPv4Network", "IPv6Network",
    "ip_address", "ip_interface", "ip_network",
    "Network", "Interface", "Address",
    "RandomIPv6Address",
    "Endpoint", "NodeType",
)

PORT = 51820


class RandomIPv6Address(IPv6Address):
    def __init__(self):
        super().__init__(b'\xfd' + getrandbits(120).to_bytes(15, 'big'))


def _ip_address_or_name(value: str) -> Address | str:
    try:
        return ip_address(value)
    except ValueError:
        return value


@define
class Endpoint:
    """Wireguard endpoint.

    Pedantic implementation to support ``wireguard-tools`` endpoint format.
    """
    host: Address | str = field(converter=_ip_address_or_name)
    port: int = field(default=PORT, converter=int)

    def __str__(self):
        return f"{self.host}:{self.port}" if self.port != PORT else str(self.host)

    @classmethod
    def convert(cls, value: str | dict | Self) -> Self:
        if isinstance(value, str):
            return cls(*value.rsplit(":", 1))
        if isinstance(value, dict):
            return cls(**value)
        if isinstance(value, Endpoint):
            return value
        raise TypeError(f"Cannot parse endpoint from {value!r}")


@define(kw_only=True)
class NodeType:
    """A node in a Wireguard mesh network.

    This is a base class meant to be used for configuration from dictionaries.

    ``Mesh.nodes`` is a dictionary of Node objects, which are converted to ``MeshNode`` objects
    in ``Mesh.__attrs_post_init__()``.
    """
    idx: int = field(converter=int)
    """Node index in the mesh.
    
    Used to determine the node's address in the mesh network.
    """

    ssh: str | dict
    """SSH connection string or arguments to the node.
    
    It is recommended to use the default SSH config file to specify connection details.
    
    This field is passed directly to ``fabric.Connection``, so any valid connection string
    can be used.
    """

    wg: Endpoint = field(converter=Endpoint.convert)
    """Public or mesh-accessible Wireguard endpoint."""

    port: int = field(default=PORT, converter=int)
    """Wireguard listen port."""

    json: dict[str, Any] = field(factory=dict)
    """Set ``friendly_json`` data for all peers."""

    addr: Address | RandomIPv6Address = field(
        converter=lambda x: ip_address(x) if not isinstance(x, (IPv4Address, IPv6Address)) else x,
        factory=RandomIPv6Address,
    )
    """Wireguard address of the node. If not specified, a random IPv6 address will be generated.
    
    This address is only used to establish a GRE tunnel between mesh nodes.
    It is not used for routing, and should not be changed once the mesh is created (configs written).
    """

    prio: int | None = field(default=None)
    """Bridge priority for GRE tunnels, normalized to ``-8 <= prio <= 7``.
    
    Calculated as ``32768 + 4096 * prio``.
    
    This field is used to create the initial bridge configurations, and should not be changed.
    
    When None, the bridge priority will be calculated as ``-8 + ((index-1) % 16)``.
    - Having any difference in bridge priority between nodes helps to avoid bad routing decisions.
    """

    @property
    def conf(self) -> dict:
        props = dict(idx=self.idx, ssh=self.ssh, wg=str(self.wg), addr=str(self.addr))

        if self.port != PORT:
            props["port"] = self.port

        if self.json:
            props["json"] = self.json

        if self.prio is not None:
            props["prio"] = self.prio

        return props

    @idx.validator  # noqa
    def __idx_validator(self, _: str, value: Any):
        if not 0 < value < 255:
            raise ValueError(f"Invalid node index {value!r}")

    @prio.validator  # noqa
    def __prio_validator(self, _: str, value: Any):
        if value is not None and not -8 <= value <= 7:
            raise ValueError(f"Invalid bridge priority {value!r}")
