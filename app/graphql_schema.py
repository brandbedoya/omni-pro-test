import enum
from datetime import datetime
from typing import List, Optional

import strawberry

from .models import EmailStatus as EmailStatusEnum
from .services import list_email_status_paginated


@strawberry.enum
class EmailStatusGQLEnum(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ERROR = "ERROR"


@strawberry.type
class EmailRecordType:
    email_id: str = strawberry.field(name="emailId")
    batch_id: str = strawberry.field(name="batchId")
    email: str
    subject: str
    content: str
    status: EmailStatusGQLEnum
    error_message: Optional[str] = strawberry.field(name="errorMessage", default=None)
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: Optional[datetime] = strawberry.field(name="updatedAt", default=None)


@strawberry.type
class EmailRecordPage:
    items: List[EmailRecordType]
    next_token: Optional[str] = strawberry.field(name="nextToken", default=None)


@strawberry.type
class Query:
    @strawberry.field(name="listEmailStatus")
    def list_email_status(
        self,
        status: Optional[List[EmailStatusGQLEnum]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        next_token: Optional[str] = None,
    ) -> EmailRecordPage:
        """
        Lista envíos filtrando por:
        - status: uno o varios estados
        - fromDate / toDate: rango de fechas de creación
        - limit: tamaño de página
        - nextToken: token de paginación (opcional)
        """

        records, next_token_val = list_email_status_paginated(
            status=[EmailStatusEnum(s.value) for s in status] if status else None,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            next_token=next_token,
        )

        items = [
            EmailRecordType(
                email_id=r.email_id,
                batch_id=r.batch_id,
                email=r.email,
                subject=r.subject,
                content=r.content,
                status=EmailStatusGQLEnum(r.status.value),
                error_message=r.error_message,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in records
        ]

        return EmailRecordPage(items=items, next_token=next_token_val)


schema = strawberry.Schema(query=Query)
