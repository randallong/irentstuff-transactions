"""Creates a Purchase entry in the Purchases db. Triggered by Buyer

This function is triggered by a Renter and creates a new RDS database table and writes records to it
    Item availability should have 4 states:
    1. available
    2. active_rental
    3. pending_purchase
    4. sold


TODO
1. Purchase requests should only be disallowed if there is an active or confirmed rental
If an item status is returned as "active_rental", the purchase request should not be allowed.
"""

import boto3
import json
import logging
import os
import pymysql
import requests
import sys

from datetime import datetime, date

log = logging.getLogger()
log.setLevel(logging.INFO)

lambda_client = boto3.client('lambda')


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
            connect_timeout=5)
        log.info("SUCCESS: Connection to Transactions DB succeeded")
    except pymysql.MySQLError as e:
        log.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        log.error(e)
        sys.exit(1)
    return transactions_conn


def response_headers(content_type: str):
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Content-Type': content_type
    }
    return headers


def get_item(item_id):
    """Gets item details from the item DB via API"""

    api_url = f"https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/{item_id}"

    try:
        response = requests.get(api_url)

        if response.status_code == 200:
            return response.json()
        else:
            return {
                "status_code": response.status_code,
                "body": response.text
            }

    except requests.exceptions.RequestException as e:
        return {
            "status_code": 500,
            "headers": response_headers('text/plain'),
            "body": f"Error occurred while making API call: {str(e)}"
        }


def check_item_rental_status(transactions_conn, item_id):
    log.info(f"Checking for active rentals for item {item_id}")
    try:
        with transactions_conn.cursor() as cursor:
            sql_query = """
                SELECT * FROM Rentals
                WHERE item_id = %s AND status NOT IN ("cancelled", "completed")
            """
            cursor.execute(sql_query, (item_id,))
            results = cursor.fetchall()
            log.info(f"Active rentals: {results}")

            if results:
                return {
                    "status_code": 403,
                    "headers": response_headers('text/plain'),
                    "body": f"Active rentals found for item_id {item_id}: {results}"
                }
            else:
                return {
                    "status_code": 200,
                    "headers": response_headers('text/plain'),
                    "body": f"No active rentals found for item_id {item_id}"
                }
    except pymysql.MySQLError as e:
        return {
            "status_code": 500,
            "headers": response_headers('text/plain'),
            "body": f"An error occurred while querying the database: {str(e)}"
        }


def create_purchases_table(transactions_conn):
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS Purchases (
            purchase_id INT AUTO_INCREMENT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            owner_id VARCHAR(255) NOT NULL,
            buyer_id VARCHAR(255) NOT NULL,
            item_id INT NOT NULL,
            purchase_date DATE NULL,
            status VARCHAR(255) NOT NULL,
            purchase_price DECIMAL(10, 2) NOT NULL
    )
    """
    # Create the table if it doesn't exist
    with transactions_conn.cursor() as cur:
        cur.execute(create_table_sql)
        transactions_conn.commit()


def create_purchase_entry(transactions_conn, event, item_id):
    body = json.loads(event['body'])
    users = body["users"]

    sql_string = """
        insert into Purchases (
            owner_id, buyer_id, item_id, status, purchase_price
        )
        values(%s, %s, %s, %s, %s)
    """

    values = (
        users["owner_id"],
        users["buyer_id"],
        item_id,
        "offered",
        float(body["purchase_details"]["purchase_price"]),
    )

    log.info(f"Will insert:\n{values}")

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cur:
            # Insert the entry
            cur.execute(sql_string, values)
            transactions_conn.commit()

            # Get the purchase_id of the newly inserted entry
            cur.execute("SELECT LAST_INSERT_ID() as purchase_id")
            purchase_id = cur.fetchone()["purchase_id"]
            log.info(f"New purchase_id is {purchase_id}")

            # Get details of the newly inserted entry
            cur.execute("SELECT * FROM Purchases WHERE purchase_id = %s", (purchase_id,))
            purchase = cur.fetchone()
            log.info("Purchase entry successfully inserted")

            response = {
                "statusCode": 200,
                "headers": response_headers('application/json'),
                "body": json.dumps({
                    "purchase_id": purchase["purchase_id"],
                    "owner_id": purchase["owner_id"],
                    "buyer_id": purchase["buyer_id"],
                    "item_id": purchase["item_id"],
                    "status": purchase["status"],
                    "purchase_price": float(purchase["purchase_price"]),
                    "purchase_date": purchase["purchase_date"].isoformat() if purchase["purchase_date"] else None,
                    "created_at": purchase["created_at"].isoformat() if isinstance(purchase["created_at"], (datetime, date)) else purchase["created_at"],
                    "updated_at": purchase["updated_at"].isoformat() if isinstance(purchase["updated_at"], (datetime, date)) else purchase["updated_at"]
                })
            }
            log.info(f"Response: {response}")
            return response
    except pymysql.MySQLError as e:
        return {
            "statusCode": 500,
            "headers": response_headers('text/plain'),
            "body": f"An error occurred while querying the database: {str(e)}"
        }


def add_purchase(event, context):
    log.info(event)
    item_id = event.get('pathParameters', {}).get('item_id')
    token = event["headers"]["Authorization"]
    clean_token = token.replace("Bearer ", "").strip()

    auth = invoke_auth_lambda(clean_token)
    auth_result = auth['message']
    requestor = auth['username']

    item_details = get_item(item_id) # Use the get_item() method to make an API call to the items DB to retrieve item info.
    item_availability = item_details['availability']
    item_owner = item_details['owner']
    log.info(f"Purchase requestor: {requestor}, Item owner: {item_owner}. Renting from self: {requestor==item_owner}")

    if auth_result != "Token is valid":
        log.error("User token is invalid")
        return {"statusCode": 401,
                "headers": response_headers('text/plain'),
                "body": "Your user token is invalid."}
    elif requestor == item_owner:
        log.error("Owner cannot purchase their own item")
        return {"statusCode": 400,
                "headers": response_headers('text/plain'),
                "body": "You cannot purchase your own item."}
    else:
        if item_availability == "active_rental":
            return {"statusCode": 400,
                    "headers": response_headers('text/plain'),
                    "body": "There are active rentals for this item. You cannot buy it until the rental has completed."}
        elif item_availability == "pending_purchase":
            return {"statusCode": 400,
                    "headers": response_headers('text/plain'),
                    "body": "There are pending purchases for this item. You cannot buy it."}
        elif item_availability == "sold":
            return {"statusCode": 400,
                    "headers": response_headers('text/plain'),
                    "body": "Item has been sold. You cannot sell it again. To sell another copy of this item, please create a new entry using the 'Add Stuff' button."}
        elif item_availability == "available":
            log.info(f"Item ID [{item_id}], is {item_availability}. Confirming in Transactions DB.")

            try:
                transactions_conn = connect_to_db()
                create_purchases_table(transactions_conn)  # if it doesn't exist

                rentals = check_item_rental_status(transactions_conn, item_id)
                log.info(rentals)
                if rentals["status_code"] != 200:
                    return {
                        "statusCode": rentals["status_code"],
                        "headers": response_headers('application/json'),
                        "body": json.dumps({
                            "message": rentals["body"]
                        })
                    }
                else:
                    log.info(f"No existing active rentals found for item_id {item_id}. Proceeding to create new purchase entry.")
                    return create_purchase_entry(transactions_conn, event, item_id)
            except Exception as e:
                log.error(e)
            finally:
                transactions_conn.close()
