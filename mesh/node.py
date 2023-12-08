from functools import cached_property
from itertools import islice
from secrets import token_bytes
import sys

from attrs import define
from wireguard_tools import WireguardConfig, WireguardKey
from wireguard_tools.wireguard_config import WireguardPeer

from .types import Interface, RandomIPv6Address, NodeType, ip_interface
from .remote import WireguardRemote
from .gretap import gretap_up, gretap_down


@define(kw_only=True, slots=False)
class MeshNode(NodeType):
    mesh: "mesh.Mesh"
    config: WireguardConfig | None = None

    @cached_property
    def remote(self) -> WireguardRemote:
        return WireguardRemote(
            connect=self.ssh,
            interface=f"wg-{self.mesh.name}{self.idx}",
        )

    @property
    def tag(self) -> str:
        return f"<{self.idx}> {self.network_addr.ip}@{self.wg.host}:{self.wg.port}"

    @property
    def network_addr(self) -> Interface:
        return ip_interface(
            f"{islice(self.mesh.network.hosts(), self.idx - 1, None).__next__()}/{self.mesh.network.prefixlen}"
        )

    @property
    def bridge_priority(self) -> int:
        prio = self.prio if self.prio is not None else -8 + (self.idx - 1) % 16
        return 32768 + 4096 * prio

    @property
    def info(self) -> dict:
        return dict(
            host=self.remote.host,
            is_up=self.remote.is_up,
            config_exists=self.remote.config_exists,
            address=str(self.network_addr.ip),
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

    def config_write(self):
        self.remote.config_write(self.config)

    def config_remove(self):
        self.remote.config_remove()

    @classmethod
    def from_node(cls, mesh: "mesh.Mesh", node: NodeType) -> "MeshNode":
        return cls(
            mesh=mesh,
            **node.conf,
        )

    def can_peer(self, other: "MeshNode") -> bool:
        """Check if this node can peer with another node.

        Uses the Wireguard UDP listen ports and endpoints to check if the nodes can peer,
        so this can only be reliable when Wireguard is not up on either node.
        """
        print(f"[{self.tag}] [can_peer] {other.tag}", file=sys.stderr)
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
        this_pubkey = self.config.private_key.public_key()
        that_pubkey = other.config.private_key.public_key()

        if this_pubkey == that_pubkey:
            raise ValueError("Cannot peer with self")

        if this_pubkey in other.config.peers and that_pubkey in self.config.peers:
            this_peer = other.config.peers[this_pubkey]
            that_peer = self.config.peers[that_pubkey]

            if this_peer.allowed_ips[0].ip != self.addr or that_peer.allowed_ips[0].ip != other.addr:
                raise ValueError("Existing peering has different addresses")

            # noinspection DuplicatedCode
            if not self.json and this_peer.friendly_json is not None:
                self.json = this_peer.friendly_json
            elif self.json and this_peer.friendly_json != self.json:
                this_peer.friendly_json = self.json

            if this_peer.friendly_name != self.remote.host:
                this_peer.friendly_name = self.remote.host

            # noinspection DuplicatedCode
            if not other.json and that_peer.friendly_json is not None:
                other.json = that_peer.friendly_json
            elif other.json and that_peer.friendly_json != other.json:
                that_peer.friendly_json = other.json

            if that_peer.friendly_name != other.remote.host:
                that_peer.friendly_name = other.remote.host

            return

        if not self.mesh.full and not self.can_peer(other):
            return

        preshared_key = WireguardKey(token_bytes(32))
        this_peer = self.as_peer(preshared_key=preshared_key)
        that_peer = other.as_peer(preshared_key=preshared_key)

        self.config.add_peer(that_peer)
        other.config.add_peer(this_peer)

        this_index = self.idx
        that_index = other.idx
        this_gretap_name = f"gt-{self.mesh.name}{that_index}"
        that_gretap_name = f"gt-{other.mesh.name}{this_index}"
        this_gretap_addr = self.addr
        that_gretap_addr = other.addr
        this_bridge_name = f"br-{self.mesh.name}"
        that_bridge_name = f"br-{other.mesh.name}"
        this_bridge_addr = self.network_addr
        that_bridge_addr = other.network_addr

        self.config.postup.extend(gretap_up(
            gretap_name=this_gretap_name,
            bridge_name=this_bridge_name,
            priority=self.bridge_priority,
            local=this_gretap_addr,
            remote=that_gretap_addr,
            bridge_addr=this_bridge_addr,
        ))

        other.config.postup.extend(gretap_up(
            gretap_name=that_gretap_name,
            bridge_name=that_bridge_name,
            priority=other.bridge_priority,
            local=that_gretap_addr,
            remote=this_gretap_addr,
            bridge_addr=that_bridge_addr,
        ))

        self.config.predown.extend(gretap_down(
            gretap_name=this_gretap_name,
            bridge_name=this_bridge_name,
        ))

        other.config.predown.extend(gretap_down(
            gretap_name=that_gretap_name,
            bridge_name=that_bridge_name,
        ))

    def up(self, *, write: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote

        if write or write is None and (write := not remote.config_exists) or (write := remote.config != self.config):
            try:
                remote.config_write(self.config)

            except Exception as exc:
                print(f"[{self.tag}] [up] !! config_write failed: {exc}", file=sys.stderr)
                return False

        if remote.is_up:
            if not write:
                return True
            remote.down()

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
