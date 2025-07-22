from dataclasses import dataclass
import lakers
import logging
from marilib.model import MariNode
from marilib.mari_protocol import Frame
import requests
import random

V = bytes.fromhex("72cc4761dbd4c78f758931aa589d348d1ef874a7e303ede2f140dcf3e6aa4aac")
CRED_V = bytes.fromhex(
    "a2026b6578616d706c652e65647508a101a501020241322001215820bbc34960526ea4d32e940cad2a234148ddc21791a12afbcbac93622046dd44f02258204519e257236b2a0ce2023f0931f1f386ca7afda64fcde0108c224c51eabf6072"
)
CBOR_TRUE = bytes.fromhex("f5")

CRED_REQUEST_PATH = ".well-known/lake-authz/cred-request"

@dataclass
class ELAHandler:
    edhoc_responder: lakers.EdhocResponder = lakers.EdhocResponder(V, CRED_V)
    authz_authenticator: lakers.AuthzAutenticator = lakers.AuthzAutenticator()
    loc_w: str | None = None
    c_i: bytes | None = None
    c_r: bytes | None = None
    state: str = "init"
    node: MariNode | None = None
    received_voucher: bytes | None = None

    def handle_join_request(self, frame: Frame):
        res = self.handle_message_1(frame)
        if not res:
            print("Failed to handle message 1")
            return False, None
        res, message_2 = self.prepare_message_2()
        if not res:
            print("Failed to prepare message 2")
            return False, None
        message_2 = self.c_i + message_2
        return True, message_2

    def handle_message_1(self, frame: Frame):
        # handle message 1
        if not frame.payload.startswith(CBOR_TRUE):
            self.state = "error"
            return False
        message_1 = frame.payload[1:]
        c_i, ead_1 = self.edhoc_responder.process_message_1(message_1)
        self.c_i = c_i
        print(
            f"edhoc_message_1: {message_1.hex(' ').upper()} ead_1: {ead_1.value().hex(' ').upper() if ead_1 else None}"
        )

        # request voucher
        loc_w, voucher_request = self.authz_authenticator.process_ead_1(ead_1, message_1)
        voucher_request_url = f"{loc_w}/.well-known/lake-authz/voucher-request"
        print(
            f"Requesting voucher: {voucher_request_url} {voucher_request.hex(' ').upper()}"
        )
        response = requests.post(voucher_request_url, data=voucher_request)
        if response.status_code == 200:
            print(
                f"Got an ok voucher response: {response.content.hex(' ').upper()}"
            )
            self.received_voucher = response.content
            self.state = "received_voucher"
        else:
            print(
                f"Error requesting voucher: {response.status_code}"
            )

        return True

    def prepare_message_2(self):
        if self.state != "received_voucher":
            return False, None
        ead_2 = self.authz_authenticator.prepare_ead_2(self.received_voucher)
        print(f"Prepared ead_2: {ead_2.value().hex(' ').upper()}")
        self.c_r = [random.randint(0, 23)]  # already cbor-encoded as single-byte integer
        message_2 = self.edhoc_responder.prepare_message_2(lakers.CredentialTransfer.ByValue, self.c_r, ead_2)
        print(f"Prepared message_2: {message_2.hex(' ').upper()}")
        return True, message_2

    @staticmethod
    def fetch_credential_remotely(loc_w: str, id_cred_i: bytes) -> bytes:
        url = f"{loc_w}/{CRED_REQUEST_PATH}"
        res = requests.post(url, data=id_cred_i)
        if res.status_code == 200:
            return res.content
        else:
            raise Exception(f"Error fetching credential {id_cred_i} at {loc_w}")
