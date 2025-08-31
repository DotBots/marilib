import time

import click
from marilib.logger import MetricsLogger
from marilib.mari_protocol import Frame, MARI_BROADCAST_ADDRESS
from marilib.model import EdgeEvent, MariNode
from marilib.communication_adapter import SerialAdapter, MQTTAdapter
from marilib.serial_uart import get_default_port
from marilib.tui_edge import MarilibTUIEdge
from marilib.marilib_edge import MarilibEdge

NORMAL_DATA_PAYLOAD = b"NORMAL_APP_DATA"


# def on_event(event: EdgeEvent, event_data: MariNode | Frame):
#     """An event handler for the application."""
#     pass

def on_event(event: EdgeEvent, event_data: MariNode | Frame):
    if event == EdgeEvent.NODE_DATA:  # Event 3
        frame: Frame = event_data
        h = frame.header
        print(
            f"RX frame: src=0x{h.source:04X} -> dst=0x{h.destination:04X} "
            f"type={h.type_} len={len(frame.payload)} " 
            f"payload(hex)={frame.payload.hex()}"
        )


@click.command()
@click.option(
    "--port",
    "-p",
    type=str,
    default=get_default_port(),
    show_default=True,
    help="Serial port to use (e.g., /dev/ttyACM0)",
)
@click.option(
    "--mqtt-url",
    "-m",
    type=str,
    default="mqtt://localhost:1883",
    show_default=True,
    help="MQTT broker to use (default: empty, no cloud)",
)
@click.option(
    "--log-dir",
    default="logs",
    show_default=True,
    help="Directory to save metric log files.",
    type=click.Path(),
)
def main(port: str | None, mqtt_url: str, log_dir: str):
    """A basic example of using the MarilibEdge library."""

    mari = MarilibEdge(
        on_event,
        serial_interface=SerialAdapter(port),
        mqtt_interface=MQTTAdapter.from_url(mqtt_url, is_edge=True) if mqtt_url else None,
        logger=MetricsLogger(
            log_dir_base=log_dir, rotation_interval_minutes=1440, log_interval_seconds=1.0
        ),
        tui=MarilibTUIEdge(),
        main_file=__file__,
    )

    try:
        while True:
            mari.update()
            if not mari.uses_mqtt and mari.nodes:
                mari.send_frame(MARI_BROADCAST_ADDRESS, NORMAL_DATA_PAYLOAD)
            mari.render_tui()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        mari.close_tui()
        mari.logger.close()


if __name__ == "__main__":
    main()
