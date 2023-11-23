"""Wireguard mesh network manager.
"""
import argparse
import json
import os
import sys

import yaml

from . import Mesh


def main():
    parser = argparse.ArgumentParser(prog="mesh", description=__doc__)
    parser.set_defaults(func=lambda _: parser.print_help())
    parser.add_argument(
        "-j", "--json", action="store_true", default=None,
        help="Input JSON instead of YAML (default: use file ext).",
    )
    parser.add_argument(
        "-J", "--json-out",
        action="store_true", default=False,
        help="Output JSON instead of YAML."
    )
    parser.add_argument(
        "-f", "--file", type=argparse.FileType("r"), default="mesh.yaml",
        help="Mesh configuration file or - for stdin (default: mesh.yaml).",
    )
    parser.add_argument("-q", "--quiet", action="store_true", default=False, help="Suppress output.")

    subparsers = parser.add_subparsers(title="commands", metavar="COMMAND", help="Command:", required=True)

    up_parser = subparsers.add_parser("up", help="- Bring up mesh.")
    up_parser.add_argument("-i", "--info", action="store_true", default=False, help="Show mesh info after bringing up.")
    up_parser.set_defaults(func=_up)
    down_parser = subparsers.add_parser("down", help="- Bring down mesh.")
    down_parser.add_argument(
        "-r", "--remove", action="store_true", default=False, help="Remove Wireguard interface configs."
    )
    down_parser.set_defaults(func=_down)
    sync_parser = subparsers.add_parser("sync", help="- Sync mesh.")
    sync_parser.set_defaults(func=_sync)
    show_parser = subparsers.add_parser("show", help="- Show mesh Wireguard info.")
    show_parser.set_defaults(func=_show)
    info_parser = subparsers.add_parser("info", help="- Show mesh network info.")
    info_parser.set_defaults(func=_info)

    args = parser.parse_args()

    if args.quiet:
        sys.stderr = open(os.devnull, "w")

    mesh_dict = (
        yaml.safe_load(args.file)
        if not args.json or args.json is None and (
                args.file.name.endswith(".yaml") or args.file.name.endswith(".yml")
        ) else
        json.load(args.file)
    )

    mesh = Mesh(**mesh_dict)

    exit(args.func(mesh, args) or 0)


def _up(mesh: Mesh, args: argparse.Namespace):
    if up := mesh.up():
        if args.info:
            return _info(mesh, args)

    return int(not up)


def _down(mesh: Mesh, args: argparse.Namespace):
    return int(not mesh.down(remove=args.remove))


def _sync(mesh: Mesh, args: argparse.Namespace):
    return int(not mesh.sync())


def _show(mesh: Mesh, args: argparse.Namespace):
    mesh.show()
    return 0


def _info(mesh: Mesh, args: argparse.Namespace):
    print(yaml.dump(mesh.info, sort_keys=False) if not args.json_out else json.dumps(mesh.info, indent=4))
    return 0


main()
