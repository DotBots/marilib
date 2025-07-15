from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from mira_edge.mira_protocol import MIRA_BROADCAST_ADDRESS, Frame, Header
from mira_edge.model import EdgeEvent, GatewayInfo, MiraGateway, MiraNode
from mira_edge.protocol import ProtocolPayloadParserException
from mira_edge.adapter import SerialAdapter
from mira_edge.serial_uart import get_default_port


@dataclass
class MiraEdge:
    cb_application: Callable[[EdgeEvent, MiraNode | Frame], None] = field(
        default_factory=lambda: lambda *args: None
    )
    cb_mqtt: Callable[[str, str], None] = None
    port: str | None = None
    baudrate: int = 1_000_000
    gateway: MiraGateway = field(default_factory=MiraGateway)
    serial_interface: SerialAdapter | None = None
    last_received_serial_data: datetime = field(default_factory=lambda: datetime.now())
    started_ts: datetime = field(default_factory=lambda: datetime.now())

    def __post_init__(self):
        if self.port is None:
            self.port = get_default_port()
        self.serial_interface = SerialAdapter(self.port, self.baudrate)
        self.serial_interface.init(self.on_received_serial)
        if self.cb_mqtt is not None:
            self.mqtt_interface = MQTTAdapter(self.host, self.port)
            self.mqtt_interface.init(self.on_received_mqtt)

    @property
    def serial_connected(self) -> bool:
        return self.serial_interface is not None

    def on_received_mqtt(self, topic: str, payload: bytes):
        print(f"Received MQTT message: {topic} {payload}")

    def on_received_serial(self, data: bytes):
        if len(data) < 1:
            return

        self.last_received_serial_data = datetime.now()

        event_type = data[0]
        # print(bytes(data).hex())

        if event_type == EdgeEvent.NODE_JOINED:
            address = int.from_bytes(data[1:9], "little")
            # print(f"Event: {EdgeEvent.NODE_JOINED.name} {address}")
            node = self.gateway.add_node(address)
            self.cb_application(EdgeEvent.NODE_JOINED, node)
            self.send_data(node.address_bytes)

        elif event_type == EdgeEvent.NODE_LEFT:
            address = int.from_bytes(data[1:9], "little")
            # print(f"Event: {EdgeEvent.NODE_LEFT.name} {address}")
            if node := self.gateway.remove_node(address):
                self.cb_application(EdgeEvent.NODE_LEFT, node)

        elif event_type == EdgeEvent.NODE_KEEP_ALIVE:
            address = int.from_bytes(data[1:9], "little")
            # print(f"Event: {EdgeEvent.NODE_KEEP_ALIVE.name} {address}")
            self.gateway.add_node(address)

        elif event_type == EdgeEvent.NODE_DATA:
            try:
                frame_bytes = data[1:]
                frame = Frame().from_bytes(frame_bytes)
                # print(f"Event: {EdgeEvent.NODE_DATA.name} {frame.header} {frame.payload.hex()}")
                self.gateway.register_received_frame(frame)
                self.cb_application(EdgeEvent.NODE_DATA, frame)
            except (ValueError, ProtocolPayloadParserException) as exc:
                print(f"Failed to decode frame: {exc}")

        elif event_type == EdgeEvent.GATEWAY_INFO:
            try:
                info = GatewayInfo().from_bytes(data[1:])
                self.gateway.set_info(info)
            except (ValueError, ProtocolPayloadParserException) as exc:
                print(f"Failed to decode gateway info: {exc}")

        else:
            # print(f"Unknown event: {event_type} -- {data}")
            print("?", end="", flush=True)

    def send_frame(self, dst: int, payload: bytes):
        assert self.serial_interface is not None
        mira_frame = Frame(Header(destination=dst), payload=payload)
        uart_frame_type = b"\x01"
        uart_frame = uart_frame_type + mira_frame.to_bytes()
        self.serial_interface.send_data(uart_frame)
        if node := self.gateway.get_node(dst):
            node.register_sent_frame(mira_frame)
        elif dst == MIRA_BROADCAST_ADDRESS:
            for node in self.gateway.nodes:
                node.register_sent_frame(mira_frame)
        self.gateway.register_sent_frame(mira_frame)
