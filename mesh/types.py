from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any, Self

from attrs import define, field
from attrs.setters import convert
from .util import RandomIPv6Address


def _ip_address_or_name(value: str) -> IPv4Address | IPv6Address | str:
    try:
        return ip_address(value)
    except ValueError:
        return value


@define(on_setattr=convert)
class Endpoint:
    """Wireguard endpoint.

    Pedantic implementation to support ``wireguard-tools`` endpoint format.
    """
    host: IPv4Address | IPv6Address | str = field(converter=_ip_address_or_name)
    port: int = field(default=51820, converter=int)

    @classmethod
    def convert(cls, value: str | dict | Self) -> Self:
        if isinstance(value, str):
            return cls(*value.rsplit(":", 1))
        if isinstance(value, dict):
            return cls(**value)
        if isinstance(value, Endpoint):
            return value
        raise TypeError(f"Cannot parse endpoint from {value!r}")


@define(kw_only=True, on_setattr=convert)
class BaseNode:
    """A node in a Wireguard mesh network.

    This is a base class meant to be used for configuration from dictionaries.

    ``Mesh.nodes`` is a dictionary of Node objects, which are converted to ``MeshNode`` objects
    in ``Mesh.__attrs_post_init__()``.
    """
    ssh: str | dict
    """SSH connection string or arguments to the node.
    
    It is recommended to use the default SSH config file to specify connection details.
    
    This field is passed directly to ``fabric.Connection``, so any valid connection string
    can be used.
    """

    wg: Endpoint = field(converter=Endpoint.convert)
    """Public or mesh-accessible Wireguard endpoint."""

    port: int = field(default=51820, converter=int)
    """Wireguard listen port."""

    json: dict[str, Any] = field(factory=dict)
    """Set ``friendly_json`` data for all peers."""

    addr: IPv4Address | IPv6Address | RandomIPv6Address = field(
        converter=lambda x: ip_address(x) if not isinstance(x, (IPv4Address, IPv6Address)) else x,
        factory=RandomIPv6Address,
    )
    """Wireguard address of the node. If not specified, a random IPv6 address will be generated.
    
    This address is only used to establish a GRE tunnel between mesh nodes.
    It is not used for routing, and should not be changed once the mesh is created (configs written).
    """

    prio: int | None = field(default=None, validator=[lambda _, __, x: x is None or -8 <= x <= 7])
    """Bridge priority for GRE tunnels, normalized to ``-8 <= prio <= 7``.
    
    Calculated as ``32768 + 4096 * prio``.
    
    This field is used to create the initial bridge configurations, and should not be changed.
    
    When None, the bridge priority will be calculated as ``-8 + (index % 16)``.
    - Having any difference in bridge priority between nodes helps to avoid bad routing decisions.
    """
