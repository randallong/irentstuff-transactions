"""
Update a rental status in the Rentals db. The following are allowed:

confirm - Triggered by Owner upon accepting rental offer from Renter
start - Triggered by Owner upon collection of rental item
cancel - Triggered by Owner or Renter only when rental status is in 'confirm' or 'start' status
compelte - Triggered by Owner upon accepting rental offer from Renter

TODO:
1. Confirm - if there are several active rental offers that overlap on the same date, once one is accepted, the rest are cancelled
    - Notify Owner and Renters when these cancellations are made
    - Rental offers on different dates should not be cancelled
"""

from datetime import (datetime, date)
from decimal import Decimal

import boto3
import sys
import logging
import pymysql
import json
import os
import requests

from websocket import create_connection

log = logging.getLogger()
log.setLevel(logging.INFO)

lambda_client = boto3.client('lambda', region_name="ap-southeast-1")


def invoke_auth_lambda(jwt_token):
    # Prepare the payload to send to the authentication Lambda
    payload = {
        "headers": {
            "Authorization": jwt_token
        }
    }

    # Invoke the authentication Lambda function
    response = lambda_client.invoke(
        FunctionName='irentstuff-authenticate-user',  # Replace with the actual Lambda function name
        InvocationType='RequestResponse',  # Synchronous invocation
        Payload=json.dumps(payload)
    )

    # Read the response from the invoked function
    response_payload = json.loads(response['Payload'].read())
    log.info(response_payload)

    # Process the response based on the status code
    if response['StatusCode'] == 200:
        # The authentication Lambda responded successfully
        return json.loads(response_payload.get('body'))
    else:
        # Handle the case where the authentication failed
        raise Exception(f"Authentication failed: {response_payload.get('body')}")


def connect_to_db():
    "Connect to Transactions DB"
    transactions_conn = None
    transactions_db_user_name = os.environ["DB1_USER_NAME"]
    transactions_db_password = os.environ["DB1_PASSWORD"]
    transactions_db_rds_proxy_host = os.environ["DB1_RDS_PROXY_HOST"]
    transactions_db_name = os.environ["DB1_NAME"]

    try:
        transactions_conn = pymysql.connect(
            host=transactions_db_rds_proxy_host,
            user=transactions_db_user_name,
            passwd=transactions_db_password,
            db=transactions_db_name,
            connect_timeout=5
            )
        log.info("SUCCESS: Connection to Transactions DB succeeded")
    except pymysql.MySQLError as e:
        log.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        log.error(e)
        sys.exit(1)
    return transactions_conn


def send_message(content):
    try:
        token = content.get("token")
        ws = create_connection(f"wss://6z72j61l2b.execute-api.ap-southeast-1.amazonaws.com/dev/?token={token}")
        log.info("WebSocket connection opened")

        message = {
            "action": "sendmessage",
            "message": "Admin message",
            "itemid": content.get("itemId"),
            "ownerid": content.get("ownerid"),
            "renterid": content.get("renterId"),
            "sender": content.get("username"),
            "timestamp": datetime.now().isoformat(),
            "admin": content.get("admin")
        }
        log.info(json.dumps(message))
        ws.send(json.dumps(message))
        log.info("Message sent")
        result = ws.recv()
        log.info("Received '%s'" % result)
        ws.close()
        log.info("Message successfully sent!")

        return {
            "statusCode": 200,
            "body": "WebSocket connection initiated"
        }
    except Exception as e:
        log.error("Message failed to send!")
        return {
            "statusCode": 500,
            "body": f"Error encountered: {e}"
        }


def response_headers(content_type: str):
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Content-Type': content_type
    }
    return headers


def get_updated_rental(cursor, item_id, rental_id):
    retrieve_query = "SELECT * FROM Rentals WHERE item_id = %s AND rental_id = %s"
    cursor.execute(retrieve_query, (item_id, rental_id))
    rental = cursor.fetchone()
    log.info(rental)

    if rental:
        response = {
            "rental_id": rental["rental_id"],
            "created_at": rental["created_at"].isoformat() if isinstance(rental["created_at"], (datetime, date)) else rental["created_at"],
            "updated_at": rental["updated_at"].isoformat() if isinstance(rental["updated_at"], (datetime, date)) else rental["updated_at"],
            "owner_id": rental["owner_id"],
            "renter_id": rental["renter_id"],
            "item_id": rental["item_id"],
            "start_date": rental["start_date"].isoformat() if isinstance(rental["start_date"], date) else rental["start_date"],
            "end_date": rental["end_date"].isoformat() if isinstance(rental["end_date"], date) else rental["end_date"],
            "status": rental["status"],
            "price_per_day": float(rental["price_per_day"]) if isinstance(rental["price_per_day"], Decimal) else rental["price_per_day"],
            "deposit": float(rental["deposit"]) if isinstance(rental["deposit"], Decimal) else rental["deposit"],
        }
        return response
    else:
        return {"error": "Rental not found"}


def update_db(cursor, new_status, rental_id, item_id, transactions_conn):
    # Update the rental status in the DB
    update_query = "UPDATE Rentals SET status = %s WHERE rental_id = %s AND item_id = %s"
    cursor.execute(update_query, (new_status, rental_id, item_id))
    transactions_conn.commit()

    # Retrieve and return the updated rental
    response = get_updated_rental(cursor, item_id, rental_id)

    return {
        "statusCode": 200,
        "headers": response_headers('application/json'),
        "body": json.dumps(response)
    }


