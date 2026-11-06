"""IQ signal sources.

A source yields Chunk objects (raw IQ samples tagged with the BLE channel they
were captured on). Three implementations are provided:

- UsrpSource      -- live stream from a USRP B210
- IQFileSource    -- replay of a recorded IQ file (.npy / .sc16 / .fc32)
- SyntheticSource -- generated realistic BLE traffic (no hardware needed)

Use make_source() to create a source from a kind string.
"""

from .base import Chunk, Source
from .iqfile import IQFileSource
from .synthetic import SyntheticSource
from .usrp import UsrpSource

__all__ = ["Chunk", "Source", "UsrpSource", "IQFileSource", "SyntheticSource", "make_source"]


def make_source(kind, **kwargs):
    """Factory: create a source by kind name ('usrp', 'file', 'synthetic')."""
    kinds = {
        "usrp": UsrpSource,
        "file": IQFileSource,
        "synthetic": SyntheticSource,
    }
    if kind not in kinds:
        raise ValueError(f"unknown source kind {kind!r}, expected one of {sorted(kinds)}")
    return kinds[kind](**kwargs)
