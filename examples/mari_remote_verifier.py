import time

import click
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, MARI_NET_ID_DEFAULT, Frame
from marilib.marilib_cloud import MarilibCloud
from marilib.model import EdgeEvent, GatewayInfo, MariNode
from marilib.communication_adapter import MQTTAdapter
from marilib.tui_cloud import MarilibTUICloud
from marilib.logger import MetricsLogger

from marilib.marilib_remote_verifier import mr_swarm_verification_result

NORMAL_DATA_PAYLOAD = b"NORMAL_APP_DATA"
mari_instance = None

def on_event(event: EdgeEvent, event_data: MariNode | Frame | GatewayInfo):
    """An event handler for the application."""
    global mari_instance
    if event == EdgeEvent.NODE_DATA:  # Event 3
        frame: Frame = event_data
        h = frame.header
        print(
            f"RX frame: src=0x{h.source:04X} -> dst=0x{h.destination:04X} "
            f"type={h.type_} len={len(frame.payload)} " 
            f"payload(hex)={frame.payload.hex()}"
        )
        p = frame.payload
        try:
            verification_response = mr_swarm_verification_result(p)
            print(f"Verification response (hex): {verification_response.hex()}")
            node_id = frame.header.source
            mari_instance.send_frame(node_id, verification_response)
            print(f"Verifier: VR ok: node=0x{node_id:04X} req_len={len(p)} resp_len={len(verification_response)}")
        except Exception as e:
            print(f"Verifier VR error: {e}")
    


@click.command()
@click.option(
    "--mqtt-url",
    "-m",
    type=str,
    default="mqtt://localhost:1883",
    show_default=True,
    help="MQTT broker to use",
)
@click.option(
    "--network-id",
    "-n",
    type=lambda x: int(x, 16),
    default=MARI_NET_ID_DEFAULT,
    help=f"Network ID to use [default: 0x{MARI_NET_ID_DEFAULT:04X}]",
)
@click.option(
    "--log-dir",
    default="logs",
    show_default=True,
    help="Directory to save metric log files.",
    type=click.Path(),
)
def main(mqtt_url: str, network_id: int, log_dir: str):
    """A basic example of using the MariLibCloud library."""
    global mari_instance

    mari = MarilibCloud(
        on_event,
        mqtt_interface=MQTTAdapter.from_url(mqtt_url, is_edge=False),
        logger=MetricsLogger(
            log_dir_base=log_dir, rotation_interval_minutes=1440, log_interval_seconds=1.0
        ),
        network_id=network_id,
        tui=MarilibTUICloud(),
        main_file=__file__,
    )

    mari_instance = mari

    try:
        while True:
            mari.update()
            if mari.nodes:
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
