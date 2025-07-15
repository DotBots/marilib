from datetime import datetime, timedelta

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mira_edge.mira_edge import MiraEdge


class MiraEdgeTUI:
    def __init__(self, max_tables=3, re_render_max_freq=0.2):
        self.console = Console()
        self.live = Live(console=self.console, auto_refresh=False, transient=True)
        self.live.start()
        self.max_tables = max_tables
        self.re_render_max_freq = re_render_max_freq # seconds
        self.last_render_time = datetime.now()

    def get_max_rows(self) -> int:
        """Calculate maximum rows based on terminal height.

        Takes into account:
        - Header panel (8 lines)
        - Panel borders (2 lines)
        - Table header (2 lines)
        - Footer space for "more nodes" message (1 line)
        - Extra space manually added (2 lines)
        """
        terminal_height = self.console.height
        available_height = terminal_height - 8 - 2 - 2 - 1 - 2
        return max(2, available_height)  # Minimum 2 rows to always show something

    def render(self, mira: MiraEdge):
        if datetime.now() - self.last_render_time < timedelta(seconds=self.re_render_max_freq):
            return
        self.last_render_time = datetime.now()

        # Create layout
        layout = Layout()

        # Create a layout with both components
        layout.split(
            Layout(self.create_header_panel(mira), size=8),
            Layout(self.create_nodes_panel(mira)),
        )

        # Update display
        self.live.update(layout, refresh=True)

    def create_header_panel(self, mira: MiraEdge) -> Panel:
        status = Text()
        status.append("MiraEdge", style="bold cyan")
        status.append(" is ", style="bold")
        if mira.serial_connected:
            status.append("connected", style="bold green")
        else:
            status.append("disconnected", style="bold red")
        status.append(f" via {mira.port} at {mira.baudrate} baud")
        status.append(f" since {mira.started_ts.strftime('%Y-%m-%d %H:%M:%S')}")
        status.append("  |  ")
        secs = int((datetime.now() - mira.last_received_serial_data).total_seconds())
        style = "bold green" if secs <= 1 else "bold red"
        status.append(f"last received: {secs}s ago", style=style)
        status.append("\n\n")

        # Gateway info
        status.append("Gateway: ", style="bold cyan")
        status.append(f"0x{mira.gateway.info.address:016X}  |  ")
        status.append("Network ID: ", style="bold cyan")
        status.append(f"{mira.gateway.info.network_id}  |  ")
        status.append("Schedule ID: ", style="bold cyan")
        status.append(f"{mira.gateway.info.schedule_id}\n")

        # Network stats
        status.append("\nStats:    ", style="bold yellow")
        status.append("Nodes: ", style="bold cyan")
        status.append(f"{len(mira.gateway.nodes)}  |  ")
        status.append("Frames TX: ", style="bold cyan")
        status.append(f"{mira.gateway.stats.sent_count()}  |  ")
        status.append("Frames RX: ", style="bold cyan")
        status.append(f"{mira.gateway.stats.received_count()} |  ")
        status.append("TX/s: ", style="bold cyan")
        status.append(f"{mira.gateway.stats.sent_count(1)}  |  ")
        status.append("RX/s: ", style="bold cyan")
        status.append(f"{mira.gateway.stats.received_count(1)}")
        # status.append(f"  |  ")
        # FIXME: this statistics should be computed differently for broadcasted frames, that's why it's commented out for now
        # status.append("  |  ")
        # status.append("SR' (30s): ", style="bold cyan")
        # status.append(f"{mira.gateway.stats.success_rate(30):.2%}")

        return Panel(status, title="[bold]MiraEdge Status", border_style="blue")

    def create_nodes_table(self, nodes, title="") -> Table:
        """Create a table for a subset of nodes."""
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            padding=(0, 1),
            title=title,
        )

        # Add columns
        table.add_column("Node Address", style="cyan")
        table.add_column("TX", justify="right")
        table.add_column("TX/s", justify="right")
        table.add_column("RX", justify="right")
        table.add_column("RX/s", justify="right")
        table.add_column("SR", justify="right")
        table.add_column("RSSI", justify="right")

        # Add rows for each node
        for node in nodes:
            table.add_row(
                f"0x{node.address:016X}",
                str(node.stats.sent_count()),
                str(node.stats.sent_count(1)),
                str(node.stats.received_count()),
                str(node.stats.received_count(1)),
                f"{node.stats.success_rate(30):>4.0%}",
                f"{node.stats.received_rssi_dbm(5)}",
            )

        return table

    def create_nodes_panel(self, mira: MiraEdge) -> Panel:
        """Create a panel containing the nodes tables."""
        nodes = mira.gateway.nodes
        total_nodes = len(nodes)
        max_rows = self.get_max_rows()

        # Calculate how many nodes we can show
        max_displayable_nodes = self.max_tables * max_rows
        nodes_to_display = nodes[:max_displayable_nodes]
        remaining_nodes = max(0, total_nodes - max_displayable_nodes)

        # Create tables
        tables = []
        current_table_nodes = []

        for i, node in enumerate(nodes_to_display):
            current_table_nodes.append(node)

            # Create a new table when we hit max rows or last node
            if len(current_table_nodes) == max_rows or i == len(nodes_to_display) - 1:
                start_idx = i - len(current_table_nodes) + 1
                end_idx = i + 1
                title = f"Nodes {start_idx + 1}-{end_idx}"
                tables.append(self.create_nodes_table(current_table_nodes, title))
                current_table_nodes = []

                # Stop if we've hit max tables
                if len(tables) >= self.max_tables:
                    break

        # Create the layout
        if len(tables) > 1:
            content = Columns(tables, equal=True, expand=True)
        else:
            content = tables[0] if tables else Table()

        # Create the panel content with optional footer
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

        return Panel(panel_content, title="[bold]Connected Nodes", border_style="blue")

    def close(self):
        """Clean up the live display."""
        self.live.stop()
        # Move cursor to a new line to ensure prompt appears correctly
        print("")
