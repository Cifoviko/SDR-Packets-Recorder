#!/usr/bin/env python3
"""Offline validation of the DSP core against recorded IQ samples.

Usage: venv_ble/bin/python scripts/validate_dataset.py [channel]

Note: old dataset/* files (saved by the pre-rewrite broken version of the app)
may not decode - they were stored by a non-working pipeline.
"""

import glob
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ble.dsp import decode_capture  # noqa: E402

DATASET = os.path.join(BASE_DIR, "dataset")


def main():
    channel = int(sys.argv[1]) if len(sys.argv) > 1 else 37
    files = sorted(glob.glob(os.path.join(DATASET, "*.npy")))
    ok, fail, by_type = 0, 0, {}
    examples = []
    for f in files:
        iq = np.load(f)
        res = decode_capture(iq, channel=channel)
        if res:
            ok += 1
            by_type[res["pdu_type"]] = by_type.get(res["pdu_type"], 0) + 1
            if len(examples) < 10:
                examples.append((os.path.basename(f), res))
        else:
            fail += 1
    print(f"files: {len(files)}, channel {channel}")
    print(f"CRC-OK decoded: {ok}")
    print(f"rejected: {fail}")
    print(f"by PDU type: {by_type}")
    print("\nexamples:")
    for name, r in examples:
        print(f"  {name}: {r['pdu_type']} MAC={r['mac']} len={r['length']} data={r['payload'][:40]}")


if __name__ == "__main__":
    main()
