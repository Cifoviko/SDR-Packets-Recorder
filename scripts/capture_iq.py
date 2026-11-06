#!/usr/bin/env python3
"""Capture raw IQ from a B210 for offline debugging.

Examples:
    venv_ble/bin/python scripts/capture_iq.py 2.402e9 15 /tmp/cap.npy
    venv_ble/bin/python scripts/capture_iq.py 2.426e9 10 /tmp/cap.sc16 --format sc16
"""

import argparse

import numpy as np
import uhd


def capture(freq, seconds, out_path, gain=50, samp_rate=2e6, fmt="npy"):
    usrp = uhd.usrp.MultiUSRP("type=b200")
    usrp.set_rx_rate(samp_rate, 0)
    usrp.set_rx_freq(uhd.types.TuneRequest(freq), 0)
    usrp.set_rx_gain(gain, 0)
    usrp.set_rx_antenna("RX2", 0)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    stream = usrp.get_rx_stream(st_args)

    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = True
    stream.issue_stream_cmd(stream_cmd)

    import time

    buf = np.zeros(8192, dtype=np.complex64)
    md = uhd.types.RXMetadata()
    chunks = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        n = stream.recv(buf, md, 1.0)
        if n:
            chunks.append(buf[:n].copy())
    stream.issue_stream_cmd(uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont))

    iq = np.concatenate(chunks)
    if fmt == "sc16":
        sc = np.empty(len(iq) * 2, dtype=np.int16)
        sc[0::2] = (iq.real * 32767).astype(np.int16)
        sc[1::2] = (iq.imag * 32767).astype(np.int16)
        sc.tofile(out_path)
    else:
        np.save(out_path, iq)
    print(f"saved {len(iq)} samples ({len(iq) / samp_rate:.1f} s) -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("freq", type=float, help="center frequency in Hz (e.g. 2.402e9)")
    parser.add_argument("seconds", type=float, help="capture duration")
    parser.add_argument("out", help="output path (.npy or .sc16)")
    parser.add_argument("--gain", type=float, default=50)
    parser.add_argument("--rate", type=float, default=2e6, help="sample rate (default: 2e6)")
    parser.add_argument("--format", choices=["npy", "sc16"], default="npy")
    args = parser.parse_args()
    capture(args.freq, args.seconds, args.out, gain=args.gain, samp_rate=args.rate, fmt=args.format)
