# Netlify serverless function handler for the FastAPI app.

from mangum import Mangum
from agent_joko.dashboard.api import create_app

# Create the FastAPI app instance
app = create_app()

# Wrap the app with Mangum for AWS Lambda compatibility
handler = Mangum(app)
