# Netlify serverless function handler for the FastAPI app.

import sys
import os

# Add the 'src' directory to the Python path so that the
# agent_joko package (which lives in src/agent_joko) can be found.
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from mangum import Mangum
from agent_joko.dashboard.api import create_app

# Create the FastAPI app instance
app = create_app()

# Wrap the app with Mangum for AWS Lambda compatibility
handler = Mangum(app)
