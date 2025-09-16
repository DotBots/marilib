import time

from marilib.serial_hdlc import (
    HDLCDecodeException,
    HDLCHandler,
    HDLCState,
    hdlc_encode,
)
from marilib.serial_uart import SerialInterface

BAUDRATE = 1000000
# BAUDRATE = 460_800

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

    def send_payload(payload):
        print(f"\nSending {len(payload)} bytes: {payload.hex(' ')}")
        encoded = hdlc_encode(payload)
        print(f"Sending encoded {len(encoded)} bytes: {encoded.hex(' ')}")

        serial_interface.write_chunked_with_trigger_byte(encoded)
        # serial_interface.write(encoded[0:1])
        # time.sleep(0.0001)  # 100 us -- this time is important because of the trigger byte timeout on the nRF side
        # serial_interface.write(encoded[1:])


    # sleep_time = 0.1 # 100 ms
    sleep_time = 0.01 # 10 ms

    # send_payload(b"A" * 1)
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 4)
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 4) # 16 bytes
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 8) # 32 bytes
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 16) # 64 bytes
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 32) # 128 bytes
    # time.sleep(sleep_time)
    # send_payload(b"ABCD" * 64) # 256 bytes

    for i in range(4):
        # send_payload(b"ABCD" * 8) # 32 bytes
        # send_payload(b"ABCD" * 16) # 64 bytes
        send_payload(b"A" * 80)
        time.sleep(sleep_time)

    # serial_interface.write(b"A" * 8)

    print("Sleeping for 2 seconds\n\n")
    time.sleep(0.01)
