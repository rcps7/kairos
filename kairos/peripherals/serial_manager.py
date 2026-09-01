import serial
import serial.tools.list_ports
from typing import List, Dict, Optional


class SerialManager:
    def __init__(self, default_baud: int = 115200):
        self.default_baud = default_baud
        self.connections: Dict[str, serial.Serial] = {}

    def list_ports(self) -> List[Dict[str, str]]:
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append({
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "open": p.device in self.connections,
            })
        return ports

    def open(self, device: str, baudrate: Optional[int] = None) -> None:
        if device in self.connections:
            return
        baud = baudrate or self.default_baud
        ser = serial.Serial(port=device, baudrate=baud, timeout=1)
        self.connections[device] = ser

    def close(self, device: str) -> None:
        ser = self.connections.pop(device, None)
        if ser:
            ser.close()

    def close_all(self) -> None:
        for ser in self.connections.values():
            try:
                ser.close()
            except Exception:
                pass
        self.connections.clear()

    def write(self, device: str, data: bytes) -> int:
        ser = self.connections.get(device)
        if not ser:
            raise RuntimeError(f"Port {device} not open")
        return ser.write(data)

    def write_text(self, device: str, text: str) -> int:
        return self.write(device, text.encode("utf-8", errors="ignore"))

    def read(self, device: str, size: int = 1024) -> bytes:
        ser = self.connections.get(device)
        if not ser:
            raise RuntimeError(f"Port {device} not open")
        return ser.read(size)

    def read_line(self, device: str) -> str:
        ser = self.connections.get(device)
        if not ser:
            raise RuntimeError(f"Port {device} not open")
        line = ser.readline()
        return line.decode("utf-8", errors="ignore").rstrip()

    def read_text(self, device: str, size: int = 1024) -> str:
        return self.read(device, size).decode("utf-8", errors="ignore")
