import csv
import io
import json
import os
import uuid
import hashlib
import boto3
import base64

from app.logger import logger

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from boto3.dynamodb.conditions import Key

from .models import EmailStatus
from .schemas import EmailRecordOut

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["EMAILS_TABLE_NAME"])

sqs = boto3.client("sqs")
QUEUE_URL = os.environ.get("EMAIL_QUEUE_URL")


def _encode_pagination_token(last_evaluated_key: dict | None) -> str | None:
    if not last_evaluated_key:
        return None
    raw = json.dumps(last_evaluated_key).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_pagination_token(token: str | None) -> dict | None:
    if not token:
        return None
    raw = base64.urlsafe_b64decode(token.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_batch_id(file_bytes: bytes) -> str:
    """
    Idempotencia: el batch_id es un hash del contenido del archivo.
    Si se sube el mismo CSV dos veces, el batch_id será igual.
    """
    h = hashlib.sha256()
    h.update(file_bytes)
    return h.hexdigest()


def parse_csv(content: bytes) -> Iterable[dict]:
    """
    Parsea el CSV y devuelve dicts con columnas: email, subject, content.
    Lanza excepción si el encabezado es inválido.
    """
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    required_fields = {"email", "subject", "content"}
    if not required_fields.issubset(reader.fieldnames or []):
        raise ValueError(f"CSV debe tener columnas: {', '.join(required_fields)}")

    for row in reader:
        yield row


def enqueue_emails_from_csv(file_bytes: bytes) -> dict:
    if not QUEUE_URL:
        raise RuntimeError("EMAIL_QUEUE_URL no está definido")

    batch_id = generate_batch_id(file_bytes)
    logger.info("Procesando nuevo upload, batch_id=%s", batch_id)

    total = 0
    enqueued = 0
    skipped = 0

    for row in parse_csv(file_bytes):
        total += 1
        try:
            raw_email = (row.get("email") or "").strip()
            subject = (row.get("subject") or "").strip()
            content = (row.get("content") or "").strip()

            if not raw_email or "@" not in raw_email:
                raise ValueError("email inválido")
            if not subject or not content:
                raise ValueError("subject y content son obligatorios")

            email_id = raw_email
            created_at = now_iso()

            item = {
                "batch_id": batch_id,
                "email_id": email_id,
                "email": raw_email,
                "subject": subject,
                "content": content,
                "status": EmailStatus.PENDING.value,
                "error_message": None,
                "created_at": created_at,
                "updated_at": created_at,
            }

            try:
                table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(email_id)",
                )
            except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
                skipped += 1
                logger.warning(
                    "Fila duplicada saltada (idempotencia). batch_id=%s email=%s",
                    batch_id,
                    raw_email,
                )
                continue

            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({"batch_id": batch_id, "email_id": email_id}),
            )

            enqueued += 1

        except ValueError as exc:
            skipped += 1
            logger.warning(
                "Fila inválida saltada. batch_id=%s error=%s raw_row=%s",
                batch_id,
                exc,
                row,
            )
            continue

    logger.info(
        "Resumen upload batch_id=%s total=%d enqueued=%d skipped=%d",
        batch_id,
        total,
        enqueued,
        skipped,
    )

    return {
        "batch_id": batch_id,
        "total": total,
        "enqueued": enqueued,
        "skipped": skipped,
    }


def _item_to_email_record_out(item: dict) -> EmailRecordOut:
    return EmailRecordOut(
        email_id=item["email_id"],
        batch_id=item["batch_id"],
        email=item["email"],
        subject=item["subject"],
        content=item["content"],
        status=EmailStatus(item["status"]),
        error_message=item.get("error_message"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=(
            datetime.fromisoformat(item["updated_at"])
            if item.get("updated_at")
            else None
        ),
    )


def list_email_status(
    status: Optional[List[EmailStatus]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> List[EmailRecordOut]:
    """
    Consulta estados desde DynamoDB.

    - Si se pasa `status`, usa el GSI StatusCreatedAtIndex.
    - Si no, hace un scan de la tabla.
    """
    items: list[dict] = []

    from_s = from_date.isoformat() if from_date else None
    to_s = to_date.isoformat() if to_date else None

    if status:
        # Query por cada status usando el GSI
        for s in status:
            key_cond = Key("status").eq(s.value)
            if from_s and to_s:
                key_cond = key_cond & Key("created_at").between(from_s, to_s)
            elif from_s:
                key_cond = key_cond & Key("created_at").gte(from_s)
            elif to_s:
                key_cond = key_cond & Key("created_at").lte(to_s)

            resp = table.query(
                IndexName="StatusCreatedAtIndex",
                KeyConditionExpression=key_cond,
            )
            items.extend(resp.get("Items", []))
    else:
        scan_kwargs = {}
        resp = table.scan(**scan_kwargs)
        items = resp.get("Items", [])

    return [_item_to_email_record_out(i) for i in items]


def list_email_status_paginated(
    status: Optional[List[EmailStatus]] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 50,
    next_token: Optional[str] = None,
) -> tuple[List[EmailRecordOut], Optional[str]]:
    """
    Versión paginada de list_email_status.
    Usa el GSI StatusCreatedAtIndex cuando se pasa status.
    """
    limit = max(1, min(limit, 200))
    exclusive_start_key = _decode_pagination_token(next_token)

    # Si hay estado, consulta por el primero
    if status:
        return _query_by_status(
            status[0], from_date, to_date, limit, exclusive_start_key
        )

    # Si no hay estado, escanea toda la tabla
    return _scan_all(limit, exclusive_start_key)


def _query_by_status(
    status: EmailStatus,
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    limit: int,
    exclusive_start_key: Optional[dict],
) -> tuple[List[EmailRecordOut], Optional[str]]:
    """Realiza la query por status usando el índice secundario."""
    from_s = from_date.isoformat() if from_date else None
    to_s = to_date.isoformat() if to_date else None

    key_cond = Key("status").eq(status.value)
    if from_s and to_s:
        key_cond &= Key("created_at").between(from_s, to_s)
    elif from_s:
        key_cond &= Key("created_at").gte(from_s)
    elif to_s:
        key_cond &= Key("created_at").lte(to_s)

    kwargs = {
        "IndexName": "StatusCreatedAtIndex",
        "KeyConditionExpression": key_cond,
        "Limit": limit,
    }
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key

    resp = table.query(**kwargs)
    items = resp.get("Items", [])
    token = _encode_pagination_token(resp.get("LastEvaluatedKey"))
    return [_item_to_email_record_out(i) for i in items], token


def _scan_all(
    limit: int, exclusive_start_key: Optional[dict]
) -> tuple[List[EmailRecordOut], Optional[str]]:
    """Escanea toda la tabla sin filtros."""
    kwargs = {"Limit": limit}
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key

    resp = table.scan(**kwargs)
    items = resp.get("Items", [])
    token = _encode_pagination_token(resp.get("LastEvaluatedKey"))
    return [_item_to_email_record_out(i) for i in items], token
