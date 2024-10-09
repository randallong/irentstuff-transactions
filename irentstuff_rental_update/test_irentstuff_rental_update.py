import json
import os
import pymysql
import pytest
import requests

from datetime import datetime, date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch, MagicMock

from irentstuff_rental_update import (
    invoke_auth_lambda,
    connect_to_db,
    response_headers,
    get_updated_rental,
    update_db,
    update_availability_in_items_db,
    update_rental_status
)


class TestAuthLambda:
    @patch("irentstuff_rental_update.lambda_client.invoke")
    def test_invoke_auth_lambda_success(self, mock_invoke):
        # Mock successful Lambda invocation
        mock_payload = {
            'body': json.dumps({"user": "authenticated_user"})
        }
        mock_response = {
            'StatusCode': 200,
            'Payload': MagicMock(read=MagicMock(return_value=json.dumps(mock_payload)))
        }

        mock_invoke.return_value = mock_response
        jwt_token = "test_jwt_token"

        # Call the function
        result = invoke_auth_lambda(jwt_token)

        # Assertions
        mock_invoke.assert_called_once_with(
            FunctionName='irentstuff-authenticate-user',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "headers": {
                    "Authorization": jwt_token
                }
            })
        )

        assert result == {"user": "authenticated_user"}

    @patch("irentstuff_rental_update.lambda_client.invoke")
    def test_invoke_auth_lambda_failure(self, mock_invoke):
        # Mock failed Lambda invocation
        mock_response = MagicMock()
        mock_response['StatusCode'] = 500
        mock_payload = {
            'body': json.dumps({"error": "authentication failed"})
        }
        mock_response['Payload'].read.return_value = json.dumps(mock_payload)

        mock_invoke.return_value = mock_response
        jwt_token = "invalid_jwt_token"

        # Call the function and expect it to raise an exception
        with pytest.raises(Exception) as exc_info:
            invoke_auth_lambda(jwt_token)

        mock_invoke.assert_called_once_with(
            FunctionName='irentstuff-authenticate-user',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "headers": {
                    "Authorization": jwt_token
                }
            })
        )
        assert str(exc_info.value) == 'Authentication failed: {"error": "authentication failed"}'


class TestConnectToDB(TestCase):
    @classmethod
    def setUpClass(cls):
        # Set up environment variables for testing
        os.environ["DB1_USER_NAME"] = "test_user"
        os.environ["DB1_PASSWORD"] = "test_password"
        os.environ["DB1_RDS_PROXY_HOST"] = "test_host"
        os.environ["DB1_NAME"] = "test_db"

    @patch("pymysql.connect")
    def test_connect_to_db_success(self, mock_connect):
        # Mock the connection object
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Call the function
        result = connect_to_db()

        # Assert that the connect function was called with the expected arguments
        mock_connect.assert_called_once_with(
            host=os.environ["DB1_RDS_PROXY_HOST"],
            user=os.environ["DB1_USER_NAME"],
            passwd=os.environ["DB1_PASSWORD"],
            db=os.environ["DB1_NAME"],
            connect_timeout=5
        )

        # Assert that the returned connection is the mocked connection
        self.assertEqual(result, mock_conn)

    @patch("pymysql.connect")
    @patch("sys.exit")  # Mock sys.exit to prevent the script from exiting
    def test_connect_to_db_failure(self, mock_exit, mock_connect):
        # Simulate a MySQL error when trying to connect
        mock_connect.side_effect = pymysql.MySQLError("Connection error")

        # Call the function (no need to expect SystemExit since we're mocking sys.exit)
        connect_to_db()

        # Assert that sys.exit was called with the correct exit code
        mock_exit.assert_called_once_with(1)


class TestResponseHeaders:
    def test_response_headers(self):
        # Test case for when content_type is 'application/json'
        content_type = "application/json"
        expected_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_headers(content_type)
        assert result == expected_headers
        assert result['Content-Type'] == 'application/json'

    def test_response_headers_text(self):
        # Test case for when content_type is 'text/html'
        content_type = "text/html"
        expected_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_headers(content_type)
        assert result == expected_headers
        assert result['Content-Type'] == 'text/html'


class TestGetUpdatedRental(TestCase):
    def test_get_updated_rental_found(self):
        # Mock the cursor and its fetchone() method
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "created_at": datetime(2023, 10, 1, 14, 30, 0),
            "updated_at": datetime(2023, 10, 5, 16, 45, 0),
            "owner_id": "owner_001",
            "renter_id": "renter_002",
            "item_id": "item_123",
            "start_date": date(2023, 10, 1),
            "end_date": date(2023, 10, 5),
            "status": "active",
            "price_per_day": Decimal('15.00'),
            "deposit": Decimal('100.00'),
        }

        # Call the function
        response = get_updated_rental(mock_cursor, "item_123", "rental_123")

        # Expected response
        expected_response = {
            "rental_id": "rental_123",
            "created_at": "2023-10-01T14:30:00",
            "updated_at": "2023-10-05T16:45:00",
            "owner_id": "owner_001",
            "renter_id": "renter_002",
            "item_id": "item_123",
            "start_date": "2023-10-01",
            "end_date": "2023-10-05",
            "status": "active",
            "price_per_day": 15.00,
            "deposit": 100.00
        }

        # Assert the response matches the expected response
        self.assertEqual(response, expected_response)

    def test_get_updated_rental_not_found(self):
        # Mock the cursor's fetchone() method to return None
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        # Call the function
        response = get_updated_rental(mock_cursor, "item_123", "rental_999")

        # Expected response for rental not found
        expected_response = {"error": "Rental not found"}

        # Assert the response matches the expected response
        self.assertEqual(response, expected_response)


