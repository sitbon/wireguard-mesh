"""Mesh Dynamic Resource Provider.
"""
from typing import Any

from pulumi import Input, Output, ResourceOptions, export
from pulumi.dynamic import Resource, ResourceProvider, CreateResult, DiffResult, CheckResult, CheckFailure

from attrs import AttrsInstance, define, field, asdict

from mesh import Mesh as WireguardMesh
from mesh.types import RandomIPv6Address

from .util import random_id

__all__ = "Mesh", "MeshArgs", "MeshNodeArgs",


@define(kw_only=True, slots=False)
class MeshNodeArgs(AttrsInstance):
    idx: Input[int | str] = field(converter=lambda x: str(int(x)))
    ssh: Input[str]
    wg: Input[str]
    port: Input[int | str] = field(default="51820", converter=lambda x: str(int(x)))


@define(kw_only=True, slots=False)
class MeshArgs(AttrsInstance):
    name: Input[str]
    network: Input[str]
    full: Input[bool] = True
    nodes: Input[list[MeshNodeArgs]] = field(
        converter=lambda x: [
            v if isinstance(v, MeshNodeArgs) else MeshNodeArgs(**v)
            for v in x
        ],
    )


class MeshProvider(ResourceProvider):

    def check(self, _olds: dict | None, news: dict) -> CheckResult:
        print("check", _olds, news)
        failures = []

        if (name := news.get("name")) is None:
            failures.append(CheckFailure("name", "required"))

        if (network := news.get("network")) is None:
            failures.append(CheckFailure("network", "required"))

        if (nodes := news.get("nodes")) is None:
            failures.append(CheckFailure("nodes", "required"))

        if not failures:
            try:
                new_mesh = WireguardMesh(name=name, network=network, nodes=nodes)

                if _olds:
                    Mesh._check_map(Mesh._from_outputs(_olds), new_mesh)

                news = Mesh._outputs(new_mesh)

            except Exception as e:
                failures.append(CheckFailure("<validation>", str(e)))

        return CheckResult(inputs=news, failures=failures)

    def create(self, props: dict) -> CreateResult:
        mesh = Mesh._from_outputs(props)

        if not mesh.up():
            mesh.down(remove=True)
            raise RuntimeError("Failed to bring up mesh")

        return CreateResult(f"mesh-{random_id()}", Mesh._outputs(mesh, creating=True))

    def diff(self, _id: str, _olds: dict, _news: dict) -> DiffResult:
        replaces = []

        olds_mesh = Mesh._from_outputs(_olds)
        news_mesh = Mesh._from_outputs(_news)
        Mesh._check_map(olds_mesh, news_mesh)
        news_outs = Mesh._outputs(news_mesh)

        if _olds["conf"] != news_outs["conf"]:
            replaces.append("conf")

        return DiffResult(
            changes=bool(replaces),
            replaces=replaces,
            stables=None,
            delete_before_replace=True,
        )

    def delete(self, _id: str, _props: dict) -> None:
        mesh = Mesh._from_outputs(_props)
        mesh.down(remove=True)


class Mesh(Resource):
    conf: Output[dict[str, Any]]
    info: Output[dict[str, Any]]

    def __init__(self, name: str, props: MeshArgs, opts: ResourceOptions | None = None):
        outputs = dict(conf=None, info=None)
        super().__init__(MeshProvider(), name, outputs | asdict(props), opts)

    @classmethod
    def _outputs(cls, mesh: WireguardMesh, *, creating: bool = False) -> dict[str, Any]:
        info = mesh.info
        info["nodes"] = [dict(idx=idx, **node) for idx, node in info["nodes"].items()]

        return dict(
            conf=mesh.conf,
            **(dict(info=info) if creating else {}),
        )

    @classmethod
    def _from_outputs(cls, outputs: dict[str, Any]) -> WireguardMesh:
        return WireguardMesh(**outputs["conf"])

    @classmethod
    def _check_map(cls, old: WireguardMesh, new: WireguardMesh) -> None:
        for new_node in new.nodes:
            if (old_node := old.node(new_node.idx)) is not None:
                if isinstance(new_node, RandomIPv6Address):
                    new_node.addr = old_node.addr

    @property
    def exports(self) -> dict:
        return {
            f"{self._name}:conf": self.conf,
            f"{self._name}:info": self.info,
        }

    def export(self):
        for k, v in self.exports.items():
            export(k, v)
