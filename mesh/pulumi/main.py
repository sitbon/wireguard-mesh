import os
from pathlib import Path

import pulumi
import yaml

from mesh.pulumi.resource import WireguardMesh, MeshArgs


def main():
    base_dir = Path(__file__).absolute().parent.parent.parent

    mesh_id = os.environ.get("PULUMI_MESH_ID", "mesh")
    mesh_file = Path(os.environ.get("PULUMI_MESH_FILE", "mesh.yaml"))

    with (base_dir / mesh_file).open() as f:
        mesh = WireguardMesh(mesh_id, MeshArgs(**yaml.safe_load(f)))
        pulumi.export(f"{mesh_id}:info", mesh.info)
        pulumi.export(f"{mesh_id}:nodes", mesh.nodes)


if __name__ == "__main__":
    main()
