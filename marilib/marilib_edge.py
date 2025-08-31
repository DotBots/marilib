import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from rich import print

from marilib.latency import LATENCY_PACKET_MAGIC, LatencyTester
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame, Header
from marilib.model import (
    EdgeEvent,
    GatewayInfo,
    MariGateway,
    MariNode,
    NodeInfoEdge,
    SCHEDULES,
)
from marilib.protocol import ProtocolPayloadParserException
from marilib.communication_adapter import MQTTAdapter, MQTTAdapterDummy, SerialAdapter
from marilib.marilib import MarilibBase
from marilib.tui_edge import MarilibTUIEdge

LOAD_PACKET_PAYLOAD = b"L"


@dataclass
class MarilibEdge(MarilibBase):
    """
    The MarilibEdge class runs in either a computer or a raspberry pi.
    It is used to communicate with:
    - a Mari radio gateway (nRF5340) via serial
    - a Mari cloud instance via MQTT (optional)
    """

    cb_application: Callable[[EdgeEvent, MariNode | Frame], None]
    serial_interface: SerialAdapter
    mqtt_interface: MQTTAdapter | None = None
    tui: MarilibTUIEdge | None = None

    logger: Any | None = None
    gateway: MariGateway = field(default_factory=MariGateway)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    latency_tester: LatencyTester | None = None

    started_ts: datetime = field(default_factory=datetime.now)
    last_received_serial_data_ts: datetime = field(default_factory=datetime.now)
    main_file: str | None = None

    def __post_init__(self):
        self.setup_params = {
            "main_file": self.main_file or "unknown",
            "serial_port": self.serial_interface.port,
        }
        if self.mqtt_interface is None:
            self.mqtt_interface = MQTTAdapterDummy()
        self.serial_interface.init(self.on_serial_data_received)
        # NOTE: MQTT interface will only be initialized when the network_id is known
        if self.logger:
            self.logger.log_setup_parameters(self.setup_params)

    # ============================ MarilibBase methods =========================

    def update(self):
        with self.lock:
            self.gateway.update()
            if self.logger and self.logger.active:
                self.logger.log_periodic_metrics(self.gateway, self.gateway.nodes)

    @property
    def nodes(self) -> list[MariNode]:
        return self.gateway.nodes

    def add_node(self, address: int, gateway_address: int = None) -> MariNode | None:
        with self.lock:
            return self.gateway.add_node(address)

    def remove_node(self, address: int) -> MariNode | None:
        with self.lock:
            return self.gateway.remove_node(address)

    def send_frame(self, dst: int, payload: bytes):
        """Sends a frame to the gateway via serial."""
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

        # FIXME: instead of prefixing with a magic 0x01 byte, we should use EdgeEvent.NODE_DATA
        self.serial_interface.send_data(b"\x01" + mari_frame.to_bytes())

    def render_tui(self):
        if self.tui:
            self.tui.render(self)

    def close_tui(self):
        if self.tui:
            self.tui.close()

    # ============================ MarilibEdge methods =========================

    @property
    def uses_mqtt(self) -> bool:
        return not isinstance(self.mqtt_interface, MQTTAdapterDummy)

    @property
    def serial_connected(self) -> bool:
        return self.serial_interface is not None

    def get_max_downlink_rate(self) -> float:
        """Calculate the max downlink packets/sec for a given schedule_id."""
        schedule_params = SCHEDULES.get(self.gateway.info.schedule_id)
        if not schedule_params:
            return 0.0
        d_down = schedule_params["d_down"]
        sf_duration_ms = schedule_params["sf_duration"]
        if sf_duration_ms == 0:
            return 0.0
        return d_down / (sf_duration_ms / 1000.0)

    # ============================ Callbacks ===================================

    def on_mqtt_data_received(self, data: bytes):
        """Just forwards the data to the serial interface."""
        if len(data) < 1:
            return
        try:
            event_type = EdgeEvent(data[0])
            frame = Frame().from_bytes(data[1:])
        except (ValueError, ProtocolPayloadParserException) as exc:
            print(f"[red]Error parsing frame: {exc}[/]")
            return
        if event_type != EdgeEvent.NODE_DATA:
            # ignore non-data events
            return
        if frame.header.destination != MARI_BROADCAST_ADDRESS and not self.gateway.get_node(
            frame.header.destination
        ):
            # ignore frames for unknown nodes
            return
        print(f"Cloud to Edge: dst=0x{frame.header.destination:04X} len={len(frame.payload)}")
        self.send_frame(frame.header.destination, frame.payload)

    def handle_serial_data(self, data: bytes) -> tuple[bool, EdgeEvent, Any]:
        """
        Handles the serial data received from the radio gateway:
        - parses the event
        - updates node or gateway information
        - returns the event type and data
        """

        if len(data) < 1:
            return False, EdgeEvent.UNKNOWN, None

        self.last_received_serial_data_ts = datetime.now()

        try:
            event_type = EdgeEvent(data[0])
        except ValueError:
            return False, EdgeEvent.UNKNOWN, None

        if event_type == EdgeEvent.NODE_JOINED:
            node_info = NodeInfoEdge().from_bytes(data[1:])
            self.add_node(node_info.address)
            return True, event_type, node_info

        elif event_type == EdgeEvent.NODE_LEFT:
            node_info = NodeInfoEdge().from_bytes(data[1:])
            if self.remove_node(node_info.address):
                return True, event_type, node_info
            else:
                return False, event_type, node_info

        elif event_type == EdgeEvent.NODE_KEEP_ALIVE:
            node_info = NodeInfoEdge().from_bytes(data[1:])
            with self.lock:
                self.gateway.update_node_liveness(node_info.address)
            return True, event_type, node_info

        elif event_type == EdgeEvent.GATEWAY_INFO:
            try:
                with self.lock:
                    self.gateway.set_info(GatewayInfo().from_bytes(data[1:]))
                return True, event_type, self.gateway.info
            except (ValueError, ProtocolPayloadParserException):
                return False, EdgeEvent.UNKNOWN, None

        elif event_type == EdgeEvent.NODE_DATA:
            try:
                frame = Frame().from_bytes(data[1:])
                with self.lock:
                    self.gateway.update_node_liveness(frame.header.source)
                    self.gateway.register_received_frame(frame, is_test_packet=False)
                return True, event_type, frame
            except (ValueError, ProtocolPayloadParserException):
                return False, EdgeEvent.UNKNOWN, None
        return True, event_type, None

    def on_serial_data_received(self, data: bytes):
        res, event_type, event_data = self.handle_serial_data(data)
        if res:
            if self.logger and event_type in [EdgeEvent.NODE_JOINED, EdgeEvent.NODE_LEFT]:
                self.logger.log_event(
                    self.gateway.info.address, event_data.address, event_type.name
                )
            if event_type == EdgeEvent.GATEWAY_INFO:
                # when the first GATEWAY_INFO is received, this will cause the MQTT interface to be initialized
                self.mqtt_interface.update(event_data.network_id_str, self.on_mqtt_data_received)
                if self.logger:
                    self.setup_params["schedule_name"] = self.gateway.info.schedule_name
                    self.logger.log_setup_parameters(self.setup_params)
            self.cb_application(event_type, event_data)
            self.send_data_to_cloud(event_type, event_data)

    def send_data_to_cloud(
        self, event_type: EdgeEvent, event_data: NodeInfoEdge | GatewayInfo | Frame
    ):
        if event_type in [EdgeEvent.NODE_JOINED, EdgeEvent.NODE_LEFT, EdgeEvent.NODE_KEEP_ALIVE]:
            # the cloud needs to know which gateway the node belongs to
            event_data = event_data.to_cloud(self.gateway.info.address)
        data = EdgeEvent.to_bytes(event_type) + event_data.to_bytes()
        self.mqtt_interface.send_data_to_cloud(data)

    # ============================ Utility methods =============================

    def latency_test_enable(self):
        if self.latency_tester is None:
            self.latency_tester = LatencyTester(self)
            self.latency_tester.start()

    def latency_test_disable(self):
        if self.latency_tester is not None:
            self.latency_tester.stop()
            self.latency_tester = None

    # ============================ Private methods =============================

    def _is_test_packet(self, payload: bytes) -> bool:
        """Determines if a packet is for testing purposes (load or latency)."""
        is_latency = payload.startswith(LATENCY_PACKET_MAGIC)
        is_load = payload == LOAD_PACKET_PAYLOAD
        return is_latency or is_load
