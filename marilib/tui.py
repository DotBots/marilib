from datetime import datetime, timedelta

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marilib.marilib import MariLib
from marilib.model import MariNode, TestState


class MariLibTUI:
    """A Text-based User Interface for MariLib."""

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

    def render(self, mari: MariLib):
        """Render the TUI layout."""
        if datetime.now() - self.last_render_time < timedelta(
            seconds=self.re_render_max_freq
        ):
            return
        self.last_render_time = datetime.now()
        layout = Layout()
        layout.split(
            Layout(self.create_header_panel(mari), size=10),
            Layout(self.create_nodes_panel(mari)),
        )
        self.live.update(layout, refresh=True)

    def create_header_panel(self, mari: MariLib) -> Panel:
        """Create the header panel with gateway and network stats."""
        status = Text()
        status.append("MariLib Edge is ", style="bold")
        status.append(
            "connected" if mari.serial_connected else "disconnected",
            style="bold green" if mari.serial_connected else "bold red",
        )
        status.append(
            f" via {mari.port} at {mari.baudrate} baud "
            f"since {mari.started_ts.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        status.append("  |  ")
        secs = int((datetime.now() - mari.last_received_serial_data).total_seconds())
        status.append(
            f"last received: {secs}s ago",
            style="bold green" if secs <= 1 else "bold red",
        )

        status.append("\n\nGateway: ", style="bold cyan")
        status.append(f"0x{mari.gateway.info.address:016X}  |  ")
        status.append("Network ID: ", style="bold cyan")
        status.append(f"{mari.gateway.info.network_id}  |  ")
        status.append("Schedule ID: ", style="bold cyan")
        status.append(f"{mari.gateway.info.schedule_id}")
        status.append("  |  ")
        status.append("Schedule Stats: ", style="bold cyan")
        # Convert to binary string, remove '0b' prefix, pad to 137 bits
        status.append(mari.gateway.info.repr_schedule_stats())
        status.append("\n\n")

        if self.test_state and self.test_state.load > 0 and self.test_state.rate > 0:
            status.append("  |  ")
            status.append(
                f"Test ({self.test_state.schedule_name}): ",
                style="bold yellow",
            )
            status.append(f"{self.test_state.load}% of {self.test_state.rate} pps")

        if mari.gateway.latency_stats.last_ms > 0:
            status.append("\n\nLatency: ", style="bold cyan")
            lat = mari.gateway.latency_stats
            status.append(
                f"Last: {lat.last_ms:.1f}ms | Avg: {lat.avg_ms:.1f}ms | "
                f"Min: {lat.min_ms:.1f}ms | Max: {lat.max_ms:.1f}ms"
            )

        status.append("\n\nStats:    ", style="bold yellow")
        stats = mari.gateway.stats
        status.append(f"Nodes: {len(mari.gateway.nodes)}  |  ")
        status.append(f"Frames TX: {stats.sent_count()}  |  ")
        status.append(f"Frames RX: {stats.received_count()} |  ")
        status.append(f"TX/s: {stats.sent_count(1)}  |  ")
        status.append(f"RX/s: {stats.received_count(1)}")

        return Panel(status, title="[bold]MariLib Status", border_style="blue")

    def create_nodes_table(self, nodes: list[MariNode], title="") -> Table:
        """Create a table displaying information about connected nodes."""
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            padding=(0, 1),
            title=title,
        )
        table.add_column("Node Address", style="cyan")
        table.add_column("TX", justify="right")
        table.add_column("TX/s", justify="right")
        table.add_column("RX", justify="right")
        table.add_column("RX/s", justify="right")
        table.add_column("SR", justify="right")
        table.add_column("RSSI", justify="right")
        table.add_column("Latency (ms)", justify="right")
        for node in nodes:
            lat_str = (
                f"{node.latency_stats.avg_ms:.1f}"
                if node.latency_stats.last_ms > 0
                else "..."
            )
            table.add_row(
                f"0x{node.address:016X}",
                str(node.stats.sent_count()),
                str(node.stats.sent_count(1)),
                str(node.stats.received_count()),
                str(node.stats.received_count(1)),
                f"{node.stats.success_rate(30):>4.0%}",
                f"{node.stats.received_rssi_dbm(5)}",
                lat_str,
            )
        return table

    def create_nodes_panel(self, mari: MariLib) -> Panel:
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