class TestUpdateDB(TestCase):

    @patch("irentstuff_rental_update.get_updated_rental")  # Mock get_updated_rental function
    def test_update_db_success(self, mock_get_updated_rental):
        # Mock cursor and transactions_conn
        mock_cursor = MagicMock()
        mock_transactions_conn = MagicMock()

        # Mock the updated rental response from get_updated_rental
        mock_get_updated_rental.return_value = {
            "rental_id": "rental_123",
            "status": "returned",
            "item_id": "item_123",
            "owner_id": "owner_001",
            "renter_id": "renter_002",
            "start_date": "2023-10-01",
            "end_date": "2023-10-05",
            "price_per_day": 15.00,
            "deposit": 100.00,
        }

        # Call the function
        response = update_db(
            cursor=mock_cursor,
            new_status="returned",
            rental_id="rental_123",
            item_id="item_123",
            transactions_conn=mock_transactions_conn
        )

        # Assert that the update query was executed with the correct parameters
        mock_cursor.execute.assert_called_once_with(
            "UPDATE Rentals SET status = %s WHERE rental_id = %s AND item_id = %s",
            ("returned", "rental_123", "item_123")
        )

        # Assert that the transaction was committed
        mock_transactions_conn.commit.assert_called_once()

        # Expected response
        expected_response = {
            "statusCode": 200,
            "headers": {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Content-Type': 'application/json'
                },  # Assuming response_headers returns this
            "body": json.dumps({
                "rental_id": "rental_123",
                "status": "returned",
                "item_id": "item_123",
                "owner_id": "owner_001",
                "renter_id": "renter_002",
                "start_date": "2023-10-01",
                "end_date": "2023-10-05",
                "price_per_day": 15.00,
                "deposit": 100.00,
            })
        }
        print(response)

        # Assert that the response matches the expected response
        self.assertEqual(response, expected_response)

    def test_update_db_error(self):
        # Mock cursor and transactions_conn
        mock_cursor = MagicMock()
        mock_transactions_conn = MagicMock()

        # Simulate an error during the update operation
        mock_cursor.execute.side_effect = Exception("Update error")

        # Call the function and expect an exception to be raised
        with self.assertRaises(Exception) as context:
            update_db(
                cursor=mock_cursor,
                new_status="returned",
                rental_id="rental_123",
                item_id="item_123",
                transactions_conn=mock_transactions_conn
            )

        # Assert that the exception message is correct
        self.assertEqual(str(context.exception), "Update error")

        # Assert that commit was not called due to the exception
        mock_transactions_conn.commit.assert_not_called()


