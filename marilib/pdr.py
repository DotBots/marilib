import threading
from typing import TYPE_CHECKING
from rich import print

from marilib.model import NodeStatsReply
from marilib.mari_protocol import Frame
from marilib.protocol import ProtocolPayloadParserException


if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


PDR_STATS_REQUEST_PAYLOAD = b"S"


class PDRTester:
    """A thread-based class to periodically test PDR to all nodes."""

    def __init__(self, marilib: "MarilibEdge", interval: float = 15.0):
        self.marilib = marilib
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Starts the PDR testing thread."""
        print("[yellow]PDR tester started.[/]")
        self._thread.start()

    def stop(self):
        """Stops the PDR testing thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join()
        print("[yellow]PDR tester stopped.[/]")

    def _run(self):
        """The main loop for the testing thread."""
        self._stop_event.wait(self.interval)

        while not self._stop_event.is_set():
            nodes = list(self.marilib.nodes)
            if not nodes:
                self._stop_event.wait(self.interval)
                continue

            for node in nodes:
                if self._stop_event.is_set():
                    break
                self.send_pdr_request(node.address)

                # Spread requests evenly over the interval
                sleep_duration = self.interval / len(nodes)
                self._stop_event.wait(sleep_duration)

    def send_pdr_request(self, address: int):
        """Sends a PDR stats request to a specific address."""
        self.marilib.send_frame(address, PDR_STATS_REQUEST_PAYLOAD)

    def handle_response(self, frame: Frame) -> bool:
        """
        Handles a PDR stats response frame and calculates PDR values.
        Returns True if the frame was a valid stats reply, False otherwise.
        """
        if len(frame.payload) != 8:
            return False

        try:
            stats_reply = NodeStatsReply().from_bytes(frame.payload)
            node = self.marilib.gateway.get_node(frame.header.source)

            if node:
                # Update with the latest stats reported by the node
                node.last_reported_rx_count = stats_reply.rx_app_packets
                node.last_reported_tx_count = stats_reply.tx_app_packets

                # Calculate Downlink PDR
                sent_count = node.stats.sent_count(include_test_packets=False)
                if sent_count > 0:
                    pdr = node.last_reported_rx_count / sent_count
                    node.pdr_downlink = min(pdr, 1.0)
                else:
                    node.pdr_downlink = 0.0

                # Calculate Uplink PDR
                received_count = node.stats.received_count(include_test_packets=False)
                if node.last_reported_tx_count > 0:
                    pdr = received_count / node.last_reported_tx_count
                    node.pdr_uplink = min(pdr, 1.0)
                else:
                    node.pdr_uplink = 0.0

                return True

        except (ValueError, ProtocolPayloadParserException):
            return False

        return False
