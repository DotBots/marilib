"""
This script is used to generate a frame to send to a node.

Usage:
python frames.py [destination]

If no destination is provided, the frame will be sent to the broadcast address.

Example usage sending to broadcast address via mosquitto_pub:

while [ 1 ]; do  python examples/frames.py | xxd -r -p | base64 | mosquitto_pub -h localhost -p 1883 -t /mari/00A0/to_edge -l; done
"""

from marilib.mari_protocol import Frame, Header, MARI_BROADCAST_ADDRESS, MetricsProbePayload
from marilib.model import EdgeEvent
from rich import print
import sys

destination = sys.argv[1] if len(sys.argv) > 1 else MARI_BROADCAST_ADDRESS

header = Header(destination=destination)
frame = Frame(header=header, payload=b"NORMAL_APP_DATA")
print(frame)
frame_to_send = EdgeEvent.to_bytes(EdgeEvent.NODE_DATA) + frame.to_bytes()
print(frame_to_send.hex())

probe_payload = MetricsProbePayload()
print(probe_payload.packet_length, probe_payload)
print(probe_payload.to_bytes().hex())
