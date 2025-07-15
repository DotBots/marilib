import time

import click

from mira_edge.mira_edge import MiraEdge
from mira_edge.mira_protocol import MIRA_BROADCAST_ADDRESS, Frame
from mira_edge.model import EdgeEvent, MiraNode
from mira_edge.serial_uart import get_default_port
from mira_edge.tui import MiraEdgeTUI

SERIAL_PORT_DEFAULT = get_default_port()


def on_event(event: EdgeEvent, event_data: MiraNode | Frame):
    if event == EdgeEvent.NODE_JOINED:
        assert isinstance(event_data, MiraNode)
        # print(f"Node {event_data} joined")
        # print("#", end="", flush=True)
    elif event == EdgeEvent.NODE_LEFT:
        assert isinstance(event_data, MiraNode)
        # print(f"Node {event_data} left")
        # print("0", end="", flush=True)
    elif event == EdgeEvent.NODE_DATA:
        assert isinstance(event_data, Frame)
        # print(f"Got frame from 0x{event_data.header.source:016x}: {event_data.payload.hex()}, rssi: {event_data.stats.rssi_dbm}")
        # print(".", end="", flush=True)


@click.command()
@click.option(
    "--port",
    "-p",
    default=SERIAL_PORT_DEFAULT,
    help="Serial port to use (e.g., /dev/ttyACM0)",
)
def main(port: str | None):
    """Basic example of using MiraEdge to communicate with nodes."""
    mira = MiraEdge(on_event, port=port)
    tui = MiraEdgeTUI()

    try:
        while True:
            mira.gateway.update()
            if len(mira.gateway.nodes) > 0:
                mira.send_frame(dst=MIRA_BROADCAST_ADDRESS, payload=b"A" * 224)
            # for node in mira.gateway.nodes:
            #     # print(f"Sending frame to 0x{node.address:016x}")
            #     mira.send_frame(dst=node.address, payload=b"A" * 3)
            time.sleep(0.3)
            tui.render(mira)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        tui.close()


if __name__ == "__main__":
    main()
