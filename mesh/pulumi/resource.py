"""Mesh Dynamic Resource Provider.
"""
import traceback
from typing import Self

import pulumi
from pulumi import Input, Output, ResourceOptions
from pulumi.dynamic import Resource, ResourceProvider, CreateResult, DiffResult, CheckResult, CheckFailure

from mesh import Mesh

from .util import random_id

__all__ = "WireguardMesh", "MeshArgs", "MeshNodeArgs", "MeshInfo"

MeshInfo = Mesh.Info


@pulumi.input_type
class MeshNodeArgs:
    addr: Input[str]
    name: Input[str]
    ssh: Input[str]
    endpoint: Input[str]
    listen_port: Input[int] | None

    def __init__(self, **kwds):
        self.__dict__.update(kwds)

    @classmethod
    def convert(cls, value: dict | Self, *, key: str | None = None) -> Self:
        if isinstance(value, cls):
            return value

        if isinstance(value, dict):
            if key is not None:
                value.setdefault("name", key)
            return cls(**value)

        raise TypeError(f"Cannot convert {value!r} to {cls.__name__}")


@pulumi.input_type
class MeshArgs:
    name: Input[str]
    network: Input[str]
    full: Input[bool] | None
    nodes: Input[dict[str, MeshNodeArgs]]

    def __init__(self, **kwds):
        nodes = kwds.pop("nodes")
        self.__dict__.update(kwds)
        self.nodes = {name: MeshNodeArgs.convert(node, key=name) for name, node in nodes.items()}


class WireguardMesh(Resource):
    name: Output[str]
    network: Output[str]
    full: Output[bool] | None
    nodes: Output[dict[str, dict]]
    info: Output[dict]

    def __init__(self, name: str, props: MeshArgs, opts: ResourceOptions | None = None):
        super().__init__(MeshProvider(), name, dict(info=None, **vars(props)), opts)


class MeshProvider(ResourceProvider):
    @classmethod
    def from_props(cls, props: dict) -> Mesh:
        props = props.copy()
        props.pop("info", None)
        props.pop("__provider", None)
        return Mesh(**props)

    def check(self, old: dict, new: dict) -> CheckResult:
        failures = []

        # noinspection PyBroadException
        try:
            if new.get("name") is None:
                failures.append(CheckFailure("name", "required"))

            if new.get("network") is None:
                failures.append(CheckFailure("network", "required"))

            if (nodes := new.get("nodes")) is None:
                failures.append(CheckFailure("nodes", "required"))
            else:
                for name, node in nodes.items():  # type: str, dict

                    if node.get("addr") is None:
                        failures.append(CheckFailure(f"nodes.{name}.addr", "required"))
                    if (name_ := node.get("name")) is not None and name != name_:
                        failures.append(CheckFailure(f"nodes.{name}.name", "must match key"))
                    if node.get("ssh") is None:
                        failures.append(CheckFailure(f"nodes.{name}.ssh", "required"))
                    if node.get("endpoint") is None:
                        failures.append(CheckFailure(f"nodes.{name}.endpoint", "required"))

            Mesh(name=new["name"], network=new["network"], nodes=new["nodes"])

        except Exception:
            failures.append(CheckFailure(None, "\n" + traceback.format_exc()))  # type: ignore[arg-type]

        return CheckResult(inputs=new, failures=failures)

    def create(self, props: dict) -> CreateResult:
        mesh = self.from_props(props)

        try:
            mesh.peer_all()
            mesh.config_write()

            if not mesh.up(write=False):
                raise RuntimeError("Failed to bring up mesh")

            info = mesh.info
            outs = mesh.asdict(serializer=lambda _, __, v: str(v) if not isinstance(v, int) else v)

        except Exception:
            mesh.down(remove=True)
            raise

        return CreateResult(
            f"mesh-{random_id()}",
            dict(info=info, **outs),
        )

    def diff(self, rid: str, old: dict, new: dict) -> DiffResult:
        replaces = []

        if old["name"] != new["name"]:
            replaces.append("name")

        if old["network"] != new["network"]:
            replaces.append("network")

        if old.get("full") != new.get("full"):
            replaces.append("full")

        if old["nodes"] != new["nodes"]:
            replaces.append("nodes")

        return DiffResult(
            changes=bool(replaces),
            replaces=replaces,
            stables=None,
            delete_before_replace=True,
        )

    def delete(self, rid: str, props: dict) -> None:
        mesh = self.from_props(props)
        mesh.down(remove=True)
