import time

from marilib.serial_hdlc import (
    HDLCDecodeException,
    HDLCHandler,
    HDLCState,
    hdlc_encode,
)
from marilib.serial_uart import SerialInterface

BAUDRATE = 1000000
# BAUDRATE = 115200

hdlc_handler = HDLCHandler()


def on_byte_received(byte):
    # print(f"Received byte: {byte}")
    hdlc_handler.handle_byte(byte)
    if hdlc_handler.state == HDLCState.READY:
        try:
            payload = hdlc_handler.payload
            print(".", end="", flush=True)
            # print(f"Received payload: {payload.hex()}")
        except HDLCDecodeException as e:
            print(f"Error decoding payload: {e}")


serial_interface = SerialInterface("/dev/ttyACM0", BAUDRATE, on_byte_received)


while True:
    time.sleep(1)
    payload = b"A" * 4
    print(f"Sending {len(payload)} bytes: {payload.hex(' ')}")
    encoded = hdlc_encode(payload)
    print(f"Sending encoded {len(encoded)} bytes: {encoded.hex(' ')}")
    serial_interface.write(encoded[0:1])
    time.sleep(0.01)
    serial_interface.write(encoded[1:])

    # serial_interface.write(b"A" * 8)
