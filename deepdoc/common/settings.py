"""DeepDoc runtime settings.

Keep these defaults conservative so importing DeepDoc does not unexpectedly consume
GPU resources.
"""

# Number of parallel devices used for OCR/layout models.
# 0/1 means single device.
PARALLEL_DEVICES: int = 0
