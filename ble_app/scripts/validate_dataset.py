#!/usr/bin/env python3
"""Офлайн-валидация ядра ble.py на сохранённых IQ-сэмплах из dataset/.

Пример: venv_ble/bin/python scripts/validate_dataset.py [channel]
Примечание: старые файлы dataset/* (до переписывания приложения) могут
не декодироваться — они были сохранены нерабочей версией приложения.
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ble import decode_capture  # noqa: E402

DATASET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset")


def main():
    files = sorted(glob.glob(os.path.join(DATASET, "*.npy")))
    ok, fail, by_type = 0, 0, {}
    examples = []
    for f in files:
        iq = np.load(f)
        res = decode_capture(iq, channel=37)
        if res:
            ok += 1
            by_type[res["pdu_type"]] = by_type.get(res["pdu_type"], 0) + 1
            if len(examples) < 10:
                examples.append((os.path.basename(f), res))
        else:
            fail += 1
    print(f"Всего файлов: {len(files)}")
    print(f"CRC-OK декодировано: {ok}")
    print(f"Отклонено: {fail}")
    print(f"По типам PDU: {by_type}")
    print("\nПримеры:")
    for name, r in examples:
        print(f"  {name}: {r['pdu_type']} MAC={r['mac']} len={r['length']} data={r['payload'][:40]}")


if __name__ == "__main__":
    main()
