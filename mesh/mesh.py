from itertools import combinations

from attrs import define, field

from .types import IPv4Network, IPv6Network, Network, RandomIPv6Address, NodeType, ip_network
from .node import MeshNode


@define(kw_only=True)
class Mesh:
    name: str

    nodes: list[NodeType | MeshNode] = field(
        converter=lambda nodes_: [
            NodeType(**node) if not isinstance(node, NodeType) else node
            for node in nodes_
        ],
    )

    network: Network = field(
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
        return combinations(self.nodes, 2)

    @property
    def is_up(self) -> float:
        return sum(int(node.remote.is_up) for node in self.nodes) / len(self.nodes)

    @property
    def config_exists(self) -> float:
        return sum(int(node.remote.config_exists) for node in self.nodes) / len(self.nodes)

    @property
    def info(self) -> dict:
        return dict(
            name=self.name,
            network=str(self.network),
            is_up=self.is_up,
            config_exists=self.config_exists,
            nodes={node.idx: node.info for node in self.nodes},
        )

    @property
    def conf(self) -> dict:
        """Dictionary suitable for serialization."""
        return dict(
            name=self.name,
            network=str(self.network),
            **(dict(full=False) if not self.full else {}),
            nodes=[node.conf for node in self.nodes],
        )

    def __attrs_post_init__(self):
        self.nodes = [
            MeshNode.from_node(self, node) if not isinstance(node, MeshNode) else node
            for node in self.nodes
        ]

    def __iter__(self):
        return iter(self.nodes)

    def __getitem__(self, item) -> MeshNode:
        for node in self.nodes:
            if node.idx == item:
                return node
        raise KeyError(item)

    def __len__(self):
        return len(self.nodes)

    def __contains__(self, item):
        return any(node.idx == item for node in self.nodes)

    def node(self, idx: int) -> MeshNode | None:
        try:
            return self[idx]
        except KeyError:
            return None

    def config_write(self) -> None:
        [node.config_write() for node in self.nodes]

    def config_remove(self) -> None:
        [node.config_remove() for node in self.nodes]

    def up(self, *, write: bool | None = None) -> bool | None:
        up_nodes = []

        if any(isinstance(node.addr, RandomIPv6Address) or not node.config.peers for node in self.nodes):
            # Some nodes don't have addresses or peers yet, so make sure all peer lists are up-to-date.
            for node1, node2 in self.pairs:
                node1.peer_with(node2)

        for node in self.nodes:
            if node.up(write=write):
                up_nodes.append(node)
            else:
                for up_node in up_nodes:
                    up_node.down(remove=write)
                return False

        return None if not up_nodes else True

    def down(self, *, remove: bool | None = None) -> bool:
        return all(node.down(remove=remove) for node in self.nodes)

    def sync(self, *, up: bool | None = None) -> bool:
        return all(node.sync(up=up) for node in self.nodes)

    def show(self) -> None:
        for node in self.nodes:
            print(f"[{node.tag}]\n{node.remote.show()}\n")
