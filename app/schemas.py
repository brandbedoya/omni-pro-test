from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr
from .models import EmailStatus


class UploadResponse(BaseModel):
    """
    Resumen de lo que pasó al procesar el CSV.
    """

    batch_id: str
    total: int
    enqueued: int
    skipped: int


class EmailStatusFilter(BaseModel):
    """
    Filtros para la consulta de estados (para GraphQL o REST si quieres).
    """

    status: Optional[List[EmailStatus]] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class EmailRecordOut(BaseModel):
    email_id: str
    batch_id: str
    email: EmailStr
    subject: str
    content: str
    status: EmailStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
