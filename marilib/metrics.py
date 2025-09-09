import threading
import time
from typing import TYPE_CHECKING
import math

from rich import print
from marilib.mari_protocol import Frame, DefaultPayloadType
from marilib.mari_protocol import MetricsProbePayload
from marilib.model import MariNode

if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


class MetricsTester:
    """A thread-based class to periodically test metrics to all nodes."""

    def __init__(self, marilib: "MarilibEdge", interval: float = 1):
        self.marilib = marilib
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Starts the metrics testing thread."""
        print("[yellow]Metrics tester started.[/]")
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
        """Returns the current time in microseconds."""
        return int(time.time() * 1000 * 1000)

    def send_metrics_request(self, node: MariNode, marilib_type: str):
        """Sends a metrics request packet to a specific address."""
        payload = MetricsProbePayload()
        if marilib_type == "edge":
            payload.edge_tx_ts_us = self.timestamp_us()
            payload.edge_tx_count = node.probe_increment_tx_count()
        elif marilib_type == "cloud":
            payload.cloud_tx_ts_us = self.timestamp_us()
            payload.cloud_tx_count = node.probe_increment_tx_count()
        # print(f">>> sending metrics probe to {node.address:016x}: {payload}")
        payload = payload.to_bytes()
        # print(f"    size is {len(payload)} bytes: {payload.hex()}\n")
        self.marilib.send_frame(node.address, payload)

    def handle_response(self, frame: Frame, marilib_type: str):
        """
        Processes a metrics response frame.
        This should be called when a LATENCY_DATA event is received.
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

        if marilib_type == "edge":
            payload.edge_rx_ts_us = self.timestamp_us()
            payload.edge_rx_count = node.probe_increment_rx_count()
        elif marilib_type == "cloud":
            payload.cloud_rx_ts_us = self.timestamp_us()
            payload.cloud_rx_count = node.probe_increment_rx_count()

        node.save_probe_stats(payload)

        # print(f"<<< received metrics probe from {frame.header.source:016x}: {payload}")
        # print(f"    size is {len(frame.payload)} bytes: {frame.payload.hex()}\n")

        # print(f"    latency_roundtrip_node_edge_ms: {payload.latency_roundtrip_node_edge_ms()}")
        # print(f"    pdr_uplink_node_gw: {payload.pdr_uplink_node_gw(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_node_gw: {payload.pdr_downlink_node_gw(node.probe_stats_start_epoch)}")
        # print(f"    pdr_uplink_gw_edge: {payload.pdr_uplink_gw_edge(node.probe_stats_start_epoch)}")
        # print(f"    pdr_downlink_gw_edge: {payload.pdr_downlink_gw_edge(node.probe_stats_start_epoch)}")
        # print(f"    rssi_at_node_dbm: {payload.rssi_at_node_dbm()}")
        # print(f"    rssi_at_gw_dbm: {payload.rssi_at_gw_dbm()}")

