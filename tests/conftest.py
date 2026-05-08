from __future__ import annotations

import sys
from pathlib import Path


# Tests are executed from inside `AGENT_Joko/`, but the import root for the
# package is one directory above (so `import AGENT_Joko` resolves).
_api_root = Path(__file__).resolve().parents[2]
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))

