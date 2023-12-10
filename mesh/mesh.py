from itertools import combinations
from typing import TypedDict

from attrs import define, field

from .types import IPv4Network, IPv6Network, Network, RandomIPv6Address, MeshType, ip_network
from .node import MeshNode


@define(kw_only=True, slots=False, order=True, eq=True)
class Mesh(MeshType):
    nodes: dict[str, MeshNode] = field(converter=MeshNode.convert_all, factory=dict)

    @property
    def pairs(self):
        return combinations(self.nodes.values(), 2)

    @property
    def is_up(self) -> float:
        return sum(int(node.remote.is_up) for node in self.nodes.values()) / len(self.nodes)

    @property
    def config_exists(self) -> float:
        return sum(int(node.remote.config_exists) for node in self.nodes.values()) / len(self.nodes)

    class Info(TypedDict):
        name: str
        network: str
        is_up: float
        config_exists: float
        nodes: dict[str, MeshNode.Info]

    @property
    def info(self) -> Info:
        return self.Info(
            name=self.name,
            network=str(self.network),
            is_up=self.is_up,
            config_exists=self.config_exists,
            nodes={name: node.info for name, node in self.nodes.items()},
        )

    def __attrs_post_init__(self):
        for node in self.nodes.values():
            node.__mesh_post_init__(self)

    def __iter__(self):
        return iter(self.nodes)

    def __getitem__(self, name) -> MeshNode:
        return self.nodes[name]

    def __len__(self):
        return len(self.nodes)

    def __contains__(self, name):
        return name in self.nodes

    def config_write(self) -> None:
        [node.config_write() for node in self.nodes.values()]

    def config_remove(self) -> None:
        [node.config_remove() for node in self.nodes.values()]

    def peer_all(self) -> None:
        for node1, node2 in self.pairs:
            node1.peer_with(node2)

    def up(self, *, write: bool | None = None) -> bool | None:
        up_nodes = []

        if write is not False and any(not node.config_exists or not node.config.peers for node in self.nodes.values()):
            # Some nodes don't have configs or peers yet, so make sure all peer lists are up-to-date.
            for node1, node2 in self.pairs:
                node1.peer_with(node2)

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
            print(f"{node}\n{node.remote.show()}\n")
