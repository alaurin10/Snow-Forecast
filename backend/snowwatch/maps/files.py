"""Writing the map's working files safely: whole or not at all, even with two threads
writing the same name at once."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import numpy as np


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_npy(path: Path, values: np.ndarray) -> None:
    buf = io.BytesIO()
    np.save(buf, values)
    write_atomic(path, buf.getvalue())
