import dataclasses
from dataclasses import dataclass

from mira_edge.protocol import Packet, PacketFieldMetadata, PacketType

MIRA_PROTOCOL_VERSION = 2
MIRA_BROADCAST_ADDRESS = 0xFFFFFFFFFFFFFFFF
MIRA_NET_ID_DEFAULT = 0x0001


@dataclass
class HeaderStats(Packet):
    """Dataclass that holds MAC header stats."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="rssi", disp="rssi", length=1),
        ]
    )
    rssi: int = 0

    @property
    def rssi_dbm(self) -> int:
        if self.rssi > 127:
            return self.rssi - 255
        return self.rssi


@dataclass
class Header(Packet):
    """Dataclass that holds MAC header fields."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="version", disp="ver.", length=1),
            PacketFieldMetadata(name="type_", disp="type", length=1),
            PacketFieldMetadata(name="network_id", disp="net", length=2),
            PacketFieldMetadata(name="destination", disp="dst", length=8),
            PacketFieldMetadata(name="source", disp="src", length=8),
        ]
    )
    version: int = MIRA_PROTOCOL_VERSION
    type_: int = PacketType.DATA
    network_id: int = MIRA_NET_ID_DEFAULT
    destination: int = MIRA_BROADCAST_ADDRESS
    source: int = 0x0000000000000000

    def __repr__(self):
        type_ = PacketType(self.type_).name
        return f"Header(version={self.version}, type_={type_}, network_id=0x{self.network_id:04x}, destination=0x{self.destination:016x}, source=0x{self.source:016x})"


@dataclass
class Frame:
    """Data class that holds a payload packet."""

    header: Header = None
    stats: HeaderStats = dataclasses.field(default_factory=HeaderStats)
    payload: bytes = b""

    def from_bytes(self, bytes_):
        self.header = Header().from_bytes(bytes_[0:20])
        if len(bytes_) > 20:
            self.stats = HeaderStats().from_bytes(bytes_[20:21])
            if len(bytes_) > 21:
                self.payload = bytes_[21:]
        return self

    def to_bytes(self, byteorder="little") -> bytes:
        header_bytes = self.header.to_bytes(byteorder)
        stats_bytes = self.stats.to_bytes(byteorder)
        return header_bytes + stats_bytes + self.payload

    def __repr__(self):
        header_no_metadata = dataclasses.replace(self.header, metadata=[])
        return f"Frame(header={header_no_metadata}, payload={self.payload})"
