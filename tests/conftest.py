"""Test configuration.

The integration's package ``__init__`` imports Home Assistant, which is too
heavy to install for unit tests of pure helpers. We load ``util`` and ``api``
directly from their source files via ``importlib`` and register them under
short module names so test modules can ``import`` them normally.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "localtrailerhire"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load util first; api.py does ``from .util import parse_iso_datetime``.
util = _load("lth_util", COMPONENT / "util.py")

# Stub the relative-import target ``.util`` resolves to under the package name
# we'll use when loading api.py.
sys.modules["lth_pkg"] = ModuleType("lth_pkg")
sys.modules["lth_pkg"].__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
sys.modules["lth_pkg.util"] = util
sys.modules["lth_pkg.const"] = _load("lth_pkg.const", COMPONENT / "const.py")

api = _load("lth_pkg.api", COMPONENT / "api.py")

# auto_review.py imports only ``.util`` (registered above), so it loads without
# Home Assistant just like api.py.
auto_review = _load("lth_pkg.auto_review", COMPONENT / "auto_review.py")
customer_history = _load("lth_pkg.customer_history", COMPONENT / "customer_history.py")
message_archive = _load("lth_pkg.message_archive", COMPONENT / "message_archive.py")

# Re-export under the names the tests use.
sys.modules["lth_util"] = util
sys.modules["lth_api"] = api
sys.modules["lth_auto_review"] = auto_review
sys.modules["lth_customer_history"] = customer_history
sys.modules["lth_message_archive"] = message_archive
