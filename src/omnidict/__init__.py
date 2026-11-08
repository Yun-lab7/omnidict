# Include vendor directory into sys.path
import sys
from pathlib import Path

vendor_path = str(Path(__file__).parent / "vendor")
if vendor_path not in sys.path:
    sys.path.insert(0, vendor_path)

from aqt import mw

from . import editor  # noqa: F401

if mw is not None:  # not when the provider tests import this package
    from .batch import add_menu_item

    add_menu_item()
