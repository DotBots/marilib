import struct
import threading
import time
from typing import TYPE_CHECKING
import math

from rich import print
from marilib.mari_protocol import Frame
from marilib.mari_protocol import DefaultPayloadType, MetricsRequestPayload, MetricsResponsePayload

if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


class MetricsTester:
    """A thread-based class to periodically test metrics to all nodes."""

    def __init__(self, marilib: "MarilibEdge", interval: float = 1.0):
        self.marilib = marilib
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Starts the metrics testing thread."""
        print("[yellow]Latency tester started.[/]")
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
                self.send_metrics_request(node.address)
                # Spread the requests evenly over the interval
                sleep_duration = self.interval / len(nodes)
                self._stop_event.wait(sleep_duration)

    def send_metrics_request(self, address: int):
        """Sends a metrics request packet to a specific address."""
        # convert to microseconds and round to nearest integer
        time_us = round(time.time() * 1000 * 1000)
        payload = MetricsRequestPayload(type_=DefaultPayloadType.METRICS_REQUEST, timestamp_us=time_us).to_bytes()
        self.marilib.send_frame(address, payload)

    def handle_response(self, frame: Frame):
        """
        Processes a metrics response frame.
        This should be called when a LATENCY_DATA event is received.
        """
        try:
            payload = MetricsResponsePayload().from_bytes(frame.payload)
            if payload.type_ != DefaultPayloadType.METRICS_RESPONSE:
                print(f"[red]Expected METRICS_RESPONSE, got {payload.type_}[/]")
                return

        except Exception as e:
            print(f"[red]Error parsing metrics response: {e}[/]")
            return

        self.handle_latency_response(frame.header.source, payload.timestamp_us)
        self.handle_pdr_metric(frame.header.source, payload.rx_count, payload.tx_count)

    def handle_latency_response(self, source: int, original_ts: float):
        original_ts = original_ts / 1000 / 1000

        rtt = time.time() - original_ts
        if math.isnan(rtt) or math.isinf(rtt):
            return  # Ignore corrupted/invalid packets
        if rtt < 0 or rtt > 5.0:
            return  # Ignore this outlier

        node = self.marilib.gateway.get_node(source)
        if node:
            # Update statistics for both the specific node and the whole gateway
            node.metrics_stats.add_metrics(rtt)
            self.marilib.gateway.metrics_stats.add_metrics(rtt)

    def handle_pdr_metric(self, source: int, rx_count: int, tx_count: int):
        pass
