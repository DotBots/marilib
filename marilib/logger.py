import csv
import os
from datetime import datetime, timedelta
from typing import IO, List, Dict

from marilib.model import MariGateway, MariNode


class MetricsLogger:
    """
    A metrics logger that saves statistics to CSV files with log rotation.
    """

    def __init__(
        self,
        log_dir_base: str = "logs",
        rotation_interval_minutes: int = 1,
        setup_params: Dict[str, any] | None = None,
    ):
        """
        Initializes the logger with rotation and setup logging capabilities.
        """
        try:
            self.log_dir_base = log_dir_base
            self.rotation_interval = timedelta(minutes=rotation_interval_minutes)

            self.start_time = datetime.now()
            self.run_timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            self.log_dir = os.path.join(self.log_dir_base, f"run_{self.run_timestamp}")
            os.makedirs(self.log_dir, exist_ok=True)

            self._gateway_file: IO[str] | None = None
            self._nodes_file: IO[str] | None = None
            self._gateway_writer = None
            self._nodes_writer = None
            self.segment_start_time: datetime | None = None

            self._log_setup_parameters(setup_params)
            self._open_new_segment()
            self.active = True

        except (IOError, OSError) as e:
            print(f"Error: Failed to initialize logger: {e}")
            self.active = False

    def _log_setup_parameters(self, params: Dict[str, any] | None):
        """Creates and writes test setup parameters to metrics_setup.csv."""
        if not params:
            return

        setup_path = os.path.join(self.log_dir, "metrics_setup.csv")
        with open(setup_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["param", "value"])
            writer.writerow(["start_time", self.start_time.isoformat()])
            for key, value in params.items():
                writer.writerow([key, value])

    def _open_new_segment(self):
        self._close_segment_files()

        self.segment_start_time = datetime.now()
        segment_ts = self.segment_start_time.strftime("%H%M%S")

        gateway_path = os.path.join(self.log_dir, f"gateway_metrics_{segment_ts}.csv")
        nodes_path = os.path.join(self.log_dir, f"node_metrics_{segment_ts}.csv")

        self._gateway_file = open(gateway_path, "w", newline="", encoding="utf-8")
        self._gateway_writer = csv.writer(self._gateway_file)
        gateway_header = [
            "timestamp",
            "connected_nodes",
            "tx_total",
            "rx_total",
            "tx_rate_1s",
            "rx_rate_1s",
            "avg_latency_ms",
        ]
        self._gateway_writer.writerow(gateway_header)

        self._nodes_file = open(nodes_path, "w", newline="", encoding="utf-8")
        self._nodes_writer = csv.writer(self._nodes_file)
        nodes_header = [
            "timestamp",
            "node_address",
            "is_alive",
            "tx_total",
            "rx_total",
            "tx_rate_1s",
            "rx_rate_1s",
            "success_rate_30s",
            "rssi_dbm_5s",
            "last_latency_ms",
            "avg_latency_ms",
        ]
        self._nodes_writer.writerow(nodes_header)

    def _check_for_rotation(self):
        if datetime.now() - self.segment_start_time >= self.rotation_interval:
            self._open_new_segment()

    def _log_common(self):
        if not self.active:
            return False
        self._check_for_rotation()
        return True

    def log_gateway_metrics(self, gateway: MariGateway):
        if not self._log_common() or self._gateway_writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [
            timestamp,
            len(gateway.nodes),
            gateway.stats.sent_count(),
            gateway.stats.received_count(),
            gateway.stats.sent_count(1),
            gateway.stats.received_count(1),
            f"{gateway.latency_stats.avg_ms:.2f}",
        ]
        self._gateway_writer.writerow(row)

    def log_all_nodes_metrics(self, nodes: List[MariNode]):
        """Writes metrics for all nodes, handling rotation."""
        if not self._log_common() or self._nodes_writer is None:
            return

        timestamp = datetime.now().isoformat()
        for node in nodes:
            row = [
                timestamp,
                f"0x{node.address:016X}",
                node.is_alive,
                node.stats.sent_count(),
                node.stats.received_count(),
                node.stats.sent_count(1),
                node.stats.received_count(1),
                f"{node.stats.success_rate(30):.2%}",
                node.stats.received_rssi_dbm(5),
                f"{node.latency_stats.last_ms:.2f}",
                f"{node.latency_stats.avg_ms:.2f}",
            ]
            self._nodes_writer.writerow(row)

    def _close_segment_files(self):
        if self._gateway_file and not self._gateway_file.closed:
            self._gateway_file.close()
        if self._nodes_file and not self._nodes_file.closed:
            self._nodes_file.close()

    def close(self):
        if not self.active:
            return

        self._close_segment_files()
        print(f"\nMetrics saved to: {self.log_dir}")
        self.active = False
