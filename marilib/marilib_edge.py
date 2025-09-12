import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from rich import print

from marilib.metrics import MetricsTester
from marilib.mari_protocol import (
    MARI_BROADCAST_ADDRESS,
    Frame,
    Header,
    DefaultPayload,
    DefaultPayloadType,
)
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
    metrics_tester: MetricsTester | None = None

    started_ts: datetime = field(default_factory=datetime.now)
    last_received_serial_data_ts: datetime = field(default_factory=datetime.now)
    last_received_mqtt_data_ts: datetime = field(default_factory=datetime.now)
    main_file: str | None = None

    def __post_init__(self):
        self.setup_params = {
            "main_file": self.main_file or "unknown",
            "serial_port": self.serial_interface.port,
        }
        if self.mqtt_interface is None:
            self.mqtt_interface = MQTTAdapterDummy()
        self.serial_interface.init(self.on_serial_data_received)
        if self.logger:
            self.logger.log_setup_parameters(self.setup_params)
        self.metrics_tester = MetricsTester(self)  # it may or not be started later

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

        with self.lock:
            self.gateway.register_sent_frame(mari_frame)
            if dst == MARI_BROADCAST_ADDRESS:
                for n in self.gateway.nodes:
                    n.register_sent_frame(mari_frame)
            elif n := self.gateway.get_node(dst):
                n.register_sent_frame(mari_frame)

        self.serial_interface.send_data(
            EdgeEvent.to_bytes(EdgeEvent.NODE_DATA) + mari_frame.to_bytes()
        )

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
    def mqtt_connected(self) -> bool:
        return self.uses_mqtt and self.mqtt_interface.is_ready()

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

        self.last_received_mqtt_data_ts = datetime.now()

        try:
            event_type = EdgeEvent(data[0])
            frame = Frame().from_bytes(data[1:])
        except (ValueError, ProtocolPayloadParserException) as exc:
            print(f"[red]Error parsing frame: {exc}[/]")
            return
        if event_type != EdgeEvent.NODE_DATA:
            return
        if frame.header.destination != MARI_BROADCAST_ADDRESS and not self.gateway.get_node(
            frame.header.destination
        ):
            return
        self.send_frame(frame.header.destination, frame.payload)

    def handle_serial_data(self, data: bytes) -> tuple[bool, EdgeEvent, Any]:
        """
        Handles the serial data received from the radio gateway.
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
                    self.gateway.register_received_frame(frame)

                    # handle metrics probe packets
                    if frame.is_test_packet:
                        payload = self.metrics_tester.handle_response_edge(frame)
                        if payload:
                            frame.payload = payload.to_bytes()

                return True, event_type, frame
            except (ValueError, ProtocolPayloadParserException):
                return False, EdgeEvent.UNKNOWN, None

        return False, event_type, None

    def on_serial_data_received(self, data: bytes):
        res, event_type, event_data = self.handle_serial_data(data)
        if not res:
            return

        if self.logger and event_type in [EdgeEvent.NODE_JOINED, EdgeEvent.NODE_LEFT]:
            self.logger.log_event(self.gateway.info.address, event_data.address, event_type.name)
        if event_type == EdgeEvent.GATEWAY_INFO:
            self.mqtt_interface.update(event_data.network_id_str, self.on_mqtt_data_received)
            if self.logger:
                self.setup_params["schedule_name"] = self.gateway.info.schedule_name
                self.logger.log_setup_parameters(self.setup_params)

        if event_type == EdgeEvent.NODE_DATA and not event_data.is_test_packet:
            # only notify the application if it's not a test packet
            self.cb_application(event_type, event_data)

        self.send_data_to_cloud(event_type, event_data)

    def send_data_to_cloud(
        self, event_type: EdgeEvent, event_data: NodeInfoEdge | GatewayInfo | Frame
    ):
        if event_type in [EdgeEvent.NODE_JOINED, EdgeEvent.NODE_LEFT, EdgeEvent.NODE_KEEP_ALIVE]:
            event_data = event_data.to_cloud(self.gateway.info.address)
        data = EdgeEvent.to_bytes(event_type) + event_data.to_bytes()
        self.mqtt_interface.send_data_to_cloud(data)

    # ============================ Utility methods =============================

    def metrics_test_enable(self):
        self.metrics_tester.start()

    def metrics_test_disable(self):
        self.metrics_tester.stop()

    # ============================ Private methods =============================

    def _is_test_packet(self, payload: bytes) -> bool:
        """Determines if a packet sent FROM the edge is for testing purposes."""
        payload = DefaultPayload().from_bytes(payload)
        return payload.type_ in [DefaultPayloadType.LOAD_TEST, DefaultPayloadType.LATENCY_TEST]
