"""Optional LAN peer discovery via multicast DNS (zeroconf).

Discovery only finds candidates on the local network; connecting still requires
the normal call-sign handshake and explicit user approval.
"""

import logging
import socket
import time

logger = logging.getLogger(__name__)

SERVICE = "_kairos._tcp.local."


def _first_addr(info):
    try:
        addrs = info.parsed_addresses()
        return addrs[0] if addrs else ""
    except Exception:
        return ""


class Discovery:
    """Advertise this peer and browse for others on the LAN."""

    def __init__(self):
        self.zc = None
        self.info = None

    def advertise(self, label: str, ip: str, port: int, fp: str, transport: str = "direct"):
        try:
            from zeroconf import ServiceInfo, Zeroconf
            self.zc = Zeroconf()
            self.info = ServiceInfo(
                SERVICE,
                f"{label}.{SERVICE}",
                addresses=[socket.inet_aton(ip)],
                port=int(port),
                properties={"fp": fp[:32], "transport": transport},
            )
            self.zc.register_service(self.info)
        except Exception:
            logger.exception("Discovery advertise failed")

    def discover(self, timeout: float = 4.0):
        found = {}
        zc = None
        try:
            from zeroconf import ServiceBrowser, Zeroconf

            class _Listener:
                def add_service(self, zc, type_, name):
                    try:
                        info = zc.get_service_info(type_, name)
                        if not info:
                            return
                        props = info.properties or {}
                        found[name] = {
                            "name": name.split(".")[0],
                            "host": _first_addr(info),
                            "port": info.port,
                            "fp": (props.get(b"fp") or b"").decode("ascii", "ignore"),
                            "transport": (props.get(b"transport") or b"direct").decode("ascii", "ignore"),
                        }
                    except Exception:
                        pass

                def update_service(self, *a):
                    pass

                def remove_service(self, *a):
                    pass

            zc = Zeroconf()
            ServiceBrowser(zc, SERVICE, _Listener())
            time.sleep(timeout)
        except Exception:
            logger.exception("Discovery browse failed")
        finally:
            if zc:
                try:
                    zc.close()
                except Exception:
                    pass
        return list(found.values())

    def close(self):
        try:
            if self.zc and self.info:
                self.zc.unregister_service(self.info)
            if self.zc:
                self.zc.close()
        except Exception:
            pass
        self.zc = None
        self.info = None