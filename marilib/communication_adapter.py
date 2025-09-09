import base64
from urllib.parse import urlparse
import paho.mqtt.client as mqtt

from abc import ABC, abstractmethod
from rich import print

from marilib.serial_hdlc import (
    HDLCDecodeException,
    HDLCHandler,
    HDLCState,
    hdlc_encode,
)
from marilib.serial_uart import SerialInterface, SERIAL_DEFAULT_BAUDRATE


class CommunicationAdapterBase(ABC):
    """Base class for interface adapters."""

    @abstractmethod
    def init(self, on_data_received: callable):
        """Initialize the interface."""

    @abstractmethod
    def close(self):
        """Close the interface."""


class SerialAdapter(CommunicationAdapterBase):
    """Class used to interface with the serial port."""

    def __init__(self, port, baudrate=SERIAL_DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.hdlc_handler = HDLCHandler()

    def on_byte_received(self, byte):
        self.hdlc_handler.handle_byte(byte)
        if self.hdlc_handler.state == HDLCState.READY:
            try:
                payload = self.hdlc_handler.payload
                # print(f"Received payload: {payload.hex()}")
                self.on_data_received(payload)
            except HDLCDecodeException as e:
                print(f"Error decoding payload: {e}")

    def init(self, on_data_received: callable):
        self.on_data_received = on_data_received
        self.serial = SerialInterface(self.port, self.baudrate, self.on_byte_received)
        print(f"[yellow]Connected to serial port {self.port} at {self.baudrate} baud[/]")

    def close(self):
        print("[yellow]Disconnect from gateway...[/]")

    def send_data(self, data):
        with self.serial.lock:  # Use the existing lock for thread safety
            self.serial.serial.flush()
            encoded = hdlc_encode(data)
            self.serial.write(encoded)


class MQTTAdapter(CommunicationAdapterBase):
    """Class used to interface with MQTT."""

    def __init__(self, host, port, is_edge: bool, use_tls: bool = False):
        self.host = host
        self.port = port
        self.is_edge = is_edge
        self.network_id = None
        self.client = None
        self.on_data_received = None
        self.use_tls = use_tls
        # optimize qos for throughput
        # 0 = no delivery guarantee, 1 = at least once, 2 = exactly once
        self.qos = 0

    @classmethod
    def from_url(cls, url: str, is_edge: bool):
        url = urlparse(url)
        host, port = url.netloc.split(":")
        if url.scheme == "mqtt":
            return cls(host, int(port), is_edge, use_tls=False)
        elif url.scheme == "mqtts":
            return cls(host, int(port), is_edge, use_tls=True)
        else:
            raise ValueError(f"Invalid MQTT URL: {url} (must start with mqtt:// or mqtts://)")

    # ==== public methods ====

    def is_ready(self) -> bool:
        return self.client is not None and self.client.is_connected()

    def set_network_id(self, network_id: str):
        self.network_id = network_id

    def set_on_data_received(self, on_data_received: callable):
        self.on_data_received = on_data_received

    def update(self, network_id: str, on_data_received: callable):
        if self.network_id is None:
            # might have been set by set_network_id
            self.network_id = network_id
        else:
            # TODO: handle the case when the network_id changes
            pass
        if self.network_id is None:
            # wait a bit, network_id not set yet
            return
        if self.on_data_received is None:
            self.set_on_data_received(on_data_received)
        if not self.is_ready():
            self.init()

    def init(self):
        if self.client:
            # already initialized, do nothing
            return
        if self.network_id is None:
            # network_id not set yet
            return

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTProtocolVersion.MQTTv5,
        )
        if self.use_tls:
            self.client.tls_set_context(context=None)
        self.client.on_log = self._on_log
        self.client.on_connect = self._on_connect_edge if self.is_edge else self._on_connect_cloud
        self.client.on_message = self._on_message_edge if self.is_edge else self._on_message_cloud
        self.client.connect(self.host, self.port, 60)
        print(f"[yellow]Connected to MQTT broker on {self.host}:{self.port}[/]")
        self.client.loop_start()

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()

    def send_data_to_edge(self, data):
        if not self.is_ready():
            return
        self.client.publish(
            f"/mari/{self.network_id}/to_edge",
            base64.b64encode(data).decode(),
            qos=self.qos,
        )

    def send_data_to_cloud(self, data):
        if not self.is_ready():
            return
        self.client.publish(
            f"/mari/{self.network_id}/to_cloud",
            base64.b64encode(data).decode(),
            qos=self.qos,
        )

    # ==== private methods ====

    # TODO: de-duplicate the _on_message_* functions? decide as the integration evolves
    def _on_message_edge(self, client, userdata, message):
        try:
            data = base64.b64decode(message.payload)
        except Exception as e:
            # print the error and a stacktrace
            print(f"[red]Error decoding MQTT message: {e}[/]")
            print(f"[red]Message: {message.payload}[/]")
            return
        self.on_data_received(data)

    def _on_message_cloud(self, client, userdata, message):
        try:
            data = base64.b64decode(message.payload)
        except Exception as e:
            # print the error and a stacktrace
            print(f"[red]Error decoding MQTT message: {e}[/]")
            print(f"[red]Message: {message.payload}[/]")
            return
        self.on_data_received(data)

    def _on_log(self, client, userdata, paho_log_level, messages):
        # print(messages)
        pass

    def _on_connect_edge(self, client, userdata, flags, reason_code, properties):
        self.client.subscribe(f"/mari/{self.network_id}/to_edge", qos=self.qos)
        print(f"[yellow]Subscribed to /mari/{self.network_id}/to_edge[/]")

    def _on_connect_cloud(self, client, userdata, flags, reason_code, properties):
        self.client.subscribe(f"/mari/{self.network_id}/to_cloud", qos=self.qos)
        print(f"[yellow]Subscribed to /mari/{self.network_id}/to_cloud[/]")


class MQTTAdapterDummy(MQTTAdapter):
    """Dummy MQTT adapter, does nothing, for when edge runs only locally, without a cloud."""

    def __init__(self, host="", port=0, is_edge=True):
        super().__init__(host, port, is_edge)

    def is_ready(self) -> bool:
        """Dummy adapter is never ready."""
        return False

    def init(self):
        pass

    def close(self):
        pass

    def send_data_to_edge(self, data):
        pass

    def send_data_to_cloud(self, data):
        pass
