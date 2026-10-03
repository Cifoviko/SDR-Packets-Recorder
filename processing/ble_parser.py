from scapy.layers.bluetooth4LE import BTLE, BTLE_ADV
import json

class BleDecoder:
    """
    Decoder class for raw BLE packets.
    Uses Scapy to extract MAC addresses and payload from raw bytes.
    """

    @staticmethod
    def parse_packet(packet_bytes: bytes, iq_data: list) -> dict:
        """
        Parses a raw BLE packet byte array into a structured dictionary.

        Args:
            packet_bytes (bytes): Raw byte array starting from Access Address.
            iq_data (list): List of complex I/Q samples associated with the packet.

        Returns:
            dict: Parsed data containing MAC address, payload, and IQ length.
        """
        try:
            # Convert raw bytes into a Scapy BTLE object
            pkt = BTLE(packet_bytes)
            
            mac_address = "Unknown"
            
            # Check if the packet contains an Advertising layer
            if pkt.haslayer(BTLE_ADV):
                # Extract the Advertiser Address (AdvA) if present
                mac_address = pkt.AdvA if hasattr(pkt, 'AdvA') else "Unknown"

            return {
                "status": "ok",
                "mac": mac_address,
                "payload_hex": packet_bytes.hex(),
                "iq_length": len(iq_data)
            }
        except Exception as e:
            return {"status": "error", "error_msg": str(e)}
        