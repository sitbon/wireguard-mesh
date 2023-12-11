# Automatic L2 Wireguard Mesh Deployment

This is a small and opinionated tool that assists with the bring-up and
management of L2-bridged Wireguard mesh networks using only SSH.
It is intended to be used within IaC systems, CI pipelines, or other
automation sources able to provide state management & idempotent deployments.

Personally, I've developed this package for use with Pulumi and RKE to create my infrastructure network,
which spans across two LANs and multiple (Linode) cloud nodes.

I wanted to minimize configuration requirements to the bare minimum, so the only thing needed to get a 
mesh going with this tool is a `mesh.yaml` file defining a minimal set of parameters for each node.

Otherwise, users are only expected to pre-configure SSH connectivity and any necessary NAT UDP ports mappings for Wireguard.

## Features
- Fully-connected topology or user-defined peering.
- SSH-based peer configuration.
  - Automatic public, private and pre-shared key generation.
  - The configuring node only needs remote root/sudo access, and does not store private keys or any additional state.
- Peerwise `gretap`/`ip6gretap` L2 links over Wireguard.
- `iproute2`-based bridging with STP enabled and configurable priorities.

### Non-Features
What this doesn't do:
- Dynamically add/remove nodes or rotate keys without bringing down the mesh.
- Configure IP forwarding, Internet routing, or DNS.
- Support clients, gateways/egress/ingress, or anything other than a fully- or mostly-connected mesh of servers.

### TODO

- [ ] Add `--dry-run` flag to preview changes.
- [ ] Add more accessibility to Wireguard config options.
- [ ] Support some method of manual insecure interface bridging, e.g. for VPCs/VLANs.

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
full: false  # Optional: default is true. Set to false for manual peering.
nodes:
  mesh0:
    addr: fd00:0:0:1::1/64
    ssh: test0
    endpoint: lan1.example.com
    peers:  # When unset or empty and full=false, all other nodes are peered.
      - mesh1
      - mesh2
      - mesh3
  mesh1:
    addr: fd00:0:0:1::2/64
    ssh: test1
    endpoint: lan1.example.com:51821
  mesh2:
    addr: fd00:0:0:1::3/64
    ssh: test2
    endpoint: lan2.example.com
    listen_port: 51850
  mesh3:
    addr: fd00:0:0:1::4/64
    ssh: test3
    endpoint: test3.cloud.example.com
    prio: 100
```

Prior versions supported auto-assignment of addresses, but this has been removed in favor of explicit configuration.

Each node's `addr` field must be a unique interface address within the network.

# Usage

Create a `mesh.yaml` as shown above, and then run:
```shell
mesh up
```

Show mesh info:
```shell
mesh info
```

Bring down the mesh and remove configs:
```shell
mesh down -r
```

### Full Usage
```commandline
usage: mesh [-h] [-j] [-J] [-f FILE] [-q] COMMAND ...

Wireguard mesh network manager.

options:
  -h, --help            show this help message and exit
  -j, --json            Input JSON instead of YAML (default: use file ext).
  -J, --json-out        Output JSON instead of YAML.
  -f FILE, --file FILE  Mesh configuration file or - for stdin (default: mesh.yaml).
  -q, --quiet           Suppress output.

commands:
  COMMAND               Command:
    up                  - Bring up mesh.
    down                - Bring down mesh.
    sync                - Sync mesh.
    show                - Show mesh Wireguard info.
    info                - Show mesh network info.
    
-------------------------------
usage: mesh up [-h] [-i]

options:
  -h, --help  show this help message and exit
  -i, --info  Show mesh info after bringing up.
  
-------------------------------
usage: mesh down [-h] [-r]

options:
  -h, --help    show this help message and exit
  -r, --remove  Remove Wireguard interface configs.
```

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
configuration. This has the side effect of generating all new private and pre-shared keys as well.

### Scalability

For a mesh of `N` fully-connected nodes, each node requires one Wireguard server with `N-1` peers,
`N-1` GRE tunnels, and one bridge interface for the tunnels. 

#### Considerations:
- STP will likely be very slow to learn/adapt with large `N` if links change state frequently.
  - Sometimes, STP doesn't find the best path between LAN-local nodes and ends up
    adding unnecessary multi-hop latency, even with only 3 nodes.
    - The newly added `prio` node field allows setting of bridge priorities. Defaults are mapped to node indices, which lessens
      the likelihood of arbitrarily bad routing decisions by ensuring that the 0-indexed node is the most likely root node (out of every 16).
  - There are better dynamic routing options, but STP is the simplest to enable.
- Kernel limitations might prevent a large number of `ip6gretap` links?

#### Performance:
- Links take a slight MTU hit for the GRE tunnels, on top of Wireguard's 80 bytes.
- Latency differences in ping times were under 500 microseconds on average,
  when comparing the same LAN vs meshed-over-LAN links.
  - LAN-local peers can sometimes find local endpoints for clients, even when the original endpoints
    referred to the same NAT gateway.
  - STP can't provide any minimum latency or best-path guarantees.
- `iperf` measurements TBD.

### Security

Every Wireguard peering is automatically assigned a preshared key when the mesh is created, and each node's
private keys are automatically generated as well.

Keys are never saved anywhere other than each nodes `/etc/wireguard/` config, and only loaded into memory when working
with meshes that were previously configured.

However, access to all keys is necessarily possible via SSH when configured for this tool,
so SSH identities should be properly protected within production environments.

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