class TestUpdateAvailabilityInItemsDB(TestCase):

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_success(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "available"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Availability updated"}
        mock_patch.return_value = mock_response

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Verify that requests.patch was called with the correct parameters
        api_url = f"https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/{item_id}"
        expected_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        expected_payload = {"availability": availability}

        mock_patch.assert_called_once_with(api_url, headers=expected_headers, json=expected_payload)

        # Assert that the result matches the expected response
        expected_result = {"message": "Availability updated"}
        self.assertEqual(result, expected_result)

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_failure(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "unavailable"

        # Mock the response object to simulate a failure
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_patch.return_value = mock_response

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Assert that the result contains the status code and body
        expected_result = {
            "status_code": 400,
            "body": "Bad Request"
        }
        self.assertEqual(result, expected_result)

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_request_exception(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "available"

        # Simulate a RequestException
        mock_patch.side_effect = requests.exceptions.RequestException("Connection error")

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Assert that the result contains the expected error message
        expected_result = {
            "status_code": 500,
            "body": "Error occurred while making API call: Connection error"
        }
        self.assertEqual(result, expected_result)


class TestUpdateRentalStatus(TestCase):

    @patch("irentstuff_rental_update.connect_to_db")  # Mock the database connection
    @patch("irentstuff_rental_update.invoke_auth_lambda")  # Mock the auth lambda function
    @patch("irentstuff_rental_update.update_db")  # Mock the update_db function
    @patch("irentstuff_rental_update.update_availability_in_items_db")  # Mock the update_availability_in_items_db function
    def test_update_rental_status_confirm_success(self, mock_update_availability, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "owner_user"
        }

        # Mock rental data
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "item_id": "item_123",
            "owner_id": "owner_user",
            "renter_id": "renter_user",
            "status": "offered"
        }

        mock_update_db.return_value = {
            "statusCode": 200,
            "body": "Rental status updated successfully"
        }

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Verify the update_db was called with the correct parameters
        mock_update_db.assert_called_once()
        self.assertEqual(result["statusCode"], 200)

    @patch("irentstuff_rental_update.connect_to_db")  # Mock the database connection
    @patch("irentstuff_rental_update.invoke_auth_lambda")  # Mock the auth lambda function
    @patch("irentstuff_rental_update.update_db")  # Mock the update_db function
    @patch("irentstuff_rental_update.update_availability_in_items_db")  # Mock the update_availability_in_items_db function
    def test_update_rental_status_start_success(self, mock_update_availability, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "owner_user"
        }

        # Mock rental data
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "item_id": "item_123",
            "owner_id": "owner_user",
            "renter_id": "renter_user",
            "status": "confirmed"
        }

        mock_update_db.return_value = {
            "statusCode": 200,
            "body": "Rental status updated successfully"
        }

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "start"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Verify the update_db was called with the correct parameters
        mock_update_db.assert_called_once()
        self.assertEqual(result["statusCode"], 200)

    @patch("irentstuff_rental_update.connect_to_db")  # Mock the database connection
    @patch("irentstuff_rental_update.invoke_auth_lambda")  # Mock the auth lambda function
    @patch("irentstuff_rental_update.update_db")  # Mock the update_db function
    @patch("irentstuff_rental_update.update_availability_in_items_db")  # Mock the update_availability_in_items_db function
    def test_update_rental_status_cancel_success(self, mock_update_availability, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "owner_user"
        }

        # Mock rental data
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "item_id": "item_123",
            "owner_id": "owner_user",
            "renter_id": "renter_user",
            "status": "confirmed"
        }

        mock_update_db.return_value = {
            "statusCode": 200,
            "body": "Rental status updated successfully"
        }

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "cancel"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Verify the update_db was called with the correct parameters
        mock_update_db.assert_called_once()
        self.assertEqual(result["statusCode"], 200)

    @patch("irentstuff_rental_update.connect_to_db")  # Mock the database connection
    @patch("irentstuff_rental_update.invoke_auth_lambda")  # Mock the auth lambda function
    @patch("irentstuff_rental_update.update_db")  # Mock the update_db function
    @patch("irentstuff_rental_update.update_availability_in_items_db")  # Mock the update_availability_in_items_db function
    def test_update_rental_status_complete_success(self, mock_update_availability, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "owner_user"
        }

        # Mock rental data
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "item_id": "item_123",
            "owner_id": "owner_user",
            "renter_id": "renter_user",
            "status": "ongoing"
        }

        mock_update_db.return_value = {
            "statusCode": 200,
            "body": "Rental status updated successfully"
        }

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "complete"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Verify the update_db was called with the correct parameters
        mock_update_db.assert_called_once()
        self.assertEqual(result["statusCode"], 200)

    @patch("irentstuff_rental_update.connect_to_db")
    @patch("irentstuff_rental_update.invoke_auth_lambda")
    def test_update_rental_status_invalid_token(self, mock_invoke_auth, mock_connect):
        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is invalid",
            "username": "user"
        }

        # Create the event
        event = {
            "pathParameters": {},
            "headers": {
                "Authorization": "Bearer invalid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Check the response
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(result["body"], "Your user token is invalid.")

    @patch("irentstuff_rental_update.connect_to_db")
    @patch("irentstuff_rental_update.invoke_auth_lambda")
    @patch("irentstuff_rental_update.update_db")
    def test_update_rental_status_not_found(self, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "owner_user"
        }

        # Mock rental not found
        mock_cursor.fetchone.return_value = None

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Check the response
        self.assertEqual(result["statusCode"], 404)
        self.assertEqual(result["body"], "Rental ID rental_123 with Item ID item_123 not found.")

    @patch("irentstuff_rental_update.connect_to_db")
    @patch("irentstuff_rental_update.invoke_auth_lambda")
    @patch("irentstuff_rental_update.update_db")
    def test_update_rental_status_permission_denied(self, mock_update_db, mock_invoke_auth, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock auth response
        mock_invoke_auth.return_value = {
            "message": "Token is valid",
            "username": "non_owner_user"
        }

        # Mock rental data
        mock_cursor.fetchone.return_value = {
            "rental_id": "rental_123",
            "item_id": "item_123",
            "owner_id": "owner_user",
            "renter_id": "renter_user",
            "status": "offered"
        }

        # Create the event
        event = {
            "pathParameters": {
                "item_id": "item_123",
                "rental_id": "rental_123",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        # Call the function
        result = update_rental_status(event, None)

        # Check the response
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(result["body"], "Only the item owner can confirm the rental request.")
