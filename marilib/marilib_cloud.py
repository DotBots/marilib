import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from marilib.metrics import MetricsTester
from marilib.mari_protocol import Frame, Header
from marilib.model import (
    EdgeEvent,
    GatewayInfo,
    MariGateway,
    MariNode,
    NodeInfoCloud,
)
from marilib.communication_adapter import MQTTAdapter
from marilib.marilib import MarilibBase
from marilib.tui_cloud import MarilibTUICloud

LOAD_PACKET_PAYLOAD = b"L"


@dataclass
class MarilibCloud(MarilibBase):
    """
    The MarilibCloud class runs in a computer.
    It is used to communicate with a Mari radio gateway (nRF5340) via MQTT.
    """

    cb_application: Callable[[EdgeEvent, MariNode | Frame | GatewayInfo], None]
    mqtt_interface: MQTTAdapter
    network_id: int
    tui: MarilibTUICloud | None = None

    logger: Any | None = None
    gateways: dict[int, MariGateway] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    metrics_tester: MetricsTester | None = None

    started_ts: datetime = field(default_factory=datetime.now)
    last_received_mqtt_data_ts: datetime = field(default_factory=datetime.now)
    main_file: str | None = None

    def __post_init__(self):
        self.setup_params = {
            "main_file": self.main_file or "unknown",
            "mqtt_host": self.mqtt_interface.host,
            "mqtt_port": self.mqtt_interface.port,
            "network_id": self.network_id_str,
        }
        self.mqtt_interface.set_network_id(self.network_id_str)
        self.mqtt_interface.set_on_data_received(self.on_mqtt_data_received)
        self.mqtt_interface.init()
        if self.logger:
            self.logger.log_setup_parameters(self.setup_params)
        self.metrics_tester = MetricsTester(
            self
        )  # just instantiate, do not start it at the cloud, for now

    # ============================ MarilibBase methods =========================

    def update(self):
        """Recurrent bookkeeping. Don't forget to call this periodically on your main loop."""
        with self.lock:
            # remove dead gateways
            self.gateways = {
                addr: gateway for addr, gateway in self.gateways.items() if gateway.is_alive
            }
            # update each gateway
            for gateway in self.gateways.values():
                gateway.update()
                if self.logger:
                    self.logger.log_periodic_metrics(gateway, gateway.nodes)

    @property
    def nodes(self) -> list[MariNode]:
        return [node for gateway in self.gateways.values() for node in gateway.nodes]

    def add_node(self, address: int, gateway_address: int = None) -> MariNode | None:
        with self.lock:
            gateway = self.gateways.get(gateway_address)
            if gateway:
                node = gateway.add_node(address)
                return node
        return None

    def remove_node(self, address: int, gateway_address: int = None) -> MariNode | None:
        with self.lock:
            gateway = self.gateways.get(gateway_address)
            if gateway:
                node = gateway.remove_node(address)
                return node
        return None

    def send_frame(self, dst: int, payload: bytes):
        """
        Sends a frame to a gateway via MQTT.
        Consists in publishing a message to the /mari/{network_id}/to_edge topic.
        """
        mari_frame = Frame(Header(destination=dst), payload=payload)

        self.mqtt_interface.send_data_to_edge(
            EdgeEvent.to_bytes(EdgeEvent.NODE_DATA) + mari_frame.to_bytes()
        )

    def render_tui(self):
        if self.tui:
            self.tui.render(self)

    def close_tui(self):
        if self.tui:
            self.tui.close()

    # ============================ MarilibCloud methods =========================

    @property
    def network_id_str(self) -> str:
        return f"{self.network_id:04X}"

    # ============================ Callbacks ===================================

    def handle_mqtt_data(self, data: bytes) -> tuple[bool, EdgeEvent, Any]:
        """
        Handles the MQTT data received from the MQTT broker:
        - parses the event
        - updates node or gateway information
        - returns the event type and data (if any)
        """

        if len(data) < 1:
            return False, EdgeEvent.UNKNOWN, None

        self.last_received_mqtt_data_ts = datetime.now()

        try:
            event_type = EdgeEvent(data[0])
        except ValueError:
            return False, EdgeEvent.UNKNOWN, None

        try:
            if event_type == EdgeEvent.NODE_JOINED:
                node_info = NodeInfoCloud().from_bytes(data[1:])
                if node := self.add_node(node_info.address, node_info.gateway_address):
                    return True, EdgeEvent.NODE_JOINED, node_info

            elif event_type == EdgeEvent.NODE_LEFT:
                node_info = NodeInfoCloud().from_bytes(data[1:])
                if node := self.remove_node(node_info.address, node_info.gateway_address):
                    return True, EdgeEvent.NODE_LEFT, node_info

            elif event_type == EdgeEvent.NODE_KEEP_ALIVE:
                node_info = NodeInfoCloud().from_bytes(data[1:])
                gateway = self.gateways.get(node_info.gateway_address)
                if gateway:
                    gateway.update_node_liveness(node_info.address)
                    return True, EdgeEvent.NODE_KEEP_ALIVE, node_info

            elif event_type == EdgeEvent.GATEWAY_INFO:
                gateway_info = GatewayInfo().from_bytes(data[1:])
                gateway = self.gateways.get(gateway_info.address)
                if not gateway:
                    # we are learning about a new gateway, so instantiate it and add it to the list
                    gateway = MariGateway(info=gateway_info)
                    self.gateways[gateway.info.address] = gateway
                else:
                    gateway.set_info(gateway_info)
                return True, EdgeEvent.GATEWAY_INFO, gateway_info

            elif event_type == EdgeEvent.NODE_DATA:
                frame = Frame().from_bytes(data[1:])

                gateway_address = frame.header.destination
                node_address = frame.header.source
                gateway = self.gateways.get(gateway_address)
                if not gateway:
                    return False, EdgeEvent.UNKNOWN, None
                node = gateway.get_node(node_address)
                if not gateway or not node:
                    return False, EdgeEvent.UNKNOWN, None

                gateway.update_node_liveness(node_address)
                gateway.register_received_frame(frame)

                # handle metrics probe packets
                if frame.is_test_packet:
                    payload = self.metrics_tester.handle_response_cloud(frame, gateway, node)
                    if payload:
                        frame.payload = payload.to_bytes()

                return True, EdgeEvent.NODE_DATA, frame

        except Exception as e:
            print(f"Error handling MQTT data: {e}")

        # fallback result in case of error
        return False, EdgeEvent.UNKNOWN, None

    def on_mqtt_data_received(self, data: bytes):
        res, event_type, event_data = self.handle_mqtt_data(data)
        if res:
            if self.logger and event_type in [EdgeEvent.NODE_JOINED, EdgeEvent.NODE_LEFT]:
                # TODO: update the logging system to also support GATEWAY_INFO events from multiple gateways
                self.logger.log_event(
                    event_data.gateway_address, event_data.address, event_type.name
                )
            self.cb_application(event_type, event_data)
