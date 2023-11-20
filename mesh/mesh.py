from itertools import combinations
from ipaddress import IPv6Address, IPv4Network, IPv6Network, ip_network

from attrs import define, field
from attrs.setters import convert

from .types import BaseNode
from .node import MeshNode


@define(kw_only=True, on_setattr=convert)
class Mesh:
    name: str

    nodes: dict[int, MeshNode] = field(
        converter=lambda nodes_: {
            int(index): BaseNode(**node) if not isinstance(node, BaseNode) else node
            for index, node in nodes_.items()
        },
    )

    network: IPv4Network | IPv6Address = field(
        converter=lambda x: ip_network(x) if not isinstance(x, (IPv4Network, IPv6Network)) else x,
    )
    """Mesh network address.
    
    This network will be routed among all node bridges in the mesh.
    """

    full: bool = True
    """Peer all node pairs regardless of reachability.
    
    When False, checks whether two nodes can reach each other before connecting them.
    """

    @property
    def pairs(self):
        return combinations(self.nodes.values(), 2)

    @property
    def is_up(self) -> float:
        return sum(int(node.remote.is_up) for node in self.nodes.values()) / len(self.nodes)

    @property
    def config_exists(self) -> float:
        return sum(int(node.remote.config_exists) for node in self.nodes.values()) / len(self.nodes)

    @property
    def info(self) -> dict:
        return dict(
            name=self.name,
            network=str(self.network),
            is_up=self.is_up,
            config_exists=self.config_exists,
            nodes={index: node.info for index, node in self.nodes.items()},
        )

    def __attrs_post_init__(self):
        for index, node in self.nodes.items():
            self.nodes[index] = MeshNode.from_node(self, index, node) if not isinstance(node, MeshNode) else node

        for node1, node2 in self.pairs:
            node1.peer_with(node2)

    def __iter__(self):
        return iter(self.nodes)

    def __getitem__(self, item):
        return self.nodes[item]

    def __len__(self):
        return len(self.nodes)

    def config_write(self) -> None:
        for node in self.nodes.values():
            node.remote.config_write(node.config)

    def config_remove(self) -> None:
        for node in self.nodes.values():
            node.remote.config_remove()

    def up(self, *, write: bool | None = None) -> bool | None:
        up_nodes = []

        for node in self.nodes.values():
            if node.up(write=write):
                up_nodes.append(node)
            else:
                for up_node in up_nodes:
                    up_node.down(remove=write)
                return False

        return None if not up_nodes else True

    def down(self, *, remove: bool | None = None) -> bool:
        return all(node.down(remove=remove) for node in self.nodes.values())

    def sync(self, *, up: bool | None = None) -> bool:
        return all(node.sync(up=up) for node in self.nodes.values())

    def show(self) -> None:
        for node in self.nodes.values():
            print(f"[{node.tag}]\n{node.remote.show()}\n")
