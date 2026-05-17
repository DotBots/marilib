import threading
import time
from typing import TYPE_CHECKING

from rich import print
from marilib.mari_protocol import Frame, DefaultPayloadType
from marilib.mari_protocol import MetricsProbePayload
from marilib.model import MariGateway, MariNode, MARI_PROBE_STATS_MAX_LEN

if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


# Wire-byte offset of edge_tx_ts_us in an outbound probe frame:
#   1 byte EdgeEvent prefix + 20-byte Header + 1-byte HeaderStats +
#   offset of edge_tx_ts_us within MetricsProbePayload.
# Used by MarilibEdge.send_probe to overwrite this field with a fresh
# monotonic timestamp inside the serial-adapter lock, just before the
# bytes leave the UART.
EDGE_TX_TS_WIRE_OFFSET = (
    1
    + 20
    + 1
    + sum(
        f.length
        for f in MetricsProbePayload().metadata
        if f.name
        in {
            "type",
            "cloud_tx_ts_us",
            "cloud_rx_ts_us",
            "cloud_tx_count",
            "cloud_rx_count",
        }
    )
)


class MetricsTester:
    """A thread-based class to periodically test metrics to all nodes."""

    def __init__(self, marilib: "MarilibEdge", interval: float = 3):
        self.marilib = marilib
        self.set_interval(interval)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def set_interval(self, interval: float):
        if interval < 0 or interval > MARI_PROBE_STATS_MAX_LEN:
            raise ValueError(f"Interval must be >= 0 and <= {MARI_PROBE_STATS_MAX_LEN}")
        self.interval = interval

    def start(self):
        """Starts the metrics testing thread."""
        if self.interval < 0 or self.interval > MARI_PROBE_STATS_MAX_LEN:
            raise ValueError(f"Interval must be >= 0 and <= {MARI_PROBE_STATS_MAX_LEN}")
        if self.interval == 0:
            print("[yellow]Metrics tester disabled.[/]")
            return
        print(f"[yellow]Metrics tester started with interval {self.interval} seconds.[/]")
        self._thread.start()

    def stop(self):
        """Stops the metrics testing thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()
        print("[yellow]Metrics tester stopped.[/]")

    def _run(self):
        """The main loop for the testing thread."""
        # Initial delay to allow nodes to join
        self._stop_event.wait(self.interval)

        while not self._stop_event.is_set():
            nodes = list(self.marilib.nodes)
            if not nodes:
                self._stop_event.wait(self.interval)
                continue

            for node in nodes:
                if self._stop_event.is_set():
                    break
                self.send_metrics_request(node, "edge")
                # Spread the requests evenly over the interval
                sleep_duration = self.interval / len(nodes)
                self._stop_event.wait(sleep_duration)

    def timestamp_us(self) -> int:
        """Returns a monotonic timestamp in microseconds.

        Monotonic (not wall-clock), so an NTP step adjustment cannot
        create apparent jumps in measured latency. Edge stamps both
        ends of the probe round trip with the same clock; the node
        firmware echoes edge_tx_ts_us back unchanged as an opaque
        8-byte blob.
        """
        return time.monotonic_ns() // 1000

    def send_metrics_request(self, node: MariNode, marilib_type: str):
        """Sends a metrics request packet to a specific address."""
        payload = MetricsProbePayload()
        if marilib_type == "edge":
            # Leave edge_tx_ts_us as 0; MarilibEdge.send_probe overwrites
            # it with a monotonic timestamp inside the serial lock, right
            # before the bytes leave the UART — avoids inflating the
            # measured RTT with mari.lock contention from render_tui /
            # update / other send_frame calls.
            payload.edge_tx_count = node.probe_increment_tx_count()
            payload_bytes = payload.to_bytes()
            self.marilib.send_probe(node.address, payload_bytes)
        elif marilib_type == "cloud":
            # Cloud probes are still stamped on call (MQTT publish is
            # async and the cloud's MetricsTester is currently never
            # started — marilib_cloud.py:55-57 — so this path is unused).
            payload.cloud_tx_ts_us = self.timestamp_us()
            payload.cloud_tx_count = node.probe_increment_tx_count()
            payload_bytes = payload.to_bytes()
            self.marilib.send_frame(node.address, payload_bytes)

    def handle_response_edge(self, frame: Frame, rx_ts_us: int | None = None):
        """
        Processes a metrics response frame.
        This should be called when a LATENCY_DATA event is received.

        `rx_ts_us` is the monotonic-microsecond timestamp captured by
        the serial adapter when the HDLC frame became READY (i.e.
        right after the wire bytes arrived). When supplied, it's used
        as edge_rx_ts_us instead of stamping here — handler runs
        inside mari.lock, which can be held by render_tui / update /
        send_frame for tens of ms, so stamping here would inflate the
        measured RTT.
        """
        node = self.marilib.gateway.get_node(frame.header.source)
        if not node:
            print(f"[red]Node not found: {frame.header.source:016x}[/]")
            return

        try:
            payload = MetricsProbePayload().from_bytes(frame.payload)
            if payload.type_ != DefaultPayloadType.METRICS_PROBE:
                print(f"[red]Expected METRICS_PROBE, got {payload.type_}[/]")
                return

        except Exception as e:
            print(f"[red]Error parsing metrics response: {e}[/]")
            return

        payload.edge_rx_ts_us = (
            rx_ts_us if rx_ts_us is not None else self.timestamp_us()
        )
        payload.edge_rx_count = node.probe_increment_rx_count()

        node.save_probe_stats(payload)

        # print(f"<<< received metrics probe from {frame.header.source:016x}: {payload}")
        # print(f"    size is {len(frame.payload)} bytes: {frame.payload.hex()}\n")

        # print(f"    latency_roundtrip_node_edge_ms: {payload.latency_roundtrip_node_edge_ms()}")
        # print(f"    pdr_uplink_radio: {payload.pdr_uplink_radio(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_radio: {payload.pdr_downlink_radio(node.probe_stats_start_epoch)}")
        # print(f"    pdr_uplink_uart: {payload.pdr_uplink_uart(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_uart: {payload.pdr_downlink_uart(node.probe_stats_start_epoch)}")
        # print(f"    rssi_at_node_dbm: {payload.rssi_at_node_dbm()}")
        # print(f"    rssi_at_gw_dbm: {payload.rssi_at_gw_dbm()}")

        return payload

    def handle_response_cloud(self, frame: Frame, gateway: MariGateway, node: MariNode):
        """
        Processes a metrics response frame.
        This should be called when a LATENCY_DATA event is received.
        """
        try:
            payload = MetricsProbePayload().from_bytes(frame.payload)
            if payload.type_ != DefaultPayloadType.METRICS_PROBE:
                print(f"[red]Expected METRICS_PROBE, got {payload.type_}[/]")
                return

        except Exception as e:
            print(f"[red]Error parsing metrics response: {e}[/]")
            return

        payload.cloud_rx_ts_us = self.timestamp_us()
        payload.cloud_rx_count = node.probe_increment_rx_count()

        node.save_probe_stats(payload)

        # print(f"<<< received metrics probe from {frame.header.source:016x}: {payload}")
        # print(f"    size is {len(frame.payload)} bytes: {frame.payload.hex()}\n")

        # print(f"    latency_roundtrip_node_edge_ms: {payload.latency_roundtrip_node_edge_ms()}")
        # print(f"    pdr_uplink_radio: {payload.pdr_uplink_radio(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_radio: {payload.pdr_downlink_radio(node.probe_stats_start_epoch)}")
        # print(f"    pdr_uplink_uart: {payload.pdr_uplink_uart(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_uart: {payload.pdr_downlink_uart(node.probe_stats_start_epoch)}")
        # print(f"    rssi_at_node_dbm: {payload.rssi_at_node_dbm()}")
        # print(f"    rssi_at_gw_dbm: {payload.rssi_at_gw_dbm()}")

        return payload
