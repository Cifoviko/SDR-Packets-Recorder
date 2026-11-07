#!/usr/bin/env python3
"""BLE Passive Identifier - application entrypoint.

Examples:
    # live capture from a USRP B210 (default)
    venv_ble/bin/python main.py

    # same but stay on one channel
    venv_ble/bin/python main.py --no-hop --channel 38

    # no hardware: replay a recorded capture (loops in realtime)
    venv_ble/bin/python main.py --source file --file samples/ch37_5s_2msps.sc16

    # no hardware: fully synthetic generated BLE traffic
    venv_ble/bin/python main.py --source synthetic --hop
"""

import argparse
import os
import sys
import threading

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ble import config
from ble.pipeline import PacketStore, Processor, Stats
from ble.sources import make_source
from ble.storage import DatasetWriter
from web.app import create_app


def build_source(args):
    """Create the IQ source selected by command line arguments."""
    if args.source == "usrp":
        channels = ((args.channel, config.channel_freq(args.channel)),) if not args.hop else config.CHANNELS
        return make_source("usrp", channels=channels)

    if args.source == "file":
        path = args.file or os.path.join(config.SAMPLES_DIR, "ch37_5s_2msps.sc16")
        return make_source("file", path=path, channel=args.channel,
                           loop=args.loop, realtime=not args.no_realtime, speed=args.speed)

    return make_source("synthetic", channel=args.channel, hop=args.hop,
                       packets_per_sec=args.pps, realtime=not args.no_realtime, seed=args.seed)


def main():
    parser = argparse.ArgumentParser(description="BLE Passive Identifier")
    parser.add_argument("--source", choices=["usrp", "file", "synthetic"], default="usrp",
                        help="IQ source: live USRP (default), recorded file, or synthetic traffic")
    parser.add_argument("--file", default=None,
                        help="path to an IQ recording for --source file (.npy/.sc16/.fc32)")
    parser.add_argument("--channel", type=int, default=37,
                        help="BLE advertising channel for file/synthetic sources and --no-hop mode")
    parser.add_argument("--hop", action=argparse.BooleanOptionalAction, default=True,
                        help="hop across advertising channels 37/38/39 (default: on)")
    parser.add_argument("--loop", action=argparse.BooleanOptionalAction, default=True,
                        help="loop the file replay (default: on)")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="file replay speed multiplier (default: 1.0 = realtime)")
    parser.add_argument("--no-realtime", action="store_true",
                        help="replay/generate as fast as possible instead of pacing to realtime")
    parser.add_argument("--pps", type=float, default=30.0,
                        help="synthetic source: packets per second (default: 30)")
    parser.add_argument("--seed", type=int, default=None, help="synthetic source RNG seed")
    parser.add_argument("--port", type=int, default=config.WEB_PORT, help="web server port")
    args = parser.parse_args()

    source = build_source(args)
    store = PacketStore()
    stats = Stats()
    writer = DatasetWriter(config.DATASET_DIR)
    processor = Processor(source, store, writer, stats)

    threading.Thread(target=processor.run, daemon=True).start()

    app = create_app(store, stats, writer, processor, config.DATASET_DIR, config.STATIC_DIR)
    print(f"[*] Web UI: http://localhost:{args.port}  (source: {source.description})")
    # access_log=False: per-request logging was measured to starve the UHD recv path
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
