# Automatic L2 Wireguard Mesh Deployment

This is a small and opinionated tool that assists with the bring-up and
management of L2-bridged Wireguard mesh networks using only SSH.
It is intended to be used within IaC systems, CI pipelines, or other
automation sources able to provide state management & idempotent deployments.

Personally, I've developed this package for use with Pulumi and RKE to create my infrastructure network,
which spans across two LANs and multiple (Linode) cloud nodes.

I wanted to minimize configuration requirements to the bare minimum, so the only thing needed to get a 
mesh going with this tool is a `mesh.yaml` file defining the network, nodes, and SSH connection parameters.

Otherwise, users are only expected to pre-configure SSH connectivity and any necessary NAT UDP ports mappings for Wireguard.

## Features
- Fully-connected topology or reachability-based peering.
- SSH-based peer configuration.
  - Automatic public, private and pre-shared key generation.
  - The configuring node only needs remote root/sudo access, and does not store private keys or any additional state.
- Peerwise `gretap`/`ip6gretap` L2 links over Wireguard.
- `iproute2`-based bridging with STP enabled.

### Non-Features
What this doesn't do:
- Dynamically add/remove nodes or rotate keys without bringing down the mesh.
- Configure IP forwarding, Internet routing, or DNS.
- Support clients, gateways/egress/ingress, or anything other than a fully- or mostly-connected mesh of servers.

## How It Works

Because Wireguard doesn't support L2 or have the ability to route the same subnet across AllowedIPs for multiple peers,
creating a fully connected mesh at L2 requires a GRE tunnel to each peer, and a bridge for all peer tunnels on each node.
```
+-------------------------+  +-------------------------+
| node1:                  |  | nodeN:                  |
| +-------------+         |  |         +-------------+ |
| | bridge      |         |  |         | bridge      | |
| | +---------+ |  +----+ |  | +----+  | +---------+ | |
| | | gretap1 |<-->|    | |  | |    |<-->| gretap1 | | |
| | +---------+ |  |    | |  | |    |  | +---------+ | |
| |   ...       |  | wg |<---->| wg |  |   ...       | |
| | +---------+ |  |    | |  | |    |  | +---------+ | |
| | | gretapN |<-->|    | |  | |    |<-->| gretapN | | |
| | +---------+ |  +----+ |  | +----+  | +---------+ | |
| +-------------+         |  |         +-------------+ |
+-------------------------+  +-------------------------+
               \                         /
                \--------- ssh ---------/
                            |
                +----------------------+
                | wireguard-mesh host  |
                +----------------------+
```
In this diagram, the bridge on each node has an assigned IP address within the defined network, and
STP prevents routing loops and advertisement floods that would otherwise be caused by multiple redundant links.
The Wireguard peer addresses are randomly chosen by default and only used for GRE tunneling.

### Example `mesh.yaml`
Configuration files can also be provided from `stdin`, and JSON-formatting is available with the `-j` flag.

```yaml
name: test
network: fd00:0:0:1::/64
nodes:
  0:
    ssh: test0
    wg: lan1.example.com
  1:
    ssh: test1
    wg: lan1.example.com:51821
  2:
    ssh: test2
    wg: lan2.example.com
  3:
    ssh: test3
    wg: test3.cloud.example.com
```

Nodes are assigned bridge network addresses from the mesh subnet based on their index, for example
`fd00:0:0:1::1` for `test0` above.

# Usage
(TODO)

## System Requirements
Before deploying, the following is expected:
- This package is installed on the configuring host.
- Root or sudo access is available via SSH on all nodes.
  - Typically defined as entries in `~/.ssh/config`.
  - Specified by a host/connection string or keyword argument dictionary for [`fabric.Connection`](https://docs.fabfile.org/en/latest/api/connection.html).
- Wireguard and `wg-quick` from `wireguard-tools` are installed on all nodes.
- `iproute2`: `ip6gretap` and `bridge` capability
- Optional: `netcat` and shell `/dev/udp` capability for reachability testing.

### Network/Firewall:
This tool assumes that we have:
  - SSH accessibility from the configuring host to every node
  - Wireguard Endpoint UDP NAT ports mapped to LAN nodes

## Notes

A _static_ mesh is defined here as a configuration that does not change between creation and
deletion. This tool is capable of discerning the mesh state from the configuration
and has some ability to handle new peers, but deconfiguring/removing peers will leave dangling configuration files.

Hence, the recommended method to handle mesh changes is to perform a full replacement:
bring down the mesh from the existing configuration, and recreate from the new
configuration. This has the side-effect of generating all new private and pre-shared keys as well.

### Scalability

For a mesh of `N` fully-connected nodes, each node requires one Wireguard server with `N-1` peers,
`N-1` GRE tunnels, and one bridge interface for the tunnels. 

Considerations:
- STP will likely be very slow to learn/adapt with large `N` if links change state frequently.
- Kernel limitiations might prevent a large number of `ip6gretap` links?

### Security

Every Wireguard peering is automatically assigned a preshared key when the mesh is created, and each node's
private keys are automatically generated as well.

Keys are never saved anywhere other than each nodes `/etc/wireguard/` config, and only loaded into memory when working
with meshes that were previously configured.

However, access to all keys is necessarily possible via SSH when configured for this tool,
so users should take care to properly protect SSH identities within production environments.

## Reference

### Articles
- [Wireguard L2 gist](https://gist.github.com/zOrg1331/a2a7ffb3cfe3b3b821d45d6af00cb8f6)
- [Comparison of Wireguard mesh tools](https://github.com/HarvsG/WireGuardMeshes)


### Tools & Libraries
- [`wireguard-tools`](https://github.com/cmusatyalab/wireguard-tools)
  - Python library used here for configuration management.
  - Netlink-capable: Useful for development of active Wireguard management solutions.
- [`wg-meshconf`](https://github.com/k4yt3x/wg-meshconf)
  - (Python) CSV-based mesh management. 
