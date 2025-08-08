import time

import click
from marilib.logger import MetricsLogger
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame
from marilib.marilib import MariLib
from marilib.model import EdgeEvent, MariNode
from marilib.serial_uart import get_default_port
from marilib.tui import MariLibTUI

SERIAL_PORT_DEFAULT = get_default_port()
NORMAL_DATA_PAYLOAD = b"NORMAL_APP_DATA"


def on_event(event: EdgeEvent, event_data: MariNode | Frame):
    """An event handler for the application."""
    if event == EdgeEvent.NODE_JOINED:
        # print(f"Node {event_data} joined")
        pass
    elif event == EdgeEvent.NODE_LEFT:
        # print(f"Node {event_data} left")
        pass
    elif event == EdgeEvent.NODE_DATA:
        # print(f"Got frame from 0x{event_data.header.source:016x}: {event_data.payload.hex()}, rssi: {event_data.stats.rssi_dbm}")
        pass


@click.command()
@click.option(
    "--port",
    "-p",
    type=str,
    default=SERIAL_PORT_DEFAULT,
    show_default=True,
    help="Serial port to use (e.g., /dev/ttyACM0)",
)
@click.option(
    "--log-dir",
    default="logs",
    show_default=True,
    help="Directory to save metric log files.",
    type=click.Path(),
)
def main(port: str | None, log_dir: str):
    """A basic example of using the MariLib library."""
    tui = MariLibTUI()
    setup_params = {"script_name": "basic.py", "port": port}

    logger = MetricsLogger(
        log_dir_base=log_dir, rotation_interval_minutes=1440, setup_params=setup_params
    )

    mari = MariLib(on_event, port, logger=logger)

    log_interval_seconds = 1.0
    last_log_time = 0

    try:
        while True:
            current_time = time.monotonic()

            if current_time - last_log_time >= log_interval_seconds:
                with mari.lock:
                    mari.log_periodic_metrics()
                last_log_time = current_time

            with mari.lock:
                mari.gateway.update()
                nodes_exist = bool(mari.gateway.nodes)

            if nodes_exist:
                mari.send_frame(MARI_BROADCAST_ADDRESS, NORMAL_DATA_PAYLOAD)

            with mari.lock:
                tui.render(mari)

            time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        tui.close()
        logger.close()


if __name__ == "__main__":
    main()
