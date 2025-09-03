import struct
import threading
import time
from typing import TYPE_CHECKING
import math

from rich import print
from marilib.mari_protocol import Frame
from marilib.mari_protocol import DefaultPayload, DefaultPayloadType

if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


class LatencyTester:
    """A thread-based class to periodically test latency to all nodes."""

    def __init__(self, marilib: "MarilibEdge", interval: float = 10.0):
        self.marilib = marilib
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Starts the latency testing thread."""
        print("[yellow]Latency tester started.[/]")
        self._thread.start()

    def stop(self):
        """Stops the latency testing thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()
        print("[yellow]Latency tester stopped.[/]")

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
                self.send_latency_request(node.address)
                # Spread the requests evenly over the interval
                sleep_duration = self.interval / len(nodes)
                self._stop_event.wait(sleep_duration)

    def send_latency_request(self, address: int):
        """Sends a latency request packet to a specific address."""
        payload = DefaultPayload(type_=DefaultPayloadType.LATENCY_TEST, needs_ack=True).to_bytes() + struct.pack("<d", time.time())
        self.marilib.send_frame(address, payload)

    def handle_response(self, frame: Frame):
        """
        Processes a latency response frame.
        This should be called when a LATENCY_DATA event is received.
        """
        payload = DefaultPayload().from_bytes(frame.payload)
        if payload.type_ != DefaultPayloadType.LATENCY_TEST:
            return
        try:
            # Unpack the original timestamp from the payload
            original_ts = struct.unpack("<d", frame.payload[2:10])[0]
            rtt = time.time() - original_ts
            if math.isnan(rtt) or math.isinf(rtt):
                return  # Ignore corrupted/invalid packets
            if rtt < 0 or rtt > 5.0:
                return  # Ignore this outlier

            node = self.marilib.gateway.get_node(frame.header.source)
            if node:
                # Update statistics for both the specific node and the whole gateway
                node.latency_stats.add_latency(rtt)
                self.marilib.gateway.latency_stats.add_latency(rtt)

        except (struct.error, IndexError):
            # Ignore packets that are too short or malformed
            pass
