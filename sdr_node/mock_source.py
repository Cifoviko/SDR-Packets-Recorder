import time
import zmq
import numpy as np
import json
import random

def run_mock_source():
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://127.0.0.1:5555")
    
    print("[SDR Mock] Server started on tcp://127.0.0.1:5555")
    
    macs = ['AA:BB:CC:DD:EE:FF', '11:22:33:44:55:66', 'FE:DC:BA:98:76:54']
    
    while True:
        # Mocking BLE metadata
        channel = random.choice([37, 38, 39])
        freq = 2402 if channel == 37 else (2426 if channel == 38 else 2480)
        
        meta = {
            "channel": channel,
            "frequency_mhz": freq,
            "timestamp": time.time()
        }
        
        # Mocking BLE bytes and IQ data
        fake_ble_bytes = b'\x40\x21\x66\x55\x44\x33\x22\x11\x02\x01\x06'
        t = np.linspace(0, 1, 200)
        fake_iq = np.exp(1j * 2 * np.pi * 5 * t) + np.random.normal(0, 0.1, 200)
        
        # We simulate different MACs to test the UI cards
        meta['mock_mac'] = random.choice(macs) 
        
        socket.send_multipart([
            json.dumps(meta).encode('utf-8'),
            fake_ble_bytes,
            fake_iq.astype(np.complex64).tobytes()
        ])
        
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    run_mock_source()
    