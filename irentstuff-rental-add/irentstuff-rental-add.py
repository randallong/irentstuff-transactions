"""
This function is triggered by a Renter and creates a new RDS database table and writes records to it
    Item availability should have 4 states:
    1. available
    2. active_rental
    3. pending_purchase
    4. sold

TODO
1. Rental requests should only be disallowed if the rental period overlaps with a confirmed one.
If an item status is returned as "active_rental", the rental period should be checked for conflicts.
If no conflict, rental should be allowed to proceed.
If conflict, return error message

2. Multiple rental requests should be allowed if the item status is still "available".

3. If an offer has been made by the renter for the same period, a second offer should not be allowed
"""

import boto3
import json
import logging
import os
import pymysql
import requests
import sys

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
            "body": f"Error occurred while making API call: {str(e)}"
        }
        
        
def check_item_rental_status(transactions_conn, item_id):
    log.info(f"Checking for active rentals for item {item_id}")
    try:
        with transactions_conn.cursor() as cursor:
            sql_query = """
                SELECT * FROM Rentals
                WHERE item_id = %s AND status NOT IN ('offered', 'cancelled', 'completed')
            """
            cursor.execute(sql_query, (item_id,))
            results = cursor.fetchall()
            log.info(f"Active rentals: {results}")
            
            if results:
                return {
                    "status_code": 403,
                    "body": f"Active rentals found for item_id {item_id}: {results}"
                }
            else:
                return {
                    "status_code": 200,
                    "body": f"No active rentals found for item_id {item_id}"
                }
    except pymysql.MySQLError as e:
        return {
            "status_code": 500,
            "body": f"An error occurred while querying the database: {str(e)}"
        }
        
        
def create_rental_table(transactions_conn):
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS Rentals (
            rental_id INT AUTO_INCREMENT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            owner_id VARCHAR(255) NOT NULL,
            renter_id VARCHAR(255) NOT NULL,
            item_id INT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            status VARCHAR(255) NOT NULL,
            price_per_day DECIMAL(10, 2) NOT NULL,
            deposit DECIMAL(10, 2) NOT NULL
        )
    """
    # Create the table if it doesn't exist
    with transactions_conn.cursor() as cur:
        cur.execute(create_table_sql)
        transactions_conn.commit()
        
        
def create_rental_entry(transactions_conn, event, item_id):
    body = json.loads(event['body'])
    users = body["users"]
    rental_details = body["rental_details"]

    # Create rental variables
    sql_string = """
        INSERT INTO Rentals (
            owner_id, renter_id, item_id, start_date, end_date, status,
            price_per_day, deposit
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    values = (
        users["owner_id"],
        users["renter_id"],
        item_id,
        rental_details["start_date"],
        rental_details["end_date"],
        "offered",
        float(rental_details["price_per_day"]),
        float(rental_details["deposit"]),
    )
    
    log.info(f"Will insert:\n{values}")

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cur:
            # Insert the entry
            cur.execute(sql_string, values)
            transactions_conn.commit()
            
            # Get the rental_id of the newly inserted entry
            cur.execute("SELECT LAST_INSERT_ID() as rental_id")
            rental_id = cur.fetchone()["rental_id"]
            log.info(f"New rental_id is {rental_id}")
        
            # Get details of the newly inserted entry
            cur.execute("SELECT * FROM Rentals WHERE rental_id = %s", (rental_id,))
            rental = cur.fetchone()
            log.info("Rental entry successfully inserted")
            
            response = {
                "statusCode": 200,
                "headers": response_headers('application/json'),
                "body": json.dumps({
                    "rental_id": rental["rental_id"],
                    "owner_id": rental["owner_id"],
                    "renter_id": rental["renter_id"],
                    "item_id": rental["item_id"],
                    "start_date": rental["start_date"].isoformat(),
                    "end_date": rental["end_date"].isoformat(),
                    "status": rental["status"],
                    "price_per_day": float(rental["price_per_day"]),
                    "deposit": float(rental["deposit"]),
                    "created_at": rental["created_at"].isoformat(),
                    "updated_at": rental["updated_at"].isoformat()
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


def add_rental(event, context):
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
    log.info(f"Rental requestor: {requestor}, Item owner: {item_owner}. Renting from self: {requestor==item_owner}")

    if auth_result != "Token is valid":
        log.error("User token is invalid")
        return {"statusCode": 401,
            "headers": response_headers('text/plain'),
            "body": "Your user token is invalid."}
    elif requestor == item_owner:
        log.error("Owner cannot rent their own item")
        return {"statusCode": 400,
            "headers": response_headers('text/plain'),
            "body": "You cannot rent your own item."}
    else:
        if item_availability == "active_rental":
            return {"statusCode": 400,
            "headers": response_headers('text/plain'),
            "body": "There are active rentals for this item. You cannot add a new rental."}
        elif item_availability == "pending_purchase":
            return {"statusCode": 400,
            "headers": response_headers('text/plain'),
            "body": "There are pending purchases for this item. You cannot add a new rental."}
        elif item_availability == "sold":
            return {"statusCode": 400,
            "headers": response_headers('text/plain'),
            "body": "Item has been sold. You cannot rent it out. To rent out another copy of this item, please create a new entry using the 'Add Stuff' button."}
        elif item_availability == "available":
            log.info(f"Item ID [{item_id}], is {item_availability}. Confirming in Transactions DB.")
            
            try:
                transactions_conn = connect_to_db()
                create_rental_table(transactions_conn) # if it doesn't exist
                
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
                    log.info(f"No existing active rentals found for item_id {item_id}. Proceeding to create new rental entry.")
                    return create_rental_entry(transactions_conn, event, item_id)
            except Exception as e:
                log.error(e)
            finally:
                transactions_conn.close()