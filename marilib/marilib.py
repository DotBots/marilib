from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame, Header
from marilib.model import EdgeEvent, GatewayInfo, MariGateway, MariNode
from marilib.protocol import ProtocolPayloadParserException
from marilib.serial_adapter import SerialAdapter
from marilib.serial_uart import get_default_port
from marilib.ela_handler import ELAHandler


USE_ELA = True


@dataclass
class MariLib:
    cb_application: Callable[[EdgeEvent, MariNode | Frame], None]
    port: str | None = None
    baudrate: int = 1_000_000
    gateway: MariGateway = field(default_factory=MariGateway)
    serial_interface: SerialAdapter | None = None
    started_ts: datetime = field(default_factory=datetime.now)
    last_received_serial_data: datetime = field(default_factory=datetime.now)
    pending_edhoc_sessions: dict[int, ELAHandler] = field(default_factory=dict)

    def __post_init__(self):
        if self.port is None:
            self.port = get_default_port()
        self.serial_interface = SerialAdapter(self.port, self.baudrate)
        self.serial_interface.init(self.on_data_received)

    @property
    def serial_connected(self) -> bool:
        return self.serial_interface is not None

    def on_data_received(self, data: bytes):
        if len(data) < 1:
            return

        self.last_received_serial_data = datetime.now()

        event_type = data[0]
        # print(bytes(data).hex())

        if event_type == EdgeEvent.NODE_JOINED:
            frame_bytes = data[1:]
            frame = Frame().from_bytes(frame_bytes)

            if USE_ELA:
                print(f"Node trying to join: {frame}")
                ela_handler = ELAHandler()
                ela_handler.handle_message_1(frame)
            else:
                print(f"Node joined: {frame.header.destination}")
                address = frame.header.destination
                # print(f"Event: {EdgeEvent.NODE_JOINED.name} {address}")
                node = self.gateway.add_node(address)
                self.cb_application(EdgeEvent.NODE_JOINED, node)

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
        mari_frame = Frame(Header(destination=dst), payload=payload)
        uart_frame_type = b"\x01"
        uart_frame = uart_frame_type + mari_frame.to_bytes()
        self.serial_interface.send_data(uart_frame)
        if node := self.gateway.get_node(dst):
            node.register_sent_frame(mari_frame)
        elif dst == MARI_BROADCAST_ADDRESS:
            for node in self.gateway.nodes:
                node.register_sent_frame(mari_frame)
        self.gateway.register_sent_frame(mari_frame)
