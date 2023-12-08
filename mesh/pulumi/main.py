import os
from pathlib import Path

import yaml

from mesh.pulumi.provider import Mesh, MeshArgs


def main():
    base_dir = Path(__file__).absolute().parent.parent.parent

    mesh_id = os.environ.get("PULUMI_MESH_ID", "mesh")
    mesh_file = Path(os.environ.get("PULUMI_MESH_FILE", "mesh.yaml"))

    with (base_dir / mesh_file).open() as f:
        Mesh(mesh_id, MeshArgs(**yaml.safe_load(f))).export()


if __name__ == "__main__":
    main()
