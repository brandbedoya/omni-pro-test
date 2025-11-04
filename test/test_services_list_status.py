import os
import importlib
from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

from app.models import EmailStatus


def _create_dynamodb_table(dynamodb):
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
def test_list_email_status_filter_by_status(monkeypatch):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")

    # Datos de prueba
    now = datetime.now(timezone.utc)
    iso_now = now.isoformat()
    iso_old = (now - timedelta(days=2)).isoformat()

    table.put_item(
        Item={
            "batch_id": "b1",
            "email_id": "alice@example.com",
            "email": "alice@example.com",
            "subject": "Welcome",
            "content": "Hi Alice",
            "status": EmailStatus.SENT.value,
            "error_message": None,
            "created_at": iso_now,
            "updated_at": iso_now,
        }
    )
    table.put_item(
        Item={
            "batch_id": "b1",
            "email_id": "bob@example.com",
            "email": "bob@example.com",
            "subject": "Promo",
            "content": "Hi Bob",
            "status": EmailStatus.PENDING.value,
            "error_message": None,
            "created_at": iso_old,
            "updated_at": iso_old,
        }
    )

    from app import services

    importlib.reload(services)

    # Act: solo SENT
    result = services.list_email_status(status=[EmailStatus.SENT])

    # Assert
    assert len(result) == 1
    r = result[0]
    assert r.email == "alice@example.com"
    assert r.status == EmailStatus.SENT


@mock_aws
def test_list_email_status_filter_by_date(monkeypatch):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")

    now = datetime.now(timezone.utc)
    iso_now = now.isoformat()
    iso_old = (now - timedelta(days=5)).isoformat()

    table.put_item(
        Item={
            "batch_id": "b1",
            "email_id": "alice@example.com",
            "email": "alice@example.com",
            "subject": "Welcome",
            "content": "Hi Alice",
            "status": EmailStatus.SENT.value,
            "error_message": None,
            "created_at": iso_now,
            "updated_at": iso_now,
        }
    )
    table.put_item(
        Item={
            "batch_id": "b1",
            "email_id": "bob@example.com",
            "email": "bob@example.com",
            "subject": "Promo",
            "content": "Hi Bob",
            "status": EmailStatus.SENT.value,
            "error_message": None,
            "created_at": iso_old,
            "updated_at": iso_old,
        }
    )

    from app import services

    importlib.reload(services)

    from_date = now - timedelta(days=1)

    result = services.list_email_status(
        status=[EmailStatus.SENT],
        from_date=from_date,
        to_date=now + timedelta(minutes=1),
    )

    # Solo debería traer el reciente
    assert len(result) == 1
    assert result[0].email == "alice@example.com"
