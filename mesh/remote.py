"""Wireguard remote controller.
"""
from functools import cached_property
from io import StringIO
from time import sleep

from attrs import define
from fabric import Connection
from invoke import Promise
from wireguard_tools import WireguardConfig

__all__ = "Remote", "WireguardRemote",


@define(slots=False)
class Remote:
    connect: str | dict
    """SSH connection string or arguments to the node."""

    @property
    def host(self):
        return self.connect if isinstance(self.connect, str) else self.connect["host"]

    @cached_property
    def _connection(self) -> Connection:
        return Connection(**(
            self.connect if isinstance(self.connect, dict) else dict(host=self.connect)
        ))

    @cached_property
    def _is_root(self) -> bool:
        return self._connection.user == "root"

    def _run(self, command: str, *, root: bool = True, **kwds):
        kwds.setdefault("hide", True)
        kwds.setdefault("warn", True)
        return self._connection.run(
            f"sudo {command.lstrip()}" if root and not self._is_root else command,
            **kwds
        )

    def udping_send(self, host: str, port: int, data: str = "1") -> bool:
        return self._run(
            f"echo -n {data!r} > /dev/udp/{host}/{port}",
            root=False,
        ).ok

    def udping_recv(self, port: int, timeout: float = 1.0) -> Promise:
        return self._run(
            f"timeout {timeout} nc -u -l -W 1 0 {port}",
            asynchronous=True,
        )

    def udping_from(self, listen_port: int, endpoint_host: str, endpoint_port: int, remote: "Remote") -> bool:
        """Send UDP ping from another remote to an endpoint mapping to this remote.
        """
        data = "1"
        promise = self.udping_recv(listen_port)
        sleep(0.1)
        remote.udping_send(endpoint_host, endpoint_port, data=data)
        result = promise.join()
        return result.ok

    def udping_to(self, listen_port: int, endpoint_host: str, endpoint_port: int, remote: "Remote") -> bool:
        return remote.udping_from(listen_port, endpoint_host, endpoint_port, self)


@define
class WireguardRemote(Remote):
    """Wireguard remote controller.
    """
    interface: str

    @property
    def config(self) -> WireguardConfig | None:
        return WireguardConfig.from_wgconfig(StringIO(config_text)) if (config_text := self.config_text) is not None else None

    @property
    def config_text(self) -> str | None:
        if (command := self._run(f"cat /etc/wireguard/{self.interface}.conf")).ok:
            return command.stdout.strip()
        return None

    def config_write(self, config: str | WireguardConfig, *, warn: bool = False) -> None:
        if isinstance(config, WireguardConfig):
            config = config.to_wgconfig(wgquick_format=True)
        if self._is_root:
            self._run(f"cat > /etc/wireguard/{self.interface}.conf <<EOF\n{config.strip()}\nEOF", root=False, warn=warn)
        else:
            self._run(
                f"cat <<EOF | sudo tee /etc/wireguard/{self.interface}.conf >/dev/null\n{config.strip()}\nEOF",
                root=False,
                warn=warn,
            )

    def config_remove(self) -> None:
        if self.is_up:
            raise RuntimeError(f"[{self.connect}] Cannot remove config while {self.interface} is up")
        self._run(f"rm -f /etc/wireguard/{self.interface}.conf")

    @property
    def config_exists(self) -> bool:
        return self._run(f"test -f /etc/wireguard/{self.interface}.conf").ok

    @property
    def is_up(self) -> bool:
        return self._run(f"wg show {self.interface}").ok

    def up(self) -> str | RuntimeError:
        cmd = self._run(f"wg-quick up {self.interface} 2>&1")
        return cmd.stdout.strip() if cmd.ok else RuntimeError(cmd.stdout.strip())

    def down(self) -> str | RuntimeError:
        cmd = self._run(f"wg-quick down {self.interface} 2>&1")
        return cmd.stdout.strip() if cmd.ok else RuntimeError(cmd.stdout.strip())

    def restart(self) -> str | RuntimeError:
        cmd = self._run(f"wg-quick down {self.interface} 2>&1 && wg-quick up {self.interface} 2>&1")
        return cmd.stdout.strip() if cmd.ok else RuntimeError(cmd.stdout.strip())

    def show(self) -> str | RuntimeError:
        cmd = self._run(f"wg show {self.interface} 2>&1")
        return cmd.stdout.strip() if cmd.ok else RuntimeError(cmd.stdout.strip())
