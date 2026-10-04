from scapy.layers.bluetooth4LE import BTLE, BTLE_ADV
import numpy as np

class BleDecoder:
    @staticmethod
    def parse_packet(meta: dict, packet_bytes: bytes, iq_array: np.ndarray) -> dict:
        try:
            pkt = BTLE(packet_bytes)
            
            # Use mock MAC if available, else extract from Scapy
            mac_address = meta.get("mock_mac", "Unknown")
            if mac_address == "Unknown" and pkt.haslayer(BTLE_ADV):
                mac_address = pkt.AdvA if hasattr(pkt, 'AdvA') else "Unknown"

            # Split complex array to I (real) and Q (imag) lists for JSON
            iq_i = np.real(iq_array).tolist()
            iq_q = np.imag(iq_array).tolist()

            return {
                "status": "ok",
                "mac": mac_address,
                "payload_hex": packet_bytes.hex(),
                "channel": meta.get("channel"),
                "frequency": meta.get("frequency_mhz"),
                "timestamp": meta.get("timestamp"),
                "iq_data": {"I": iq_i, "Q": iq_q}
            }
        except Exception as e:
            return {"status": "error", "error_msg": str(e)}