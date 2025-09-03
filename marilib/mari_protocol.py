import dataclasses
from dataclasses import dataclass
from enum import IntEnum

from marilib.protocol import Packet, PacketFieldMetadata, PacketType

MARI_PROTOCOL_VERSION = 2
MARI_BROADCAST_ADDRESS = 0xFFFFFFFFFFFFFFFF
MARI_NET_ID_DEFAULT = 0x0001


class DefaultPayloadType(IntEnum):
    APPLICATION_DATA = 1
    METRICS_REQUEST = 128
    METRICS_RESPONSE = 129
    METRICS_LOAD = 130

    def as_bytes(self) -> bytes:
        return bytes([self.value])


@dataclass
class DefaultPayload(Packet):
    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="type", length=1),
        ]
    )
    type_: DefaultPayloadType = DefaultPayloadType.APPLICATION_DATA


@dataclass
class MetricsRequestPayload(Packet):
    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="type", length=1),
            PacketFieldMetadata(name="timestamp_us", length=8),
        ]
    )
    type_: DefaultPayloadType = DefaultPayloadType.METRICS_REQUEST
    timestamp_us: int = 0


@dataclass
class MetricsResponsePayload(Packet):
    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="type", length=1),
            PacketFieldMetadata(name="timestamp_us", length=8),
            PacketFieldMetadata(name="rx_count", length=4),
            PacketFieldMetadata(name="tx_count", length=4),
        ]
    )
    type_: DefaultPayloadType = DefaultPayloadType.METRICS_RESPONSE
    timestamp_us: int = 0
    rx_count: int = 0
    tx_count: int = 0


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
    version: int = MARI_PROTOCOL_VERSION
    type_: int = PacketType.DATA
    network_id: int = MARI_NET_ID_DEFAULT
    destination: int = MARI_BROADCAST_ADDRESS
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

    @property
    def is_test_packet(self) -> bool:
        """Returns True if either the payload is a metrics response, request, or load test packet."""
        return self.payload.startswith(DefaultPayloadType.METRICS_RESPONSE.as_bytes()) or \
            self.payload.startswith(DefaultPayloadType.METRICS_REQUEST.as_bytes()) or \
            self.payload.startswith(DefaultPayloadType.METRICS_LOAD.as_bytes())

    @property
    def is_load_test_packet(self) -> bool:
        return self.payload.startswith(DefaultPayloadType.METRICS_LOAD.as_bytes())

    def __repr__(self):
        header_no_metadata = dataclasses.replace(self.header, metadata=[])
        return f"Frame(header={header_no_metadata}, payload={self.payload})"
