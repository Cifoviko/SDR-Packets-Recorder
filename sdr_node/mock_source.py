import time
import zmq
import numpy as np

def run_mock_source():
    """
    Emulates the operation of an SDR board and GNU Radio.
    Generates a fake BLE packet and a chunk of I/Q data once per second,
    then sends them via a ZMQ socket.
    """
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://127.0.0.1:5555")
    
    print("[SDR Mock] Server started on tcp://127.0.0.1:5555")
    
    while True:
        # Fake BLE packet (Advertising packet, MAC: 11:22:33:44:55:66)
        fake_ble_bytes = b'\x40\x21\x66\x55\x44\x33\x22\x11\x02\x01\x06'
        
        t = np.linspace(0, 1, 100)
        fake_iq = np.exp(1j * 2 * np.pi * 5 * t) + np.random.normal(0, 0.1, 100)
        
        iq_bytes = fake_iq.astype(np.complex64).tobytes()
        
        socket.send_multipart([fake_ble_bytes, iq_bytes])
        print(f"[SDR Mock] Send packet ({len(fake_ble_bytes)} byte)")
        
        time.sleep(1)

if __name__ == "__main__":
    run_mock_source()
