from functools import cached_property
from secrets import token_bytes
import sys
from typing import TypedDict

from attrs import define, field
from wireguard_tools import WireguardConfig, WireguardKey
from wireguard_tools.wireguard_config import WireguardPeer

from .types import RandomIPv6Interface, Interface, NodeType, MeshType, ip_interface, DEFAULT_PORT
from .remote import WireguardRemote
from .gretap import gretap_up, gretap_down


@define(kw_only=True, slots=False, order=True, eq=True)
class MeshNode(NodeType):
    _mesh: MeshType | None = field(default=None, init=False, repr=False, eq=False, order=False)
    _config: WireguardConfig | None = field(default=None, init=False, repr=False, eq=False, order=False)

    @cached_property
    def remote(self) -> WireguardRemote:
        return WireguardRemote(
            connect=self.ssh,
            interface=f"wg-{self._mesh.name}{self.index}",
        )

    @property
    def mesh(self) -> MeshType:
        return self._mesh

    @property
    def config(self) -> WireguardConfig:
        return self._config

    @property
    def config_exists(self) -> bool:
        return self.remote.config_exists

    @property
    def wg_addr(self) -> Interface:
        """Wireguard address of the node.
        This address is only used to establish a GRE tunnel between mesh nodes, and is always a random IPv6/128 address.
        """
        return self._config.addresses[0]

    @property
    def peers(self) -> list[str]:
        return [peer.friendly_name for peer in self._config.peers.values()]

    @property
    def bridge_priority(self) -> int:
        prio = self.prio if self.prio is not None else -8 + (self.index - 1) % 16
        return 32768 + 4096 * prio

    # @property
    # def conf(self) -> dict:
    #     return super().conf | dict(
    #         address=str(self.network_addr.ip),
    #     )

    class Info(TypedDict):
        host: str
        is_up: bool
        config_exists: bool
        address: str
        peers: list[str]

    @property
    def info(self) -> Info:
        return self.Info(
            host=self.remote.host,
            is_up=self.remote.is_up,
            config_exists=self.remote.config_exists,
            address=str(self.addr.ip),
            peers=self.peers,
        )

    def __mesh_post_init__(self, mesh: MeshType):
        if self.network != mesh.network:
            raise ValueError(f"Node {self.name!r} address {self.addr} is not in the mesh network {mesh.network}")
        if mesh.nodes.get(self.name) is not self:
            raise ValueError(f"Node name {self.name!r} does not match mesh.nodes[{self.name!r}].")
        self._mesh = mesh
        self.__config_init()

    def __config_init(self):
        self._config = self.remote.config

        if self._config is not None:
            if self._config.listen_port != DEFAULT_PORT and self.listen_port is None:
                self.listen_port = self._config.listen_port

        else:
            self._config = WireguardConfig(
                private_key=WireguardKey.generate(),
                addresses=[RandomIPv6Interface()],
                listen_port=self.listen_port or DEFAULT_PORT,
            )

    def config_write(self):
        self.remote.config_write(self._config)

    def config_remove(self):
        self.remote.config_remove()

    def can_peer(self, other: "MeshNode") -> bool:
        """Check if this node can peer with another node.

        Uses the Wireguard UDP listen ports and endpoints to check if the nodes can peer,
        so this can only be reliable when Wireguard is not up on either node.
        """
        print(f"[{self}] [can_peer] {other}", file=sys.stderr)
        return (not self.remote.is_up and self.remote.udping_from(
            listen_port=self.listen_port or DEFAULT_PORT,
            endpoint_host=self.endpoint.host,
            endpoint_port=self.endpoint.port or DEFAULT_PORT,
            remote=other.remote,
        )) or (not other.remote.is_up and other.remote.udping_from(
            listen_port=other.listen_port or DEFAULT_PORT,
            endpoint_host=other.endpoint.host,
            endpoint_port=other.endpoint.port or DEFAULT_PORT,
            remote=self.remote,
        ))

    def as_peer(self, **kwds) -> WireguardPeer:
        return WireguardPeer(
            public_key=self._config.private_key.public_key(),
            allowed_ips=[self.wg_addr],
            endpoint_host=self.endpoint.host,
            endpoint_port=self.endpoint.port or DEFAULT_PORT,
            friendly_name=self.name,
            friendly_json=self.json,
            **kwds,
        )

    def peer_with(self, other: "MeshNode"):
        this_pubkey = self._config.private_key.public_key()
        that_pubkey = other._config.private_key.public_key()

        if this_pubkey == that_pubkey:
            raise ValueError("Cannot peer with self")

        if this_pubkey in other._config.peers and that_pubkey in self._config.peers:
            this_peer = other._config.peers[this_pubkey]
            that_peer = self._config.peers[that_pubkey]

            if this_peer.allowed_ips[0] != self.wg_addr or that_peer.allowed_ips[0] != other.wg_addr:
                raise ValueError("Existing peering WireGuard addresses do not match")

            # noinspection DuplicatedCode
            if not self.json and this_peer.friendly_json is not None:
                self.json = this_peer.friendly_json
            elif self.json and this_peer.friendly_json != self.json:
                this_peer.friendly_json = self.json

            if this_peer.friendly_name != self.name:
                this_peer.friendly_name = self.name

            # noinspection DuplicatedCode
            if not other.json and that_peer.friendly_json is not None:
                other.json = that_peer.friendly_json
            elif other.json and that_peer.friendly_json != other.json:
                that_peer.friendly_json = other.json

            if that_peer.friendly_name != other.name:
                that_peer.friendly_name = other.name

            return

        if not self._mesh.full and not self.can_peer(other):
            return

        preshared_key = WireguardKey(token_bytes(32))
        this_peer = self.as_peer(preshared_key=preshared_key)
        that_peer = other.as_peer(preshared_key=preshared_key)

        self._config.add_peer(that_peer)
        other._config.add_peer(this_peer)

        this_index = self.index
        that_index = other.index
        this_gretap_name = f"gt-{self._mesh.name}{that_index}"
        that_gretap_name = f"gt-{other._mesh.name}{this_index}"
        this_gretap_addr = self.wg_addr.ip
        that_gretap_addr = other.wg_addr.ip
        this_bridge_name = f"br-{self._mesh.name}"
        that_bridge_name = f"br-{other._mesh.name}"
        this_bridge_addr = self.addr
        that_bridge_addr = other.addr

        self._config.postup.extend(gretap_up(
            gretap_name=this_gretap_name,
            bridge_name=this_bridge_name,
            priority=self.bridge_priority,
            local=this_gretap_addr,
            remote=that_gretap_addr,
            bridge_addr=this_bridge_addr,
        ))

        other._config.postup.extend(gretap_up(
            gretap_name=that_gretap_name,
            bridge_name=that_bridge_name,
            priority=other.bridge_priority,
            local=that_gretap_addr,
            remote=this_gretap_addr,
            bridge_addr=that_bridge_addr,
        ))

        self._config.predown.extend(gretap_down(
            gretap_name=this_gretap_name,
            bridge_name=this_bridge_name,
        ))

        other._config.predown.extend(gretap_down(
            gretap_name=that_gretap_name,
            bridge_name=that_bridge_name,
        ))

    def up(self, *, write: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote

        if write or write is None and (write := not remote.config_exists) or (write := remote.config != self._config):
            try:
                remote.config_write(self._config)

            except Exception as exc:
                print(f"[{self}] [up] !! config_write failed: {exc}", file=sys.stderr)
                return False

        if remote.is_up:
            if not write:
                return True
            remote.down()

        if isinstance(up := remote.up(), RuntimeError):
            print(f"[{self}] [up] !! {remote.interface}:\n{up}", file=sys.stderr)
            if write:
                remote.config_remove()
            return False

        else:
            print(f"[{self}] [up] ++ {remote.interface}:\n{up}", file=sys.stderr)

        return True

    def down(self, *, remove: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote

        if remote.is_up:
            if isinstance(down := remote.down(), RuntimeError):
                print(f"[{self}] [down] !! {remote.interface}:\n{down}", file=sys.stderr)

                if not remote.is_up and remove:
                    remote.config_remove()
                return False

            else:
                print(f"[{self}] [down] -- {remote.interface}:\n{down}", file=sys.stderr)

        if remove or remove is None and remote.config_exists:
            remote.config_remove()

        return True

    def sync(self, *, up: bool | None = None) -> bool:
        remote: WireguardRemote = self.remote
        remote_config = remote.config

        if remote_config is None or remote_config != self._config:
            if up or up is None and remote.is_up:
                return self.up(write=True)

            remote.config_write(self._config)
            return True

        return False
