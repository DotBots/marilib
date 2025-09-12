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
    METRICS_PROBE = 140

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
class MetricsProbePayload(Packet):
    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="type", length=1),
            PacketFieldMetadata(name="cloud_tx_ts_us", length=8),
            PacketFieldMetadata(name="cloud_rx_ts_us", length=8),
            PacketFieldMetadata(name="cloud_tx_count", length=4),
            PacketFieldMetadata(name="cloud_rx_count", length=4),
            PacketFieldMetadata(name="edge_tx_ts_us", length=8),
            PacketFieldMetadata(name="edge_rx_ts_us", length=8),
            PacketFieldMetadata(name="edge_tx_count", length=4),
            PacketFieldMetadata(name="edge_rx_count", length=4),
            PacketFieldMetadata(name="gw_tx_count", length=4),
            PacketFieldMetadata(name="gw_rx_count", length=4),
            PacketFieldMetadata(name="gw_rx_asn", length=8),
            PacketFieldMetadata(name="gw_tx_enqueued_asn", length=8),
            PacketFieldMetadata(name="gw_tx_dequeued_asn", length=8),
            PacketFieldMetadata(name="node_rx_count", length=4),
            PacketFieldMetadata(name="node_tx_count", length=4),
            PacketFieldMetadata(name="node_rx_asn", length=8),
            PacketFieldMetadata(name="node_tx_enqueued_asn", length=8),
            PacketFieldMetadata(name="node_tx_dequeued_asn", length=8),
            PacketFieldMetadata(name="rssi_at_node", length=1),
            PacketFieldMetadata(name="rssi_at_gw", length=1),
        ]
    )
    type_: DefaultPayloadType = DefaultPayloadType.METRICS_PROBE
    cloud_tx_ts_us: int = 0
    cloud_rx_ts_us: int = 0
    cloud_tx_count: int = 0
    cloud_rx_count: int = 0
    edge_tx_ts_us: int = 0
    edge_rx_ts_us: int = 0
    edge_tx_count: int = 0
    edge_rx_count: int = 0
    gw_tx_count: int = 0
    gw_rx_count: int = 0
    gw_rx_asn: int = 0
    gw_tx_enqueued_asn: int = 0
    gw_tx_dequeued_asn: int = 0
    node_rx_count: int = 0
    node_tx_count: int = 0
    node_rx_asn: int = 0
    node_tx_enqueued_asn: int = 0
    node_tx_dequeued_asn: int = 0
    rssi_at_node: int = 0
    rssi_at_gw: int = 0

    @property
    def packet_length(self) -> int:
        return sum(field.length for field in self.metadata)

    @property
    def asn(self) -> int:
        """ASN at reception back from the network"""
        return self.gw_rx_asn

    def latency_roundtrip_node_edge_ms(self) -> float:
        return (self.edge_rx_ts_us - self.edge_tx_ts_us) / 1000.0

    def latency_roundtrip_node_cloud_ms(self) -> float:
        return (self.cloud_rx_ts_us - self.cloud_tx_ts_us) / 1000.0

    def pdr_uplink_radio(self, probe_stats_start_epoch=None) -> float:
        if probe_stats_start_epoch is None:
            # if no epoch is provided, use the current values
            gw_rx_count = self.gw_rx_count
            node_tx_count = self.node_tx_count
        else:
            # if epoch is provided, subtract the epoch values from the current values
            if probe_stats_start_epoch.asn == 0:
                return 0
            gw_rx_count = self.gw_rx_count - probe_stats_start_epoch.gw_rx_count
            node_tx_count = self.node_tx_count - probe_stats_start_epoch.node_tx_count
        if node_tx_count <= 0:
            return 0
        return gw_rx_count / node_tx_count

    def pdr_downlink_radio(self, probe_stats_start_epoch=None) -> float:
        if probe_stats_start_epoch is None:
            # if no epoch is provided, use the current values
            gw_tx_count = self.gw_tx_count
            node_rx_count = self.node_rx_count
        else:
            # if epoch is provided, subtract the epoch values from the current values
            if probe_stats_start_epoch.asn == 0:
                return 0
            gw_tx_count = self.gw_tx_count - probe_stats_start_epoch.gw_tx_count
            node_rx_count = self.node_rx_count - probe_stats_start_epoch.node_rx_count
        if gw_tx_count <= 0:
            return 0
        return node_rx_count / gw_tx_count

    def pdr_uplink_uart(self, probe_stats_start_epoch=None) -> float:
        if probe_stats_start_epoch is None:
            # if no epoch is provided, just wait a bit
            return -1
        else:
            # if epoch is provided, subtract the epoch values from the current values
            if probe_stats_start_epoch.asn == 0:
                return 0
            # if a packet was received at the gatweway, it should also be received at the edge (otherwise, it's a loss)
            gw_rx_count = self.gw_rx_count - probe_stats_start_epoch.gw_rx_count
            edge_rx_count = self.edge_rx_count - probe_stats_start_epoch.edge_rx_count
        if gw_rx_count <= 0:
            return 0
        return edge_rx_count / gw_rx_count

    def pdr_downlink_uart(self, probe_stats_start_epoch=None) -> float:
        if probe_stats_start_epoch is None:
            # if no epoch is provided, just wait a bit
            return -1
        else:
            # if epoch is provided, subtract the epoch values from the current values
            if probe_stats_start_epoch.asn == 0:
                return 0
            # if a packet was sent at the edge, it should also be sent at the gateway (otherwise, it's a loss)
            gw_tx_count = self.gw_tx_count - probe_stats_start_epoch.gw_tx_count
            edge_tx_count = self.edge_tx_count - probe_stats_start_epoch.edge_tx_count
        if edge_tx_count <= 0:
            return 0
        return gw_tx_count / edge_tx_count

    def rssi_at_node_dbm(self) -> int:
        if self.rssi_at_node > 127:
            return self.rssi_at_node - 255
        return self.rssi_at_node

    def rssi_at_gw_dbm(self) -> int:
        if self.rssi_at_gw > 127:
            return self.rssi_at_gw - 255
        return self.rssi_at_gw

    def __repr__(self):
        rep = dataclasses.asdict(self)
        rep.pop("metadata", None)
        return f"{rep}"


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
        return (
            self.payload.startswith(DefaultPayloadType.METRICS_RESPONSE.as_bytes())
            or self.payload.startswith(DefaultPayloadType.METRICS_REQUEST.as_bytes())
            or self.payload.startswith(DefaultPayloadType.METRICS_LOAD.as_bytes())
            or self.payload.startswith(DefaultPayloadType.METRICS_PROBE.as_bytes())
        )

    @property
    def is_load_test_packet(self) -> bool:
        return self.payload.startswith(DefaultPayloadType.METRICS_LOAD.as_bytes())

    def __repr__(self):
        header_no_metadata = dataclasses.replace(self.header, metadata=[])
        return f"Frame(header={header_no_metadata}, payload={self.payload})"
