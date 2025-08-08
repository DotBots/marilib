import sys
import threading
import time

import click
from marilib.logger import MetricsLogger
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame
from marilib.marilib import MariLib
from marilib.model import EdgeEvent, MariNode, SCHEDULES, TestState
from marilib.serial_uart import get_default_port
from marilib.tui import MariLibTUI

LOAD_PACKET_PAYLOAD = b"L"
NORMAL_DATA_PAYLOAD = b"NORMAL_APP_DATA"

SCHEDULE_ID_TO_NAME = {
    schedule_id: schedule["name"] for schedule_id, schedule in SCHEDULES.items()
}


class LoadTester(threading.Thread):
    def __init__(
        self,
        mari: MariLib,
        test_state: TestState,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.mari = mari
        self.test_state = test_state
        self._stop_event = stop_event

    def run(self):
        if self.test_state.load == 0:
            return
        max_rate = self.mari.get_max_downlink_rate(self.test_state.schedule_id)
        if max_rate == 0:
            sys.stderr.write(
                f"Error: Invalid schedule_id '{self.test_state.schedule_id}'.\n"
            )
            return
        self.test_state.rate = int(max_rate)
        packets_per_second = max_rate * (self.test_state.load / 100.0)
        delay = 1.0 / packets_per_second if packets_per_second > 0 else float("inf")
        while not self._stop_event.is_set():
            with self.mari.lock:
                nodes_exist = bool(self.mari.gateway.nodes)

            if nodes_exist:
                self.mari.send_frame(MARI_BROADCAST_ADDRESS, LOAD_PACKET_PAYLOAD)
            self._stop_event.wait(delay)


def on_event(event: EdgeEvent, event_data: MariNode | Frame):
    """An event handler for the application."""
    pass


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
    "--load",
    type=int,
    default=0,
    show_default=True,
    help="Load percentage to apply (0–100)",
)
@click.option(
    "--log-dir",
    default="logs_metrics",
    show_default=True,
    help="Directory to save metric log files.",
    type=click.Path(),
)
def main(port: str | None, load: int, log_dir: str):
    if not (0 <= load <= 100):
        sys.stderr.write("Error: --load must be between 0 and 100.\n")
        return

    setup_params = {
        "script_name": "mari_edge_stats.py",
        "port": port,
        "load_percentage": load,
    }
    logger = MetricsLogger(
        log_dir_base=log_dir, rotation_interval_minutes=1440, setup_params=setup_params
    )

    mari = MariLib(on_event, port, logger=logger)

    print("Connecting to gateway and waiting for its info packet...")
    gateway_info_received = False
    timeout_seconds = 10
    start_wait = time.time()
    while time.time() - start_wait < timeout_seconds:
        with mari.lock:
            if mari.gateway.info.address != 0:
                gateway_info_received = True
                break
        time.sleep(0.1)

    if not gateway_info_received:
        sys.stderr.write("\nError: Timed out waiting for gateway info.\n")
        logger.close()
        return

    schedule_id = mari.gateway.info.schedule_id
    schedule_name = SCHEDULE_ID_TO_NAME.get(schedule_id, "unknown")
    print(f"Gateway reported schedule: '{schedule_name}' (ID: {schedule_id})")

    setup_params["schedule"] = f"{schedule_name} (auto-detected)"
    logger._log_setup_parameters(setup_params)

    test_state = TestState(
        schedule_id=schedule_id,
        schedule_name=schedule_name,
        load=load,
    )

    tui = MariLibTUI(test_state=test_state)
    stop_event = threading.Event()

    mari.latency_test_enable()

    load_tester = LoadTester(mari, test_state, stop_event)
    if load > 0:
        load_tester.start()

    try:
        log_interval_seconds = 1.0
        normal_traffic_interval = 0.5
        last_log_time = 0
        last_normal_send_time = 0

        while not stop_event.is_set():
            current_time = time.monotonic()

            with mari.lock:
                mari.gateway.update()

                if current_time - last_log_time >= log_interval_seconds:
                    mari.log_periodic_metrics()
                    last_log_time = current_time

                tui.render(mari)

            if current_time - last_normal_send_time >= normal_traffic_interval:
                with mari.lock:
                    nodes_exist = bool(mari.gateway.nodes)
                if nodes_exist:
                    mari.send_frame(MARI_BROADCAST_ADDRESS, NORMAL_DATA_PAYLOAD)
                last_normal_send_time = current_time

            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        mari.latency_test_disable()
        if load_tester.is_alive():
            load_tester.join()
        tui.close()
        logger.close()


if __name__ == "__main__":
    main()
