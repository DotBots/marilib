from datetime import datetime, timedelta

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marilib import MarilibCloud
from marilib.model import MariGateway
from marilib.tui import MarilibTUI


class MarilibTUICloud(MarilibTUI):
    """A Text-based User Interface for MarilibCloud."""

    def __init__(
        self,
        max_tables=4,
        re_render_max_freq=0.2,
    ):
        self.console = Console()
        self.live = Live(console=self.console, auto_refresh=False, transient=True)
        self.live.start()
        self.max_tables = max_tables
        self.re_render_max_freq = re_render_max_freq
        self.last_render_time = datetime.now()

    def get_max_rows(self) -> int:
        """Calculate maximum rows based on terminal height."""
        terminal_height = self.console.height
        available_height = terminal_height - 10 - 2 - 2 - 1 - 2
        return max(2, available_height)

    def render(self, mari: MarilibCloud):
        """Render the TUI layout."""
        with mari.lock:
            if datetime.now() - self.last_render_time < timedelta(seconds=self.re_render_max_freq):
                return
            self.last_render_time = datetime.now()
            layout = Layout()
            layout.split(
                Layout(self.create_header_panel(mari), size=6),
                Layout(self.create_gateways_panel(mari)),
            )
            self.live.update(layout, refresh=True)

    def create_header_panel(self, mari: MarilibCloud) -> Panel:
        """Create the header panel with MQTT connection and network info."""
        status = Text()
        status.append("MarilibCloud is ", style="bold")
        status.append("connected", style="bold green")
        status.append(
            f" to MQTT broker {mari.mqtt_interface.host}:{mari.mqtt_interface.port} "
            f"at topic /mari/{mari.network_id_str}/to_cloud "
            f"since {mari.started_ts.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        status.append("  |  ")
        secs = int((datetime.now() - mari.last_received_mqtt_data_ts).total_seconds())
        status.append(
            f"last received: {secs}s ago",
            style="bold green" if secs <= 1 else "bold red",
        )

        status.append("\n\nNetwork ID: ", style="bold cyan")
        status.append(f"0x{mari.network_id:04X}")
        status.append("  |  ")
        status.append("Gateways: ", style="bold cyan")
        status.append(f"{len(mari.gateways)}")
        status.append("  |  ")
        status.append("Nodes: ", style="bold cyan")
        status.append(f"{len(mari.nodes)}")

        return Panel(status, title="[bold]MarilibCloud Status", border_style="blue")

    def create_gateway_table(self, gateway: MariGateway) -> Table:
        """Create a table for a single gateway with 3 rows and 2 columns."""
        table = Table(
            show_header=False,
            border_style="blue",
            padding=(0, 1),
        )
        table.add_column("Field", style="bold", width=18, justify="right")
        table.add_column("Value")

        # Row 1: Gateway info
        node_count = f"{len(gateway.nodes)} / {gateway.info.schedule_uplink_cells}"
        schedule_info = f"#{gateway.info.schedule_id} {gateway.info.schedule_name}"

        # --- Latency and PDR Display ---
        avg_latency_edge = gateway.stats_avg_latency_roundtrip_node_edge_ms()
        has_latency_info = avg_latency_edge > 0

        # Check if we have PDR info by looking at the gateway averages
        avg_uart_pdr_up = gateway.stats_avg_pdr_uplink_uart()
        avg_uart_pdr_down = gateway.stats_avg_pdr_downlink_uart()
        has_uart_pdr_info = avg_uart_pdr_up > 0 or avg_uart_pdr_down > 0

        avg_radio_pdr_down = gateway.stats_avg_pdr_downlink_radio()
        avg_radio_pdr_up = gateway.stats_avg_pdr_uplink_radio()
        has_radio_pdr_info = avg_radio_pdr_down > 0 or avg_radio_pdr_up > 0

        latency_info = f"  |  Latency: {avg_latency_edge:.1f}ms" if has_latency_info else ""
        pdr_info = "  |  PDR:" if has_uart_pdr_info or has_radio_pdr_info else ""
        radio_pdr_info = (
            f"  Radio ↓ {avg_radio_pdr_down:.1%} ↑ {avg_radio_pdr_up:.1%}"
            if has_radio_pdr_info
            else ""
        )
        uart_pdr_info = (
            f"  UART ↓ {avg_uart_pdr_down:.1%} ↑ {avg_uart_pdr_up:.1%}" if has_uart_pdr_info else ""
        )

        table.add_row(
            f"[bold cyan]0x{gateway.info.address:016X}[/bold cyan]",
            f"Nodes: {node_count}  |  Schedule: {schedule_info}{latency_info}{pdr_info}{radio_pdr_info}{uart_pdr_info}",
        )

        # Row 2: Schedule usage
        schedule_repr = gateway.info.repr_schedule_cells_with_colors()
        table.add_row("[bold cyan]Live schedule[/bold cyan]", schedule_repr)

        # Row 3: Node list
        if gateway.nodes:
            node_addresses = [f"0x{node.address:016X}" for node in gateway.nodes]
            node_display = " ".join(node_addresses)
        else:
            node_display = "—"

        table.add_row("[bold cyan]Nodes[/bold cyan]", node_display)

        return table

    def create_gateways_panel(self, mari: MarilibCloud) -> Panel:
        """Create the panel that contains individual gateway tables."""
        gateways = list(mari.gateways.values())

        if not gateways:
            empty_table = Table(title="No Gateways Connected")
            return Panel(
                empty_table,
                title="[bold]Connected Gateways",
                border_style="blue",
            )

        # Create individual tables for each gateway
        gateway_tables = []
        max_displayable_gateways = self.max_tables
        gateways_to_display = gateways[:max_displayable_gateways]
        remaining_gateways = max(0, len(gateways) - max_displayable_gateways)

        for gateway in gateways_to_display:
            gateway_tables.append(self.create_gateway_table(gateway))

        # Arrange tables in columns
        if len(gateway_tables) > 1:
            content = Columns(gateway_tables, equal=True, expand=True)
        else:
            content = gateway_tables[0]

        if remaining_gateways > 0:
            panel_content = Group(
                content,
                Text(
                    f"\n...and {remaining_gateways} more gateway(s)",
                    style="bold yellow",
                ),
            )
        else:
            panel_content = content

        return Panel(
            panel_content,
            title="[bold]Connected Gateways",
            border_style="blue",
        )

    def close(self):
        """Clean up the live display."""
        self.live.stop()
        print("")
