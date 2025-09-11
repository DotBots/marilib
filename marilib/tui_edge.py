from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marilib.model import MariNode, TestState
from marilib.tui import MarilibTUI

if TYPE_CHECKING:
    from marilib.marilib_edge import MarilibEdge


class MarilibTUIEdge(MarilibTUI):
    """A Text-based User Interface for MarilibEdge."""

    def __init__(
        self,
        max_tables=3,
        re_render_max_freq=0.2,
        test_state: TestState | None = None,
    ):
        self.console = Console()
        self.live = Live(console=self.console, auto_refresh=False, transient=True)
        self.live.start()
        self.max_tables = max_tables
        self.re_render_max_freq = re_render_max_freq
        self.last_render_time = datetime.now()
        self.test_state = test_state

    def get_max_rows(self) -> int:
        """Calculate maximum rows based on terminal height."""
        terminal_height = self.console.height
        available_height = terminal_height - 10 - 2 - 2 - 1 - 2
        return max(2, available_height)

    def render(self, mari: "MarilibEdge"):
        """Render the TUI layout."""
        with mari.lock:
            if datetime.now() - self.last_render_time < timedelta(seconds=self.re_render_max_freq):
                return
            self.last_render_time = datetime.now()
            layout = Layout()
            layout.split(
                Layout(self.create_header_panel(mari), size=12),
                Layout(self.create_nodes_panel(mari)),
            )
            self.live.update(layout, refresh=True)

    def create_header_panel(self, mari: "MarilibEdge") -> Panel:
        """Create the header panel with gateway and network stats."""
        status = Text()

        # UART Status Line
        status.append("UART: ", style="bold cyan")
        status.append(
            "connected" if mari.serial_connected else "disconnected",
            style="bold green" if mari.serial_connected else "bold red",
        )
        if mari.serial_connected:
            status.append(
                f" via {mari.serial_interface.port} at {mari.serial_interface.baudrate} baud "
            )
        secs = int((datetime.now() - mari.last_received_serial_data_ts).total_seconds())
        status.append(
            f"(last: {secs}s ago)",
            style="bold green" if secs <= 1 else "bold red",
        )

        status.append("  |  ")

        # MQTT Status Line
        status.append("MQTT: ", style="bold cyan")
        if mari.uses_mqtt:
            status.append(
                "connected" if mari.mqtt_connected else "disconnected",
                style="bold green" if mari.mqtt_connected else "bold red",
            )
            if mari.mqtt_connected:
                status.append(f" to {mari.mqtt_interface.host}:{mari.mqtt_interface.port} ")
            mqtt_secs = int((datetime.now() - mari.last_received_mqtt_data_ts).total_seconds())
            status.append(
                f"(last: {mqtt_secs}s ago)",
                style="bold green" if mqtt_secs <= 1 else "bold red",
            )
        else:
            status.append("disabled", style="bold yellow")

        status.append("\n\nGateway:  ", style="bold cyan")
        status.append(f"0x{mari.gateway.info.address:016X}  |  ")
        status.append("Network ID: ", style="bold cyan")
        status.append(f"0x{mari.gateway.info.network_id:04X}  |  ")
        status.append("ASN: ", style="bold cyan")
        status.append(f"{mari.gateway.info.asn:020d}")

        status.append("\n\n")
        status.append("Schedule: ", style="bold cyan")
        status.append(f"#{mari.gateway.info.schedule_id} {mari.gateway.info.schedule_name} |  ")
        status.append(f"{len(mari.gateway.nodes)} / {mari.gateway.info.max_nodes} nodes  |  ")
        status.append(mari.gateway.info.repr_schedule_cells_with_colors())

        # --- Latency and PDR Display ---
        avg_latency_edge = mari.gateway.stats_avg_latency_roundtrip_node_edge_ms()
        has_latency_info = avg_latency_edge > 0

        # Check if we have PDR info by looking at the gateway averages
        avg_uart_pdr_up = mari.gateway.stats_avg_pdr_uplink_uart()
        avg_uart_pdr_down = mari.gateway.stats_avg_pdr_downlink_uart()
        has_uart_pdr_info = avg_uart_pdr_up > 0 or avg_uart_pdr_down > 0

        avg_radio_pdr_down = mari.gateway.stats_avg_pdr_downlink_radio()
        avg_radio_pdr_up = mari.gateway.stats_avg_pdr_uplink_radio()
        has_radio_pdr_info = avg_radio_pdr_down > 0 or avg_radio_pdr_up > 0

        pdr_info = "  |  PDR:" if has_uart_pdr_info or has_radio_pdr_info else ""
        radio_pdr_info = (
            f"  Radio ↓ {avg_radio_pdr_down:.1%} ↑ {avg_radio_pdr_up:.1%}"
            if has_radio_pdr_info
            else ""
        )
        uart_pdr_info = (
            f"  UART ↓ {avg_uart_pdr_down:.1%} ↑ {avg_uart_pdr_up:.1%}" if has_uart_pdr_info else ""
        )

        if has_latency_info or has_uart_pdr_info or has_radio_pdr_info:
            status.append("\n\n")

        # Display Latency
        if has_latency_info:
            status.append("Latency:  ", style="bold yellow")
            status.append(f"Avg: {avg_latency_edge:.1f}ms")

        # Display PDR
        status.append(f"{pdr_info}{radio_pdr_info}{uart_pdr_info}")

        status.append("\n\nStats:    ", style="bold yellow")
        if self.test_state and self.test_state.load > 0 and self.test_state.rate > 0:
            status.append(
                "Test load: ",
            )
            status.append(f"{self.test_state.load}% of {self.test_state.rate} pps")
            status.append("  |  ")

        stats = mari.gateway.stats
        status.append(f"Frames TX: {stats.sent_count(include_test_packets=True)}  |  ")
        status.append(f"Frames RX: {stats.received_count(include_test_packets=True)} |  ")
        status.append(f"TX/s: {stats.sent_count(1, include_test_packets=True)}  |  ")
        status.append(f"RX/s: {stats.received_count(1, include_test_packets=True)}")

        return Panel(
            status,
            title=f"[bold]MariEdge running since {mari.started_ts.strftime('%Y-%m-%d %H:%M:%S')}",
            border_style="blue",
        )

    def create_nodes_table(self, nodes: list[MariNode], title="") -> Table:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            padding=(0, 1),
            title=title,
        )
        table.add_column("Node Address", style="cyan")
        table.add_column("TX", justify="right")
        table.add_column("/s", justify="right")
        table.add_column("RX", justify="right")
        table.add_column("/s", justify="right")
        table.add_column("Radio ↓ PDR | RSSI", justify="center")
        table.add_column("Radio ↑ PDR | RSSI", justify="center")
        table.add_column("UART PDR ↓ | ↑", justify="center")
        table.add_column("Latency", justify="center")

        for node in nodes:
            lat_str = (
                f"{node.stats_avg_latency_roundtrip_node_edge_ms():.1f} ms"
                if node.stats_avg_latency_roundtrip_node_edge_ms() > 0
                else "..."
            )
            # PDR Downlink with color coding
            if node.stats_pdr_downlink_radio() > 0:
                if node.stats_pdr_downlink_radio() > 0.9:
                    pdr_down_str = f"[white]{node.stats_pdr_downlink_radio():>4.0%}[/white]"
                elif node.stats_pdr_downlink_radio() > 0.8:
                    pdr_down_str = f"[yellow]{node.stats_pdr_downlink_radio():>4.0%}[/yellow]"
                else:
                    pdr_down_str = f"[red]{node.stats_pdr_downlink_radio():>4.0%}[/red]"
            else:
                pdr_down_str = "..."

            # PDR Uplink with color coding
            if node.stats_pdr_uplink_radio() > 0:
                if node.stats_pdr_uplink_radio() > 0.9:
                    pdr_up_str = f"[white]{node.stats_pdr_uplink_radio():>4.0%}[/white]"
                elif node.stats_pdr_uplink_radio() > 0.8:
                    pdr_up_str = f"[yellow]{node.stats_pdr_uplink_radio():>4.0%}[/yellow]"
                else:
                    pdr_up_str = f"[red]{node.stats_pdr_uplink_radio():>4.0%}[/red]"
            else:
                pdr_up_str = "..."

            # PDR UART Up / Down with color coding
            if node.stats_pdr_downlink_uart() > 0:
                if node.stats_pdr_downlink_uart() > 0.9:
                    pdr_down_gw_edge_str = f"[white]{node.stats_pdr_downlink_uart():>4.0%}[/white]"
                elif node.stats_pdr_downlink_uart() > 0.8:
                    pdr_down_gw_edge_str = (
                        f"[yellow]{node.stats_pdr_downlink_uart():>4.0%}[/yellow]"
                    )
                else:
                    pdr_down_gw_edge_str = f"[red]{node.stats_pdr_downlink_uart():>4.0%}[/red]"
            else:
                pdr_down_gw_edge_str = "..."

            if node.stats_pdr_uplink_uart() > 0:
                if node.stats_pdr_uplink_uart() > 0.9:
                    pdr_up_gw_edge_str = f"[white]{node.stats_pdr_uplink_uart():>4.0%}[/white]"
                elif node.stats_pdr_uplink_uart() > 0.8:
                    pdr_up_gw_edge_str = f"[yellow]{node.stats_pdr_uplink_uart():>4.0%}[/yellow]"
                else:
                    pdr_up_gw_edge_str = f"[red]{node.stats_pdr_uplink_uart():>4.0%}[/red]"
            else:
                pdr_up_gw_edge_str = "..."

            rssi_node_str = (
                f"{node.stats_rssi_node_dbm():.0f}"
                if node.stats_rssi_node_dbm() is not None
                else "..."
            )
            rssi_gw_str = (
                f"{node.stats_rssi_gw_dbm():.0f}" if node.stats_rssi_gw_dbm() is not None else "..."
            )

            table.add_row(
                f"0x{node.address:016X}",
                str(node.stats.sent_count(include_test_packets=True)),
                str(node.stats.sent_count(1, include_test_packets=True)),
                str(node.stats.received_count(include_test_packets=True)),
                str(node.stats.received_count(1, include_test_packets=True)),
                f"{pdr_down_str} | {rssi_node_str} dBm",
                f"{pdr_up_str} | {rssi_gw_str} dBm",
                f"{pdr_down_gw_edge_str} | {pdr_up_gw_edge_str}",
                lat_str,
            )
        return table

    def create_nodes_panel(self, mari: "MarilibEdge") -> Panel:
        """Create the panel that contains the nodes table."""
        nodes = mari.gateway.nodes
        max_rows = self.get_max_rows()
        max_displayable_nodes = self.max_tables * max_rows
        nodes_to_display = nodes[:max_displayable_nodes]
        remaining_nodes = max(0, len(nodes) - max_displayable_nodes)
        tables = []
        current_table_nodes = []
        for i, node in enumerate(nodes_to_display):
            current_table_nodes.append(node)
            if len(current_table_nodes) == max_rows or i == len(nodes_to_display) - 1:
                title = f"Nodes {i - len(current_table_nodes) + 2}-{i + 1}"
                tables.append(self.create_nodes_table(current_table_nodes, title))
                current_table_nodes = []
                if len(tables) >= self.max_tables:
                    break
        if len(tables) > 1:
            content = Columns(tables, equal=True, expand=True)
        else:
            content = tables[0] if tables else Table()
        if remaining_nodes > 0:
            panel_content = Group(
                content,
                Text(
                    f"\n(...and {remaining_nodes} more nodes)",
                    style="bold yellow",
                ),
            )
        else:
            panel_content = content
        return Panel(
            panel_content,
            title="[bold]Connected Nodes",
            border_style="blue",
        )

    def close(self):
        """Clean up the live display."""
        self.live.stop()
        print("")
