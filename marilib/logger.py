import csv
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import IO, List, Dict

from marilib.model import MariGateway, MariNode


@dataclass
class MetricsLogger:
    """
    A metrics logger that saves statistics to CSV files with log rotation.
    """

    log_dir_base: str = "logs"
    rotation_interval_minutes: int = 1440  # 1 day
    already_logged_setup_parameters: bool = False
    log_interval_seconds: float = 1.0
    last_log_time: Dict[int, datetime] = field(default_factory=dict)

    def __post_init__(self):
        """
        Initializes the logger with rotation and setup logging capabilities.
        """
        try:
            self.rotation_interval = timedelta(minutes=self.rotation_interval_minutes)

            self.start_time = datetime.now()
            self.run_timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            self.log_dir = os.path.join(self.log_dir_base, f"run_{self.run_timestamp}")
            os.makedirs(self.log_dir, exist_ok=True)

            self._gateway_file: IO[str] | None = None
            self._nodes_file: IO[str] | None = None
            self._events_file: IO[str] | None = None
            self._gateway_writer = None
            self._nodes_writer = None
            self._events_writer = None
            self.segment_start_time: datetime | None = None

            # Open events log file
            events_path = os.path.join(self.log_dir, "log_events.csv")
            self._events_file = open(events_path, "w", newline="", encoding="utf-8")
            self._events_writer = csv.writer(self._events_file)
            self._events_writer.writerow(
                ["timestamp", "gateway_address", "node_address", "event_name", "event_tag"]
            )

            self._open_new_segment()
            self.active = True

        except (IOError, OSError) as e:
            print(f"Error: Failed to initialize logger: {e}")
            self.active = False

    def log_setup_parameters(self, params: Dict[str, any] | None):
        """Creates and writes test setup parameters to metrics_setup.csv."""
        if not params or self.already_logged_setup_parameters:
            return
        # only log setup parameters once
        self.already_logged_setup_parameters = True

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
            "gateway_address",
            "schedule_id",
            "connected_nodes",
            # "tx_total",
            # "rx_total",
            # "tx_rate_1s",
            # "rx_rate_1s",
            "avg_latency_ms",
            "avg_pdr_downlink_radio",
            "avg_pdr_uplink_radio",
            "latest_node_tx_count",
            "latest_node_rx_count",
            "latest_gw_tx_count",
            "latest_gw_rx_count",
        ]
        self._gateway_writer.writerow(gateway_header)

        self._nodes_file = open(nodes_path, "w", newline="", encoding="utf-8")
        self._nodes_writer = csv.writer(self._nodes_file)
        nodes_header = [
            "timestamp",
            "gateway_address",
            "node_address",
            "is_alive",
            # "tx_total",
            # "rx_total",
            # "tx_rate_1s",
            # "rx_rate_1s",
            "success_rate_30s",
            "success_rate_total",
            "pdr_downlink",
            "pdr_uplink",
            "rssi_node_dbm",
            "rssi_gw_dbm",
            "avg_latency_edge_ms",
            "avg_latency_cloud_ms",
            "last_latency_edge_ms",
            "last_latency_cloud_ms",
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

    def log_periodic_metrics(self, gateway: MariGateway, nodes: List[MariNode]):
        last_log_time = self.last_log_time.get(gateway.info.address, self.segment_start_time)
        if datetime.now() - last_log_time >= timedelta(seconds=self.log_interval_seconds):
            self.log_gateway_metrics(gateway)
            self.log_all_nodes_metrics(nodes)
            self.last_log_time[gateway.info.address] = datetime.now()

    def log_gateway_metrics(self, gateway: MariGateway):
        if not self._log_common() or self._gateway_writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [
            timestamp,
            f"0x{gateway.info.address:016X}",
            gateway.info.schedule_id,
            len(gateway.nodes),
            # gateway.stats.sent_count(include_test_packets=False),
            # gateway.stats.received_count(include_test_packets=False),
            # gateway.stats.sent_count(1, include_test_packets=False),
            # gateway.stats.received_count(1, include_test_packets=False),
            f"{gateway.stats_avg_latency_roundtrip_node_edge_ms():.2f}",
            f"{gateway.stats_avg_pdr_downlink_radio():.2f}",
            f"{gateway.stats_avg_pdr_uplink_radio():.2f}",
            gateway.stats_latest_node_tx_count(),
            gateway.stats_latest_node_rx_count(),
            gateway.stats_latest_gw_tx_count(),
            gateway.stats_latest_gw_rx_count(),
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
                f"0x{node.gateway_address:016X}",
                f"0x{node.address:016X}",
                node.is_alive,
                # node.stats.sent_count(include_test_packets=False),
                # node.stats.received_count(include_test_packets=False),
                # node.stats.sent_count(1, include_test_packets=False),
                # node.stats.received_count(1, include_test_packets=False),
                f"{node.stats.success_rate(30):.2%}",
                f"{node.stats.success_rate():.2%}",
                f"{node.pdr_downlink:.2%}",
                f"{node.pdr_uplink:.2%}",
                node.stats_rssi_node_dbm(),
                node.stats_rssi_gw_dbm(),
                f"{node.stats_avg_latency_roundtrip_node_edge_ms():.2f}",
                f"{node.stats_avg_latency_roundtrip_node_edge_ms():.2f}",  # FIXME!: should use cloud option
                f"{node.stats_latest_latency_roundtrip_node_edge_ms():.2f}",
                f"{node.stats_latest_latency_roundtrip_node_edge_ms():.2f}",  # FIXME!: should use cloud option
            ]
            self._nodes_writer.writerow(row)

    def log_event(
        self, gateway_address: int, node_address: int, event_name: str, event_tag: str = ""
    ):
        """Logs an event to the events log file."""
        if not self.active or self._events_writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [
            timestamp,
            f"0x{gateway_address:016X}",
            f"0x{node_address:016X}",
            event_name,
            event_tag,
        ]
        self._events_writer.writerow(row)
        if self._events_file:
            self._events_file.flush()

    def _close_segment_files(self):
        if self._gateway_file and not self._gateway_file.closed:
            self._gateway_file.close()
        if self._nodes_file and not self._nodes_file.closed:
            self._nodes_file.close()

    def close(self):
        if not self.active:
            return

        self._close_segment_files()
        if self._events_file and not self._events_file.closed:
            self._events_file.close()
        print(f"\nMetrics saved to: {self.log_dir}")
        self.active = False
