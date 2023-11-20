from functools import cached_property
from itertools import islice
from ipaddress import IPv4Interface, IPv6Interface, ip_interface
from secrets import token_bytes
import sys

from attrs import define
from attrs.setters import convert
from wireguard_tools import WireguardConfig, WireguardKey
from wireguard_tools.wireguard_config import WireguardPeer

from .types import BaseNode
from .remote import WireguardRemote
from .gretap import gretap_up, gretap_down
from .util import RandomIPv6Address


@define(kw_only=True, slots=False, on_setattr=convert)
class MeshNode(BaseNode):
    mesh: "mesh.Mesh"
    index: int
    config: WireguardConfig | None = None

    @cached_property
    def remote(self) -> WireguardRemote:
        return WireguardRemote(
            connect=self.ssh,
            interface=f"wg-{self.mesh.name}{self.index}",
        )

    @property
    def tag(self) -> str:
        return f"{self.network_addr.ip}@{self.wg.host}:{self.wg.port}"

    @property
    def network_addr(self) -> IPv4Interface | IPv6Interface:
        return ip_interface(f"{islice(self.mesh.network.hosts(), self.index, None).__next__()}/{self.mesh.network.prefixlen}")

    @property
    def info(self) -> dict:
        return dict(
            host=self.remote.host,
            is_up=self.remote.is_up,
            config_exists=self.remote.config_exists,
            address=str(self.network_addr),
        )

    def __attrs_post_init__(self):
        self.__config_init()

    def __config_init(self):
        self.config = self.remote.config

        if self.config is not None:
            if isinstance(self.addr, RandomIPv6Address):
                self.addr = self.config.addresses[0].ip
            if self.config.listen_port is not None:
                self.port = self.config.listen_port

        else:
            self.config = WireguardConfig(
                private_key=WireguardKey.generate(),
                addresses=[ip_interface(self.addr)],
                listen_port=self.port,
            )

    @classmethod
    def from_node(cls, mesh: "mesh.Mesh", index: int, node: BaseNode) -> "MeshNode":
        return cls(
            mesh=mesh,
            index=index,
            ssh=node.ssh,
            wg=node.wg,
            port=node.port,
            addr=node.addr,
            json=node.json,
        )

    def can_peer(self, other: "MeshNode") -> bool:
        """Check if this node can peer with another node.

        Uses the Wireguard UDP listen ports and endpoints to check if the nodes can peer,
        so this can only be reliable when Wireguard is not up on either node.
        """
        return (not self.remote.is_up and self.remote.udping_from(
            listen_port=self.port,
            endpoint_host=self.wg.host,
            endpoint_port=self.wg.port,
            remote=other.remote,
        )) or (not other.remote.is_up and other.remote.udping_from(
            listen_port=other.port,
            endpoint_host=other.wg.host,
            endpoint_port=other.wg.port,
            remote=self.remote,
        ))

    def as_peer(self, **kwds) -> WireguardPeer:
        return WireguardPeer(
            public_key=self.config.private_key.public_key(),
            allowed_ips=[ip_interface(self.addr)],
            endpoint_host=self.wg.host,
            endpoint_port=self.wg.port,
            friendly_name=self.remote.host,
            friendly_json=self.json or None,
            **kwds,
        )

    def peer_with(self, other: "MeshNode"):
        self_pubkey = self.config.private_key.public_key()
        other_pubkey = other.config.private_key.public_key()

        if self_pubkey == other_pubkey:
            raise ValueError("Cannot peer with self")

        if self_pubkey in other.config.peers and other_pubkey in self.config.peers:
            self_peer = other.config.peers[self_pubkey]
            other_peer = self.config.peers[other_pubkey]

            if self_peer.allowed_ips[0].ip != self.addr or other_peer.allowed_ips[0].ip != other.addr:
                raise ValueError("Existing peering has different addresses")

            # noinspection DuplicatedCode
            if not self.json and self_peer.friendly_json is not None:
                self.json = self_peer.friendly_json
            elif self.json and self_peer.friendly_json != self.json:
                self_peer.friendly_json = self.json

            if self_peer.friendly_name != self.remote.host:
                self_peer.friendly_name = self.remote.host

            # noinspection DuplicatedCode
            if not other.json and other_peer.friendly_json is not None:
                other.json = other_peer.friendly_json
            elif other.json and other_peer.friendly_json != other.json:
                other_peer.friendly_json = other.json

            if other_peer.friendly_name != other.remote.host:
                other_peer.friendly_name = other.remote.host

            return

        if not self.mesh.full and not self.can_peer(other):
            return

        preshared_key = WireguardKey(token_bytes(32))
        self_peer = self.as_peer(preshared_key=preshared_key)
        other_peer = other.as_peer(preshared_key=preshared_key)

        self.config.add_peer(other_peer)
        other.config.add_peer(self_peer)

        self_index = self.index
        other_index = other.index
        self_gretap_name = f"{self.mesh.name}{self_index}{other_index}"
        other_gretap_name = f"{other.mesh.name}{other_index}{self_index}"
        self_gretap_addr = self.addr
        other_gretap_addr = other.addr
        self_bridge_name = f"{self.mesh.name}{self_index}"
        other_bridge_name = f"{other.mesh.name}{other_index}"
        self_bridge_addr = self.network_addr
        other_bridge_addr = other.network_addr

        self.config.postup.extend(gretap_up(
            gretap_name=self_gretap_name,
            bridge_name=self_bridge_name,
            local=self_gretap_addr,
            remote=other_gretap_addr,
            bridge_addr=self_bridge_addr,
        ))

        other.config.postup.extend(gretap_up(
            gretap_name=other_gretap_name,
            bridge_name=other_bridge_name,
            local=other_gretap_addr,
            remote=self_gretap_addr,
            bridge_addr=other_bridge_addr,
        ))

        self.config.predown.extend(gretap_down(
            gretap_name=self_gretap_name,
            bridge_name=self_bridge_name,
        ))

        other.config.predown.extend(gretap_down(
            gretap_name=other_gretap_name,
            bridge_name=other_bridge_name,
        ))

    def up(self, *, write: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote

        if remote.is_up:
            remote.down()

        if write or write is None and (write := not remote.config_exists) or (write := remote.config != self.config):
            try:
                remote.config_write(self.config)

            except Exception as exc:
                print(f"[{self.tag}] [up] !! config_write failed: {exc}", file=sys.stderr)
                return False

        if isinstance(up := remote.up(), RuntimeError):
            print(f"[{self.tag}] [up] !! {remote.interface}:\n{up}", file=sys.stderr)
            if write:
                remote.config_remove()
            return False

        else:
            print(f"[{self.tag}] [up] ++ {remote.interface}:\n{up}", file=sys.stderr)

        return True

    def down(self, *, remove: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote

        if remote.is_up:
            if isinstance(down := remote.down(), RuntimeError):
                print(f"[{self.tag}] [down] !! {remote.interface}:\n{down}", file=sys.stderr)

                if not remote.is_up and remove:
                    remote.config_remove()
                return False

            else:
                print(f"[{self.tag}] [down] -- {remote.interface}:\n{down}", file=sys.stderr)

        if remove or remove is None and remote.config_exists:
            remote.config_remove()

        return True

    def sync(self, *, up: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote
        remote_config = remote.config

        if remote_config is None or remote_config != self.config:
            if up or up is None and remote.is_up:
                return self.up(write=True)

            remote.config_write(self.config)
            return True

        return False
