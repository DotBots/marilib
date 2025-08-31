import cbor2
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey, Ed25519PrivateKey
)
from cryptography.exceptions import InvalidSignature

# provisions 
freshness_threshold = 8000
node_to_key_id = {
    795094838: 1,
}

swarm_public_key_list = {
    1: bytes.fromhex('b24f6d4e5f8147af1d1cd8c26e1a510b7a0f7f0a7bcc60688955d327b99c6475')
}

swarm_reference_value_list = {
    1: "h'DE6CD05D50778648BDB07B4D1C6DB81E0C2DF4533A32E515E533A26E2172873B'"
}

key_id_v = 5
private_key_verifier = bytes.fromhex('8ed2d03fa136f5232f957e41d368940153d580e6b5ea57b68aa8836ff9539010')
public_key_verifier = bytes.fromhex('2463f9d5e61b84689b3b19ae10a3d6b5bfd1e69a643d7061aca4d04f7fd98db9')

def mr_swarm_check_signature(signature_attester, asn_dl, version, node_id):
    # prepare sig_structure
    hash_verifier = swarm_reference_value_list[version]
    key_id_verifier = node_to_key_id[node_id]
    sig_structure = cbor2.dumps([asn_dl, hash_verifier, key_id_verifier])
    
    public_key_bytes = swarm_public_key_list[key_id_verifier]
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature_attester, sig_structure)
        return True
    except InvalidSignature:
        return False

def mr_swarm_generate_verification_response(result, node_id):
    if (result):
        sig_structure_cbor = cbor2.dumps([1, key_id_v, node_id])
    else:
        sig_structure_cbor = cbor2.dumps([0, key_id_v, node_id])
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_verifier)
    result_signed = private_key.sign(sig_structure_cbor)
    # generate verification_response
    verification_response = cbor2.dumps([result_signed, node_id, key_id_v])
    return verification_response

def mr_swarm_verification_result(verification_request):
        asn_ul, asn_offset, evidence_cbor, node_id = cbor2.loads(verification_request)
        version_attester, key_id_attester, signature_attester = cbor2.loads(evidence_cbor)
        
        # check freshness 
        if (asn_offset > freshness_threshold):
            return mr_swarm_generate_verification_response(False, node_id)
        
        asn_dl = asn_ul - asn_offset
        if (mr_swarm_check_signature(signature_attester, asn_dl, version_attester, node_id)):
            return mr_swarm_generate_verification_response(True, node_id)
        else:
            return mr_swarm_generate_verification_response(False, node_id)
