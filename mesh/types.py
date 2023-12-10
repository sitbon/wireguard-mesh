from functools import cached_property
from ipaddress import (
    IPv4Interface, IPv6Interface, IPv4Address, IPv6Address, IPv4Network, IPv6Network, ip_address, ip_interface, ip_network,
)
from random import getrandbits
from typing import Any, Self

from attrs import AttrsInstance, define, field, asdict
from attrs.converters import optional
from attrs.setters import frozen
import yaml

from .util import host_index

Network = IPv4Network | IPv6Network
Interface = IPv4Interface | IPv6Interface
Address = IPv4Address | IPv6Address

__all__ = (
    "IPv4Interface", "IPv6Interface", "IPv4Address", "IPv6Address", "IPv4Network", "IPv6Network",
    "ip_address", "ip_interface", "ip_network",
    "Network", "Interface", "Address",
    "RandomIPv6Address",
    "RandomIPv6Interface",
    "Endpoint", "NodeType",
    "DEFAULT_PORT",
)

DEFAULT_PORT = 51820


class RandomIPv6Address(IPv6Address):
    def __init__(self):
        super().__init__(b'\xfd' + getrandbits(120).to_bytes(15, 'big'))


class RandomIPv6Interface(IPv6Interface):
    def __init__(self):
        super().__init__(RandomIPv6Address())


def _ip_address_or_name(value: str) -> Address | str:
    try:
        return ip_address(value)
    except ValueError:
        return value


@define
class Endpoint(AttrsInstance):
    """Wireguard endpoint.

    Pedantic implementation to support ``wireguard-tools`` endpoint format.
    """
    host: Address | str = field(converter=_ip_address_or_name)
    port: int | None = field(default=None, converter=optional(int))

    @port.validator  # noqa
    def __port_validator(self, _: str, value: Any):
        if value is not None and not 0 <= value <= 65535:
            raise ValueError(f"Invalid port {value!r}")

    def __str__(self):
        return f"{self.host}:{self.port}" if self.port is not None else str(self.host)

    @classmethod
    def convert(cls, value: str | dict | Self) -> Self:
        if isinstance(value, str):
            return cls(*value.rsplit(":", 1))
        if isinstance(value, dict):
            return cls(**value)
        if isinstance(value, Endpoint):
            return value
        raise TypeError(f"Cannot parse endpoint from {value!r}")


@define(kw_only=True, slots=False, order=True, eq=True)
class NodeType(AttrsInstance):
    """A node in a Wireguard mesh network.
    """
    name: str = field(on_setattr=frozen)

    addr: Interface = field(
        converter=lambda x: ip_interface(x) if not isinstance(x, (IPv4Interface, IPv6Interface)) else x,
        on_setattr=frozen,
    )
    """Network bridge address for the node.
    
    Must be in the mesh network.
    """

    ssh: str | dict = field()
    """SSH connection string or arguments to the node.
    
    It is recommended to use the default SSH config file to specify connection details.
    
    This field is passed directly to ``fabric.Connection``, so any valid connection string
    can be used.
    """

    endpoint: Endpoint = field(converter=Endpoint.convert)
    """Public or network-accessible Wireguard endpoint."""

    listen_port: int | None = field(default=None, converter=optional(int))
    """Wireguard listen port."""

    json: dict[str, Any] | None = None
    """Set ``friendly_json`` data for all peers."""

    prio: int | None = field(default=None)
    """Bridge priority for GRE tunnels, normalized to ``-8 <= prio <= 7``.
    
    Calculated as ``32768 + 4096 * prio``.
    
    This field is used to create the initial bridge configurations, and should not be changed.
    
    When None, the bridge priority will be calculated as ``-8 + ((index-1) % 16)``.
    - Having any difference in bridge priority between nodes helps to avoid bad routing decisions.
    """

    @cached_property
    def index(self) -> int:
        return host_index(self.addr)

    @cached_property
    def ip(self) -> Address:
        return self.addr.ip

    @cached_property
    def network(self) -> Network:
        return self.addr.network

    def __str__(self):
        return f"[{self.index}] {self.addr.ip} <{self.name}> via {self.endpoint}"

    def asdict(self, *, serializer=None) -> dict:
        return asdict(self, filter=lambda a, v: v is not None and not a.name.startswith("_"), value_serializer=serializer)

    @name.validator  # noqa
    def __name_validator(self, _: str, value: Any):
        if not value:
            raise ValueError("Node name cannot be empty")

    @addr.validator  # noqa
    def __addr_validator(self, _: str, value: Interface):
        if (prefixlen := value.network.prefixlen) == value.max_prefixlen or prefixlen == 0:
            raise ValueError(f"Address {value!r} is not a network address")

    @ssh.validator  # noqa
    def __ssh_validator(self, _: str, value: Any):
        if isinstance(value, str):
            if not value:
                raise ValueError("SSH connection string cannot be empty")
        elif isinstance(value, dict):
            if "host" not in value:
                raise ValueError("SSH connection dict args must specify host")

    @listen_port.validator  # noqa
    def __port_validator(self, _: str, value: Any):
        if value is not None and not 0 <= value <= 65535:
            raise ValueError(f"Invalid port {value!r}")

    @prio.validator  # noqa
    def __prio_validator(self, _: str, value: Any):
        if value is not None and not -8 <= value <= 7:
            raise ValueError(f"Invalid bridge priority {value!r}")

    @classmethod
    def convert(cls, value, *, key: str | None = None) -> Self:
        if isinstance(value, cls):
            return value

        if isinstance(value, dict):
            if key is not None:
                value["name"] = value.setdefault("name", key) or key
            return cls(**value)

        raise TypeError(f"Cannot convert {value!r} to {cls.__name__}")

    @classmethod
    def convert_all(cls, value: dict | list) -> dict[str, Self]:
        if isinstance(value, dict):
            return {key: cls.convert(val, key=key) for key, val in value.items()}

        if isinstance(value, list):
            return {
                node_.name: (node_ := cls.convert(node))
                for node in value
            }

        raise TypeError(f"Cannot convert {value!r} to {cls.__name__}")


@define(kw_only=True, slots=False, order=True, eq=True)
class MeshType(AttrsInstance):
    name: str = field(on_setattr=frozen)

    network: Network = field(
        converter=lambda x: ip_network(x) if not isinstance(x, (IPv4Network, IPv6Network)) else x,
        on_setattr=frozen,
    )
    """Mesh network.

    This network will be routed among all nodes in the mesh.
    """

    full: bool = True
    """Peer all node pairs regardless of reachability.

    When False, checks whether two nodes can reach each other before peering them.
    """

    nodes: dict[str, NodeType]

    def asdict(self, *, serializer=None) -> dict:
        return dict(
            name=self.name,
            network=str(self.network),
            **(dict(full=False) if not self.full else {}),
            nodes={node.name: node.asdict(serializer=serializer) for node in self.nodes.values()},
        )

    def asyaml(self, *, serializer=None) -> str:
        return yaml.dump(self.asdict(serializer=serializer), sort_keys=False, allow_unicode=True)
