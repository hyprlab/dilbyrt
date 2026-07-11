# SPDX-License-Identifier: MIT
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("DILBYRT_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=8000, debug=debug)
