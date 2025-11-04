import os
import json
import importlib

import boto3
from moto import mock_aws

from app.models import EmailStatus


CSV_CONTENT = b"""email,subject,content
alice@example.com,Welcome,Hi Alice!
bob@example.com,Promo,Hi Bob!
"""


def _create_dynamodb_table(dynamodb):
    """
    Crea una tabla DynamoDB 'emails' compatible con template.yaml
    para usar en pruebas locales con moto.
    """
    return dynamodb.create_table(
        TableName="emails",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "batch_id", "AttributeType": "S"},
            {"AttributeName": "email_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "batch_id", "KeyType": "HASH"},
            {"AttributeName": "email_id", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "StatusCreatedAtIndex",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


@mock_aws
def test_enqueue_emails_from_csv_basic(monkeypatch):
    """
    Verifica que:
    - Se creen items en Dynamo en estado PENDING.
    - Se publiquen mensajes en SQS por cada email válido.
    """
    # Configurar entorno AWS simulado
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="email-queue")

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")
    monkeypatch.setenv("EMAIL_QUEUE_URL", queue["QueueUrl"])

    # Importar services DESPUÉS de configurar env + moto
    from app import services

    importlib.reload(services)

    # Act
    result = services.enqueue_emails_from_csv(CSV_CONTENT)

    # Assert respuesta
    assert result["total"] == 2
    assert result["enqueued"] == 2
    assert result["skipped"] == 0
    assert "batch_id" in result

    batch_id = result["batch_id"]

    # Assert DynamoDB
    items = table.scan()["Items"]
    assert len(items) == 2
    statuses = {item["status"] for item in items}
    assert statuses == {EmailStatus.PENDING.value}

    # Assert SQS (2 mensajes publicados)
    msgs = sqs.receive_message(QueueUrl=queue["QueueUrl"], MaxNumberOfMessages=10).get(
        "Messages", []
    )
    assert len(msgs) == 2

    bodies = [json.loads(m["Body"]) for m in msgs]
    assert all(b["batch_id"] == batch_id for b in bodies)


@mock_aws
def test_enqueue_emails_from_csv_idempotent(monkeypatch):
    """
    Verifica la idempotencia:
    - Mismo CSV => mismo batch_id.
    - Segunda ejecución no vuelve a encolar los mismos emails.
    """
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue = sqs.create_queue(QueueName="email-queue")

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")
    monkeypatch.setenv("EMAIL_QUEUE_URL", queue["QueueUrl"])

    from app import services

    importlib.reload(services)

    # Primera ejecución
    first = services.enqueue_emails_from_csv(CSV_CONTENT)
    # Limpiar mensajes de la cola
    sqs.receive_message(QueueUrl=queue["QueueUrl"], MaxNumberOfMessages=10)

    # Segunda ejecución con el MISMO archivo
    second = services.enqueue_emails_from_csv(CSV_CONTENT)

    # batch_id debe ser el mismo
    assert first["batch_id"] == second["batch_id"]

    # No se deben volver a encolar los mismos emails
    assert second["enqueued"] == 0
    assert second["skipped"] == 2

    # La tabla sigue teniendo solo 2 items
    items = table.scan()["Items"]
    assert len(items) == 2
