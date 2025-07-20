import time

import click

from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame
from marilib.marilib import MariLib
from marilib.model import EdgeEvent, MariNode
from marilib.serial_uart import get_default_port
from marilib.tui import MariLibTUI

SERIAL_PORT_DEFAULT = get_default_port()


def on_event(event: EdgeEvent, event_data: MariNode | Frame):
    if event == EdgeEvent.NODE_JOINED:
        assert isinstance(event_data, MariNode)
        print(f"Node {event_data} joined")
        # print("#", end="", flush=True)
    elif event == EdgeEvent.NODE_LEFT:
        assert isinstance(event_data, MariNode)
        print(f"Node {event_data} left")
        # print("0", end="", flush=True)
    elif event == EdgeEvent.NODE_DATA:
        assert isinstance(event_data, Frame)
        # print(f"Got frame from 0x{event_data.header.source:016x}: {event_data.payload.hex()}, rssi: {event_data.stats.rssi_dbm}")
        print(".", end="", flush=True)


@click.command()
@click.option(
    "--port",
    "-p",
    default=SERIAL_PORT_DEFAULT,
    help="Serial port to use (e.g., /dev/ttyACM0)",
)
def main(port: str | None):
    """Basic example of using MariLib to communicate with nodes."""
    mari = MariLib(on_event, port)
    tui = MariLibTUI()

    try:
        while True:
            mari.gateway.update()
            if len(mari.gateway.nodes) > 0:
                mari.send_frame(dst=MARI_BROADCAST_ADDRESS, payload=b"A" * 224)
            # for node in mari.gateway.nodes:
            #     # print(f"Sending frame to 0x{node.address:016x}")
            #     mari.send_frame(dst=node.address, payload=b"A" * 3)
            time.sleep(0.3)
            # tui.render(mari)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        tui.close()


if __name__ == "__main__":
    main()
