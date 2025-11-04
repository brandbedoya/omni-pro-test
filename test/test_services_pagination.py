import importlib
from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

from app.models import EmailStatus


def _create_dynamodb_table(dynamodb):
    """
    Crea una tabla DynamoDB 'emails' compatible con template.yaml
    para pruebas con moto.
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
def test_list_email_status_paginated_by_status(monkeypatch):
    """
    Verifica que list_email_status_paginated:
    - Filtra por status usando el GSI.
    - Respeta el limit.
    - Devuelve un nextToken cuando hay más resultados.
    """
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")

    now = datetime.now(timezone.utc)
    # 3 SENT y 2 PENDING
    for i in range(3):
        ts = (now - timedelta(minutes=i)).isoformat()
        table.put_item(
            Item={
                "batch_id": "b1",
                "email_id": f"sent{i}@example.com",
                "email": f"sent{i}@example.com",
                "subject": "Sent",
                "content": "content",
                "status": EmailStatus.SENT.value,
                "error_message": None,
                "created_at": ts,
                "updated_at": ts,
            }
        )

    for i in range(2):
        ts = (now - timedelta(hours=1 + i)).isoformat()
        table.put_item(
            Item={
                "batch_id": "b1",
                "email_id": f"pending{i}@example.com",
                "email": f"pending{i}@example.com",
                "subject": "Pending",
                "content": "content",
                "status": EmailStatus.PENDING.value,
                "error_message": None,
                "created_at": ts,
                "updated_at": ts,
            }
        )

    from app import services

    importlib.reload(services)

    # Primera página: status=SENT, limit=2
    items_page1, next_token = services.list_email_status_paginated(
        status=[EmailStatus.SENT],
        from_date=None,
        to_date=None,
        limit=2,
        next_token=None,
    )

    assert len(items_page1) == 2
    assert next_token is not None

    # Segunda página: usar next_token
    items_page2, next_token2 = services.list_email_status_paginated(
        status=[EmailStatus.SENT],
        from_date=None,
        to_date=None,
        limit=2,
        next_token=next_token,
    )

    # En total teníamos 3 SENT
    all_emails = {r.email for r in items_page1 + items_page2}
    assert len(all_emails) == 3
    # Ya no debería haber más páginas
    assert next_token2 is None


@mock_aws
def test_list_email_status_paginated_scan_all(monkeypatch):
    """
    Verifica que list_email_status_paginated:
    - Escanea toda la tabla cuando no se pasa status.
    - Pagina correctamente con limit y nextToken.
    """
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = _create_dynamodb_table(dynamodb)

    monkeypatch.setenv("EMAILS_TABLE_NAME", "emails")

    now = datetime.now(timezone.utc)

    # Insertamos 5 items con distintos estados
    for i in range(5):
        status = EmailStatus.SENT if i % 2 == 0 else EmailStatus.PENDING
        ts = (now - timedelta(minutes=i)).isoformat()
        table.put_item(
            Item={
                "batch_id": "b2",
                "email_id": f"user{i}@example.com",
                "email": f"user{i}@example.com",
                "subject": "Test",
                "content": "content",
                "status": status.value,
                "error_message": None,
                "created_at": ts,
                "updated_at": ts,
            }
        )

    from app import services

    importlib.reload(services)

    # Primera página: sin filtro de status, limit=3
    items_page1, next_token = services.list_email_status_paginated(
        status=None,
        from_date=None,
        to_date=None,
        limit=3,
        next_token=None,
    )

    assert len(items_page1) == 3
    assert next_token is not None

    # Segunda página
    items_page2, next_token2 = services.list_email_status_paginated(
        status=None,
        from_date=None,
        to_date=None,
        limit=3,
        next_token=next_token,
    )

    assert len(items_page2) == 2  # 5 en total
    assert next_token2 is None

    all_emails = {r.email for r in items_page1 + items_page2}
    assert len(all_emails) == 5
