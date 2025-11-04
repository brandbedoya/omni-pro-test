"""
Adaptador para ejecutar la app de FastAPI dentro de AWS Lambda
usando API Gateway (SAM -> Handler: lambda_app.handler).
"""

from mangum import Mangum
from app.main import app


# Handler que SAM va a usar en la Lambda de la API
handler = Mangum(app)
