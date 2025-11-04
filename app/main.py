import os
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from .graphql_schema import schema as gql_schema
from .schemas import UploadResponse
from .services import enqueue_emails_from_csv

root_path = os.getenv("ROOT_PATH", "")

app = FastAPI(
    title="Serverless Challenge",
    version="0.1.0",
    root_path=root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024


@app.post("/upload", response_model=UploadResponse)
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="El archivo debe ser CSV")

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"El archivo excede el tamaño máximo permitido de {MAX_FILE_SIZE_MB} MB.",
        )

    await file.seek(0)

    try:
        result = enqueue_emails_from_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return UploadResponse(**result)


graphql_app = GraphQLRouter(gql_schema)
app.include_router(graphql_app, prefix="/graphql")
