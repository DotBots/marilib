import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from marilib.latency import LATENCY_PACKET_MAGIC, LatencyTester
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame, Header
from marilib.model import (
    EdgeEvent,
    GatewayInfo,
    MariGateway,
    MariNode,
    NodeStatsReply,
    SCHEDULES,
)
from marilib.protocol import ProtocolPayloadParserException
from marilib.serial_adapter import SerialAdapter
from marilib.serial_uart import get_default_port

LOAD_PACKET_PAYLOAD = b"L"


@dataclass
class MariLib:
    """Main MariLib class."""

    cb_application: Callable[[EdgeEvent, MariNode | Frame], None]
    port: str | None = None
    baudrate: int = 1_000_000
    logger: Any | None = None
    gateway: MariGateway = field(default_factory=MariGateway)
    serial_interface: SerialAdapter | None = None
    started_ts: datetime = field(default_factory=datetime.now)
    last_received_serial_data: datetime = field(default_factory=datetime.now)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    latency_tester: LatencyTester | None = None

    def __post_init__(self):
        if self.port is None:
            self.port = get_default_port()
        self.serial_interface = SerialAdapter(self.port, self.baudrate)
        self.serial_interface.init(self.on_data_received)

    def get_max_downlink_rate(self, schedule_id: int) -> float:
        """Calculate the max downlink packets/sec for a given schedule_id."""
        schedule_params = SCHEDULES.get(schedule_id)
        if not schedule_params:
            return 0.0
        d_down = schedule_params["d_down"]
        sf_duration_ms = schedule_params["sf_duration"]
        if sf_duration_ms == 0:
            return 0.0
        return d_down / (sf_duration_ms / 1000.0)

    def log_periodic_metrics(self):
        if self.logger and self.logger.active:
            self.logger.log_gateway_metrics(self.gateway)
            self.logger.log_all_nodes_metrics(list(self.gateway.node_registry.values()))

    def latency_test_enable(self):
        if self.latency_tester is None:
            self.latency_tester = LatencyTester(self)
            self.latency_tester.start()

    def latency_test_disable(self):
        if self.latency_tester is not None:
            self.latency_tester.stop()
            self.latency_tester = None

    @property
    def serial_connected(self) -> bool:
        return self.serial_interface is not None

    def _is_test_packet(self, payload: bytes) -> bool:
        """Determines if a packet is for testing purposes (load or latency)."""
        is_latency = payload.startswith(LATENCY_PACKET_MAGIC)
        is_load = payload == LOAD_PACKET_PAYLOAD
        return is_latency or is_load

    def on_data_received(self, data: bytes):
        with self.lock:
            if len(data) < 1:
                return
            self.last_received_serial_data = datetime.now()
            event_type = data[0]

            if event_type == EdgeEvent.NODE_JOINED:
                node = self.gateway.add_node(int.from_bytes(data[1:9], "little"))
                if self.logger:
                    self.logger.log_event(node.address, EdgeEvent.NODE_JOINED.name)
                self.cb_application(EdgeEvent.NODE_JOINED, node)
            elif event_type == EdgeEvent.NODE_LEFT:
                if n := self.gateway.remove_node(int.from_bytes(data[1:9], "little")):
                    if self.logger:
                        self.logger.log_event(n.address, EdgeEvent.NODE_LEFT.name)
                    self.cb_application(EdgeEvent.NODE_LEFT, n)
            elif event_type == EdgeEvent.NODE_KEEP_ALIVE:
                self.gateway.update_node_liveness(int.from_bytes(data[1:9], "little"))
            elif event_type == EdgeEvent.GATEWAY_INFO:
                try:
                    self.gateway.set_info(GatewayInfo().from_bytes(data[1:]))
                    # print(self.gateway.info.repr_schedule_stats())
                except (ValueError, ProtocolPayloadParserException):
                    pass
            elif event_type == EdgeEvent.NODE_DATA:
                try:
                    frame = Frame().from_bytes(data[1:])
                    self.gateway.update_node_liveness(frame.header.source)
                    payload = frame.payload
                    node = self.gateway.get_node(frame.header.source)
                    is_test_or_stats_packet = False

                    if payload.startswith(LATENCY_PACKET_MAGIC):
                        is_test_or_stats_packet = True
                        if self.latency_tester:
                            self.latency_tester.handle_response(frame)

                    elif len(payload) == 8:
                        try:
                            stats_reply = NodeStatsReply().from_bytes(payload)

                            if node:
                                if not hasattr(node, "stats_reply_count"):
                                    node.stats_reply_count = 0
                                node.stats_reply_count += 1

                                node.last_reported_rx_count = stats_reply.rx_app_packets
                                node.last_reported_tx_count = stats_reply.tx_app_packets

                                # Calculate PDR Downlink
                                if node.stats.cumulative_sent_non_test > 0:
                                    pdr = (
                                        node.last_reported_rx_count
                                        / node.stats.cumulative_sent_non_test
                                    )
                                    node.pdr_downlink = min(pdr, 1.0)
                                else:
                                    node.pdr_downlink = 1.0

                                # Calculate PDR Uplink
                                if node.last_reported_tx_count > 0:
                                    pdr = (
                                        node.stats_reply_count
                                        / node.last_reported_tx_count
                                    )
                                    node.pdr_uplink = min(pdr, 1.0)

                        except (ValueError, ProtocolPayloadParserException):
                            pass

                    self.gateway.register_received_frame(frame, is_test_or_stats_packet)

                    if not is_test_or_stats_packet:
                        self.cb_application(EdgeEvent.NODE_DATA, frame)

                except (ValueError, ProtocolPayloadParserException):
                    pass

    def send_frame(self, dst: int, payload: bytes):
        assert self.serial_interface is not None

        mari_frame = Frame(Header(destination=dst), payload=payload)
        is_test = self._is_test_packet(payload)

        with self.lock:
            # Only register statistics for normal data packets, not for test packets.
            self.gateway.register_sent_frame(mari_frame, is_test)
            if dst == MARI_BROADCAST_ADDRESS:
                for n in self.gateway.nodes:
                    n.register_sent_frame(mari_frame, is_test)
            elif n := self.gateway.get_node(dst):
                n.register_sent_frame(mari_frame, is_test)

        self.serial_interface.send_data(b"\x01" + mari_frame.to_bytes())
