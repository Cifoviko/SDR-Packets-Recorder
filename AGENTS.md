# BLE Passive Identifier

Passive BLE advertising sniffer: USRP B210 -> energy burst detection -> GFSK
demodulation -> dewhitening -> CRC24 validation -> raw IQ dataset + web UI.

## Structure

```
main.py               entrypoint: argparse, wiring, uvicorn
ble/
  config.py           global constants (rates, channels, directories)
  dsp.py              DSP core: demodulation, dewhitening, CRC24, PDU parsing,
                      GFSK modulation (no I/O dependencies, offline-testable)
  pipeline.py         Processor (source -> bursts -> decoded packets),
                      PacketStore, Stats
  storage.py          DatasetWriter (background .npy writer)
  sources/
    base.py           Chunk dataclass + Source interface
    usrp.py           live USRP B210 source (recv thread + channel hopping)
    iqfile.py         recorded IQ file replay (.npy/.sc16/.fc32)
    synthetic.py      generated valid BLE traffic (no hardware needed)
web/
  app.py              FastAPI factory (routes only, state is injected)
  static/index.html   web UI
scripts/
  capture_iq.py       record raw IQ from the B210
  validate_dataset.py offline DSP validation over dataset/*.npy
dataset/              decoded packet IQ captures (.npy, complex128)
samples/              bundled recording for offline replay
```

Data flow: `Source.chunks()` -> `Processor` (detect/decode/CRC) ->
`PacketStore` + `DatasetWriter` -> `web` reads both.

## Run

```
venv_ble/bin/python main.py                      # live USRP B210, hop 37/38/39
venv_ble/bin/python main.py --no-hop --channel 38
venv_ble/bin/python main.py --source synthetic --hop    # fake data, no hardware
venv_ble/bin/python main.py --source file               # replay bundled sample
```

Web UI: http://localhost:5000