def update_availability_in_items_db(token, item_id, availability):
    """Updates item availability in the item DB via API using a PATCH request"""

    api_url = f"https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/{item_id}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # JSON body for the PATCH request
    payload = {
        "availability": availability
    }

    try:
        # Make the PATCH request
        response = requests.patch(api_url, headers=headers, json=payload)

        if response.status_code == 200:
            log.info(f"Availability for item {item_id} successfully updated to {availability}")
            return response.json()
        else:
            return {
                "status_code": response.status_code,
                "body": response.text
            }

    except requests.exceptions.RequestException as e:
        return {
            "status_code": 500,
            "body": f"Error occurred while making API call: {str(e)}"
        }


def update_rental_status(event, context):
    transactions_conn = connect_to_db()
    log.info(event)

    item_id = event.get("pathParameters", {}).get("item_id")
    rental_id = event.get("pathParameters", {}).get("rental_id")
    action = event.get("pathParameters", {}).get("action")  # Accepted actions: "confirm", "start", "cancel", "complete"
    log.info(f"item_id: {item_id}, rental_id: {rental_id}, action: {action}")

    token = event["headers"]["Authorization"]
    clean_token = token.replace("Bearer ", "").strip()

    auth = invoke_auth_lambda(clean_token)
    log.info(f"{auth=}")
    auth_result = auth['message']
    requestor = auth['username']
    log.info(f"{auth_result=}")
    log.info(f"{requestor=}")

    if auth_result != "Token is valid":
        log.error("User token is invalid")
        return {"statusCode": 401,
                "headers": response_headers('text/plain'),
                "body": "Your user token is invalid."}
    else:
        try:
            with transactions_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # Retrieve the rental by rental_id and item_id
                log.info(f"rental_id: {rental_id}, item_id: {item_id}")
                select_query = "SELECT * FROM Rentals WHERE rental_id = %s AND item_id = %s"
                cursor.execute(select_query, (rental_id, item_id))
                rental = cursor.fetchone()

                if rental:
                    log.info(f"{rental=}")
                    item_owner = rental["owner_id"]
                    item_renter = rental["renter_id"]
                    current_status = rental["status"]

                    content = {
                        "token": clean_token,
                        "itemId": item_id,
                        "ownerid": item_owner,
                        "renterId": requestor
                    }

                    # Confirm rental
                    if action == 'confirm' and current_status == 'offered':
                        if requestor == item_owner:
                            new_status = 'confirmed'
                            log.info(f"Request passed all authentication checks. Item will be {new_status}")
                            db_update = update_db(cursor, new_status, rental_id, item_id, transactions_conn)

                            # Send message
                            content["username"] = item_owner
                            content["admin"] = "confirmed"
                            message_response = send_message(content)
                            log.info(message_response)
                        else:
                            log.error("Requestor is not item owner")
                            db_update = {"statusCode": 401,
                                         "headers": response_headers('text/plain'),
                                         "body": "Only the item owner can confirm the rental request."}

                    # Start rental
                    elif action == 'start' and current_status == 'confirmed':
                        if requestor == item_owner:
                            new_status = 'ongoing'
                            log.info(f"Request passed all authentication checks. Item will be {new_status}")
                            db_update = update_db(cursor, new_status, rental_id, item_id, transactions_conn)

                            # Update availability in items DB
                            update_availability_in_items_db(clean_token, item_id, availability="active_rental")

                            # Send message
                            content["username"] = item_owner
                            content["admin"] = "active"
                            message_response = send_message(content)
                            log.info(message_response)
                        else:
                            log.error("Requestor is not item owner")
                            db_update = {"statusCode": 401,
                                         "headers": response_headers('text/plain'),
                                         "body": "Only the item owner can start the rental activity."}

                    # Cancel rental
                    elif action == 'cancel' and current_status in ('offered', 'confirmed'):
                        if requestor in (item_owner, item_renter):
                            new_status = 'cancelled'
                            log.info(f"Request passed all authentication checks. Item will be {new_status}")
                            db_update = update_db(cursor, new_status, rental_id, item_id, transactions_conn)

                            # Update availability in items DB
                            update_availability_in_items_db(clean_token, item_id, availability="available")

                            # Send message
                            content["username"] = requestor
                            content["admin"] = "cancelled"
                            message_response = send_message(content)
                            log.info(message_response)
                        else:
                            log.error("Requestor is not item owner or renter")
                            db_update = {"statusCode": 401,
                                         "headers": response_headers('text/plain'),
                                         "body": "Only the item owner or renter can cancel the rental request."}

                    # Complete rental
                    elif action == 'complete' and current_status == 'ongoing':
                        if requestor == item_owner:
                            new_status = 'completed'
                            log.info(f"Request passed all authentication checks. Item will be {new_status}")
                            db_update = update_db(cursor, new_status, rental_id, item_id, transactions_conn)

                            # Update availability in items DB
                            update_availability_in_items_db(clean_token, item_id, availability="available")

                            # Send message
                            content["username"] = item_owner
                            content["admin"] = "completed"
                            message_response = send_message(content)
                            log.info(message_response)
                        else:
                            log.error("Requestor is not item owner")
                            db_update = {"statusCode": 401,
                                         "headers": response_headers('text/plain'),
                                         "body": "Only the item owner can complete the rental request."}
                    else:
                        db_update = {
                            "statusCode": 400,
                            "headers": response_headers('text/plain'),
                            "body": f"Cannot perform '{action}' update on Item ID '{item_id}' with Rental ID '{rental_id}' because the current status is '{current_status}'."
                        }
                    return db_update
                else:
                    return {
                        "statusCode": 404,
                        "headers": response_headers('text/plain'),
                        "body": f"Rental ID {rental_id} with Item ID {item_id} not found."
                    }
        except pymysql.MySQLError as e:
            return {
                "statusCode": 500,
                "headers": response_headers('text/plain'),
                "body": f"An error occurred while updating the rental status: {str(e)}"
            }
        finally:
            transactions_conn.close()
