import json
import os
from datetime import datetime, timezone

import boto3
from app.logger import logger

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["EMAILS_TABLE_NAME"])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_email_simulation(email: str, subject: str, content: str) -> bool:
    logger.info("[WORKER] Enviando email a=%s subject=%s", email, subject)
    return True


def handler(event, context):
    logger.info("[WORKER] Event recibido: %s", json.dumps(event))

    for rec in event.get("Records", []):
        try:
            body = json.loads(rec["body"])
            batch_id = body.get("batch_id")
            email_id = body.get("email_id")

            if not batch_id or not email_id:
                logger.warning(
                    "[WORKER] Mensaje sin batch_id o email_id. body=%s", body
                )
                continue

            resp = table.get_item(Key={"batch_id": batch_id, "email_id": email_id})
            item = resp.get("Item")
            if not item:
                logger.warning(
                    "[WORKER] No se encontró item batch_id=%s email_id=%s",
                    batch_id,
                    email_id,
                )
                continue

            ok = send_email_simulation(item["email"], item["subject"], item["content"])

            status = "SENT" if ok else "ERROR"
            table.update_item(
                Key={"batch_id": batch_id, "email_id": email_id},
                UpdateExpression="SET #s = :s, updated_at = :u",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": status, ":u": now_iso()},
            )

            logger.info(
                "[WORKER] Actualizado estado batch_id=%s email_id=%s status=%s",
                batch_id,
                email_id,
                status,
            )

        except Exception as exc:
            logger.error(
                "[WORKER] Error procesando mensaje. body=%s error=%s",
                rec.get("body"),
                exc,
            )

    return {"statusCode": 200, "body": json.dumps({"message": "processed"})}
