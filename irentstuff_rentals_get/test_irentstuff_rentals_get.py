from logging import getLogger
import json
import pytest
from unittest import mock
from decimal import Decimal
from irentstuff_rentals_get import connect_to_db, get_rentals, retrieve_updated_rental

log = getLogger(__name__)

# Mock the Lambda event and context
@pytest.fixture
def mock_event():
    return {
        "pathParameters": {"item_id": "123", "rental_id": "456"},
        "queryStringParameters": {"type": "all"}
    }


@pytest.fixture
def mock_context():
    return {}


# Mock the database connection and cursor
@pytest.fixture
def mock_cursor():
    mock_cursor = mock.MagicMock()
    mock_cursor.fetchone.return_value = {
        "rental_id": "456",
        "owner_id": "owner123",
        "renter_id": "renter123",
        "item_id": "123",
        "start_date": "2023-09-28",
        "end_date": "2023-09-30",
        "status": "active",
        "price_per_day": Decimal("10.50"),
        "deposit": Decimal("50.00"),
        "created_at": "2023-09-20T00:00:00",
        "updated_at": "2023-09-28T00:00:00"
    }
    mock_cursor.fetchall.return_value = [mock_cursor.fetchone.return_value]
    return mock_cursor


@pytest.fixture
def mock_db_conn(mock_cursor):
    """Creates a mock DB connection with a mock cursor and close method."""
    mock_conn = mock.MagicMock()

    # Set up the context management for the mock connection
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__ = mock.Mock()

    # Mock the close method explicitly
    mock_conn.close = mock.Mock()

    return mock_conn


def test_get_rentals_success(mock_db_conn, mock_cursor, mock_event, mock_context):
    # Mock connect_to_db to return the mock_db_conn
    with mock.patch("irentstuff_rentals_get.connect_to_db", return_value=mock_db_conn):
        response = get_rentals(mock_event, mock_context)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert isinstance(body, list)
        assert body[0]["rental_id"] == "456"
        assert body[0]["price_per_day"] == 10.5
        assert body[0]["deposit"] == 50.0


def test_get_rentals_db_connection_error(mock_event, mock_context):
    # Mock connect_to_db to raise an exception
    with mock.patch("irentstuff_rentals_get.connect_to_db", side_effect=Exception("DB connection failed")):
        response = get_rentals(mock_event, mock_context)
        print("\n\n\nHERE\n\n\n")
        print(f'{response["body"]=}')
        assert response["statusCode"] == 500
        assert "DB connection failed" in response["body"]


def test_get_rentals_no_rentals_found(mock_db_conn, mock_cursor, mock_event, mock_context):
    # Mock connect_to_db to return the mock_db_conn
    with mock.patch("irentstuff_rentals_get.connect_to_db", return_value=mock_db_conn):
        # Mock fetchall to return an empty list
        mock_cursor.fetchall.return_value = []
        response = get_rentals(mock_event, mock_context)
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "No rentals found"


def test_retrieve_updated_rental(mock_db_conn, mock_cursor):
    # Test retrieve_updated_rental directly
    result = retrieve_updated_rental(mock_cursor, "123", "456")
    assert result["rental_id"] == "456"
    assert result["item_id"] == "123"
    assert result["price_per_day"] == 10.5
    assert result["deposit"] == 50.0
