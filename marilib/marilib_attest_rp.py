import cbor2
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey, Ed25519PrivateKey
)
from cryptography.exceptions import InvalidSignature

verifier_public_key_list = {
    5: bytes.fromhex('2463f9d5e61b84689b3b19ae10a3d6b5bfd1e69a643d7061aca4d04f7fd98db9')
}


MARI_ATTEST_VERIF_REQ_PAYLOAD_TAG  = 0xE2 
MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG = 0xE3

def mr_is_attest_verif_resp (payload):
    """Check if payload is verification response"""
    if len(payload) < 1:
        return False
    return payload[0] == MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG

def mr_process_attest_verif_resp(payload):
    """Process verification response and return simple binary result, 0 is fail, 1 is success"""
    try:
        verif_resp = payload[1:]
        result_signed, node_id, key_id_v = cbor2.loads(verif_resp)
        
        public_key_bytes = verifier_public_key_list[key_id_v]
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        
        
        try:
            sig_structure_cbor_t = cbor2.dumps([1, key_id_v, node_id])
            public_key.verify(result_signed, sig_structure_cbor_t)
            return bytes([MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG]) + bytes([1])
        except InvalidSignature:
            pass
        try:
            sig_structure_cbor_f = cbor2.dumps([0, key_id_v, node_id])
            public_key.verify(result_signed, sig_structure_cbor_f)
            print(f"result from verifier is 0")
            return bytes([MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG]) + bytes([0])
        except InvalidSignature:
            pass
        print(f"neither signature check passed, fail")
        return bytes([MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG]) + bytes([0])
    except Exception as e:
        print(f"Attestation verification response error: {e}")
        return bytes([MARI_ATTEST_VERIF_RESP_PAYLOAD_TAG]) + bytes([0])