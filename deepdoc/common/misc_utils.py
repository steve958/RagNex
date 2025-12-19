from __future__ import annotations


def pip_install_torch() -> None:
    """Best-effort torch import.

    In ragflow this attempted to install torch at runtime; for RagNex we avoid
    doing any installation and simply provide a compatibility shim.
    """

    # Intentionally no-op. Callers should handle ImportError / missing CUDA.
    return
