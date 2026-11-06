#!/usr/bin/env python3
"""Живой захват IQ с B210 для офлайн-отладки декодера."""
import sys
import time

import numpy as np
import uhd


def capture(freq, seconds, out_path, gain=50):
    usrp = uhd.usrp.MultiUSRP("type=b200")
    usrp.set_rx_rate(4e6, 0)
    usrp.set_rx_freq(uhd.types.TuneRequest(freq), 0)
    usrp.set_rx_gain(gain, 0)
    usrp.set_rx_antenna("RX2", 0)
    usrp.set_rx_antenna("RX2", 0)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    stream = usrp.get_rx_stream(st_args)

    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = True
    stream.issue_stream_cmd(stream_cmd)

    buf = np.zeros(8192, dtype=np.complex64)
    md = uhd.types.RXMetadata()
    chunks = []
    t0 = time.time()
    total = 0
    while time.time() - t0 < seconds:
        n = stream.recv(buf, md, 1.0)
        if n:
            chunks.append(buf[:n].copy())
            total += n
    stream.issue_stream_cmd(uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont))
    iq = np.concatenate(chunks)
    np.save(out_path, iq)
    print(f"saved {len(iq)} samples ({len(iq)/4e6:.1f} s) -> {out_path}")


if __name__ == "__main__":
    freq = float(sys.argv[1]) if len(sys.argv) > 1 else 2.402e9
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 15
    out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/opencode/capture.npy"
    capture(freq, seconds, out)
