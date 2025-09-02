import struct
import threading
import time
from typing import TYPE_CHECKING
import math

from marilib.mari_protocol import Frame

if TYPE_CHECKING:
    from marilib.marilib import MariLib

LATENCY_PACKET_MAGIC = b"\x4c\x54"  # "LT" for Latency Test


class LatencyTester:
    """A thread-based class to periodically test latency to all nodes."""

    def __init__(self, marilib: "MariLib", interval: float = 10.0):
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
        self._thread.join()
        print("[yellow]Latency tester stopped.[/]")

    def _run(self):
        """The main loop for the testing thread."""
        while not self._stop_event.is_set():
            if not self.marilib.nodes:
                time.sleep(self.interval)
                continue

            for node in list(self.marilib.nodes):
                if self._stop_event.is_set():
                    break
                self.send_latency_request(node.address)
                time.sleep(self.interval / len(self.marilib.nodes))

    def send_latency_request(self, address: int):
        """Sends a latency request packet to a specific address."""

        payload = LATENCY_PACKET_MAGIC + struct.pack("<d", time.time())
        self.marilib.send_frame(address, payload)

    def handle_response(self, frame: Frame):
        """
        Processes a latency response frame.
        This should be called when a LATENCY_DATA event is received.
        """
        if not frame.payload.startswith(LATENCY_PACKET_MAGIC):
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
