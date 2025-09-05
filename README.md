# MariLib 💫 👀 🐍

MariLib is a Python library to interact with a local [Mari](https://github.com/DotBots/mari) network.
It connects to a Mari gateway via:
- UART, using MarilibEdge
- MQTT, using MarilibCloud

## Example with TUI
MariLib provides a stateful class with gateway and node information, network statistics, and a rich real-time TUI:

[mari-edge-2.webm](https://github.com/user-attachments/assets/fe50f2ba-8e67-4522-8700-69730f8e3aee)

To run with a gateway connected via UART:
```bash
# for example, using the Inria Argus MQTT broker
(.venv) $ python examples/mari_edge.py -m mqtts://argus.paris.inria.fr:8883
```
You can see how it works using `examples/mari_edge.py --help`.

To run with a gateway connected via MQTT:
```bash
# for example, using the Inria Argus MQTT broker
(.venv) $ python examples/mari_cloud.py -n 0x0100 -m mqtts://argus.paris.inria.fr:8883
```

## Setup and dependencies
To setup the environment, do:

```bash
$ python -m venv .venv
$ source .venv/bin/activate
(.venv) $ pip install -e .
```

## Minimal example
Here is a minimal example showcasing how to use MariLib:

```python
import time
from marilib.marilib import MarilibEdge
from marilib.serial_uart import get_default_port

def main():
    mari = MarilibEdge(lambda event, data: print(event.name, data), get_default_port())
    while True:
        for node in mari.gateway.nodes:
            mari.send_frame(dst=node.address, payload=b"A" * 3)
        statistics = [(f"{node.address:016X}", node.stats.received_rssi_dbm()) for node in mari.gateway.nodes]
        print(f"Network statistics: {statistics}")
        time.sleep(0.25)

if __name__ == "__main__":
    main()
```
See it in action in `examples/minimal.py`.
