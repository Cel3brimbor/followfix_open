from flask import Flask, render_template, request, Response
import requests
import os
import json
from datetime import datetime, timedelta
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo.errors import ConnectionFailure, OperationFailure
import time
import random
import urllib3
import uuid
from requests.exceptions import ProxyError, ConnectionError
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

global response_size
response_size = 0

port = int(os.environ.get("PORT", 5000))

MONGO_URI = os.getenv("MONGO_URI", "enter URI here")
DB_NAME = os.getenv("MONGO_DB_NAME", "enter database's name here")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "enter database's collection name")

def debug_print(message):
    """Print message only if ENABLE_DEBUG is enabled."""
    ENABLE_DEBUG = True
    
    if ENABLE_DEBUG:
        print(f"DEBUG: {message}")

def get_proxy():
    decodo_username = os.getenv('DECODO_USERNAME', "username here")
    decodo_password = os.getenv('DECODO_PASSWORD', "password here")
    proxy_username = decodo_username  #sticky session

    proxy_host = "enter host endpoint"

    proxies = {
        "http": f"http://{proxy_username}:{decodo_password}@{proxy_host}",
        "https": f"http://{proxy_username}:{decodo_password}@{proxy_host}"
    }
    debug_print(f"Using Decodo proxy: {proxy_host} (sticky session)")
    try:
        response = requests.get("https://ipinfo.io/json", proxies=proxies, timeout=10, verify=False)
        if response.status_code == 200:
            geo_info = response.json()
            debug_print(f"Proxy connection successful. IP: {geo_info.get('ip', 'Unknown')}, Location: {geo_info.get('city', 'Unknown')}, {geo_info.get('country', 'Unknown')}")
        else:
            debug_print(f"Failed to retrieve proxy geo info: Status {response.status_code}, Response: {response.text[:100]}")
    except Exception as e:
        debug_print(f"Error testing proxy: {str(e)}")
    return proxies

def make_request_with_retry(url, headers, cookies, proxies, retries=3, timeout=15):
    for attempt in range(retries):
        try:
            proxy_host = proxies.get("https", "").split("@")[-1] if proxies.get("https") else "No proxy"
            #debug_print(f"Making request to {url} with proxy {proxy_host}, attempt {attempt + 1}")
            response = requests.get(url, headers=headers, cookies=cookies, proxies=proxies, timeout=timeout, verify=False)
            #debug_print(f"Request to {url} successful, status code: {response.status_code}")
            return response
        except (ProxyError, ConnectionError) as e:
            #debug_print(f"Request to {url} failed: {str(e)}, attempt {attempt + 1}")
            if attempt < retries - 1:
                time.sleep(2)
            continue
    debug_print(f"All {retries} retries failed for {url}")
    return None

def get_mongo_collection(db_name=DB_NAME, collection_name=COLLECTION_NAME):
    debug_print(f"Attempting to connect to MongoDB: {MONGO_URI}")
    client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
    try:
        db = client[db_name]
        collection = db[collection_name]
        debug_print(f"Successfully connected to MongoDB database: {db_name}, collection: {collection_name}")
        collection.create_index("_id")
        return client, collection
    except Exception as e:
        debug_print(f"Error connecting to MongoDB database {db_name}: {e}")
        print(f"Error connecting to MongoDB database {db_name}: {e}")
        client.close()
        raise

def save_user_document(username, user_data, db_name=DB_NAME, collection_name=COLLECTION_NAME):
    try:
        debug_print(f"Attempting to save document for user {username} to MongoDB")
        with MongoClient(MONGO_URI, server_api=ServerApi('1')) as client:
            db = client[db_name]
            collection = db[collection_name]
            result = collection.update_one(
                {"_id": username},
                {"$set": user_data},
                upsert=True
            )
            debug_print(f"Successfully saved document for user {username}, modified count: {result.modified_count}")
    except Exception as e:
        debug_print(f"Error saving document for user {username} to MongoDB: {e}")
        print(f"An error occurred while saving to MongoDB database {db_name} for user {username}: {e}")

def load_user_document(username, db_name=DB_NAME, collection_name=COLLECTION_NAME):
    try:
        debug_print(f"Attempting to load document for user {username} from MongoDB")
        with MongoClient(MONGO_URI, server_api=ServerApi('1')) as client:
            db = client[db_name]
            collection = db[collection_name]
            user_document = collection.find_one({"_id": username})
            if user_document:
                debug_print(f"Successfully loaded document for user {username}")
                user_document.pop('_id', None)
                return user_document
            else:
                debug_print(f"User document with _id '{username}' not found in MongoDB database {db_name}, collection {collection_name}")
                print(f"INFO: User document with _id '{username}' not found in MongoDB database {db_name}, collection {collection_name}. Returning empty document.")
                return {}
    except ConnectionFailure as e:
        debug_print(f"Connection failure to MongoDB database {db_name}: {e}")
        print(f"WARNING: Could not connect to MongoDB database {db_name}. Is the server running? Returning empty document. Details: {e}")
        return {}
    except OperationFailure as e:
        debug_print(f"MongoDB operation failure during load from database {db_name}: {e}")
        print(f"WARNING: MongoDB operation failed during load from database {db_name}. Returning empty document. Details: {e}")
        return {}
    except Exception as e:
        debug_print(f"Unexpected error loading document from MongoDB database {db_name}: {e}")
        print(f"WARNING: An unexpected error occurred while loading document from MongoDB database {db_name}. Returning empty document. Details: {e}")
        return {}

def reset_runcount(username):
    user_data = load_user_document(username)
    user_data["times_ran"] = 0
    save_user_document(username, user_data)

def save_user_data(session_id, username):
    user_data = load_user_document(username)
    now = datetime.now()
    current_timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    user_data["session_id"] = session_id
    user_data["last_run_time"] = current_timestamp_str
    times_ran = max(0, user_data.get("times_ran", 0))  # ensure non-negative
    if times_ran == 67:
        return
    elif times_ran >= 3:
        user_data["times_ran"] = 1
    else:
        user_data["times_ran"] = times_ran + 1
    user_data["times_ran_total"] = user_data.get("times_ran_total", 0) + 1
    save_user_document(username, user_data)

def verify_runtime(username):
    user_data = load_user_document(username)
    if user_data and "last_run_time" in user_data:
        last_run_time_str = user_data["last_run_time"]
        try:
            last_run_time = datetime.strptime(last_run_time_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            time_difference = now - last_run_time
            if time_difference < timedelta(hours=24):
                if user_data.get("times_ran", 0) < 3 or user_data.get("times_ran", 0) == 67:
                    return {"verified": True, "error": None}
                else:
                    remaining_seconds = (timedelta(hours=24) - time_difference).total_seconds()
                    hours_remaining = int(remaining_seconds // 3600) + 1
                    return {"verified": False, "error": f"You already used this site three times within the last 24 hours.\n\nPlease wait {hours_remaining} hours before using again."}
            else:
                if user_data.get("times_ran", 0) == 67:
                    return {"verified": True, "error": None}
                elif user_data.get("times_ran", 0) > 0:
                    reset_runcount(username)
                return {"verified": True, "error": None}
        except ValueError:
            print(f"WARNING: Invalid 'last_run_time' format for {username}: {last_run_time_str}. Resetting.")
            return {"verified": True, "error": None}
    return {"verified": True, "error": None}

def verify_session_id(session_id, claimed_username, proxy):
    headers = {
        "User-Agent": "Instagram 194.0.0.36.172 Android (28/9; 440dpi; 1080x2130; samsung; SM-G973F)",
        "x-ig-app-id": "936619743392459"
    }
    try:
        response = make_request_with_retry(
            "https://i.instagram.com/api/v1/accounts/current_user/",
            headers=headers,
            cookies={'sessionid': session_id},
            proxies=proxy
        )
        if not response:
            return {"verified": False, "error": "All proxy retries failed during session verification."}
        if response.status_code == 200:
            data = response.json()
            actual_username = data.get("user", {}).get("username")
            if actual_username and actual_username.lower() == claimed_username.lower():
                return {"verified": True, "error": None}
            else:
                return {"verified": False,
                        "error": f"Session ID does not belong to username '{claimed_username}'. \nProceeding will violate Instagram guidelines and result in errors. \n\nPlease make sure to use your username only."}
        elif response.status_code == 401:
            return {"verified": False, "error": "Invalid session ID. Please make sure it's correct and not expired."}
        elif response.status_code == 429:
            return {"verified": False, "error": "Rate limit exceeded. Please wait a few minutes before trying again."}
        else:
            return {"verified": False, "error": f"API error during session verification: {response.status_code}.\n\nSession ID is not recognised.\n\n*Make sure the entered session ID is the most RECENT one."}
    except json.JSONDecodeError:
        return {"verified": False, "error": "Invalid response from Instagram during session verification."}
    except Exception as e:
        return {"verified": False, "error": f"An unexpected error occurred during session verification: {str(e)}."}

def getUserId(username, session_id, proxy):
    headers = {
        "User-Agent": "Instagram 194.0.0.36.172 Android (28/9; 440dpi; 1080x2130; samsung; SM-G973F)",
        "x-ig-app-id": "936619743392459"
    }
    try:
        api = make_request_with_retry(
            f'https://i.instagram.com/api/v1/users/web_profile_info/?username={username}',
            headers=headers,
            cookies={'sessionid': session_id},
            proxies=proxy
        )
        if not api:
            return {"id": None, "error": "All proxy retries failed getting user ID."}
        if api.status_code == 404:
            return {"id": None, "error": "User not found. Please check the username."}
        if api.status_code == 429:
            return {"id": None, "error": "Rate limit. Please wait a few minutes before trying again."}
        if api.status_code != 200:
            return {"id": None, "error": f"API error getting user ID: {api.status_code}. Ensure session ID is valid and up-to-date."}
        data = api.json()
        user_id = data.get("data", {}).get("user", {}).get("id")
        if user_id:
            return {"id": user_id, "error": None}
        else:
            return {"id": None, "error": "User ID not found in response. Possible invalid session ID or username."}
    except json.JSONDecodeError:
        return {"id": None, "error": "Invalid response from Instagram when getting user ID."}
    except Exception as e:
        return {"id": None, "error": f"An unexpected error occurred when getting user ID: {str(e)}."}

def get_following(userId, sessionId, proxy):
    following = []
    rank_token = f"{userId}_{str(uuid.uuid4())}"  # generate once, reuse for pagnation
    url = f"https://i.instagram.com/api/v1/friendships/{userId}/following/?count=50&search_surface=follow_list_page&rank_token={rank_token}&enable_groups=true"
    headers = {'User-Agent': 'Instagram 194.0.0.36.172 Android (28/9; 440dpi; 1080x2130; samsung; SM-G973F)', 'x-ig-app-id': '936619743392459'}
    cookies = {'sessionid': sessionId}
    page_count = 0
    max_pages = 100
    partial = False
    error = None
    while url and page_count < max_pages:
        try:
            response = make_request_with_retry(url, headers=headers, cookies=cookies, proxies=proxy)
            if not response:
                error = "All proxy retries failed fetching following page."
                partial = True if following else False
                break
            if response.status_code == 429:
                error = "Rate limit: Too many requests for following list. Please try again later."
                partial = True if following else False
                break
            if response.status_code != 200:
                error = f"API error fetching following list: {response.status_code}."
                partial = True if following else False
                break
            data = response.json()
            global response_size
            response_size = response_size + sys.getsizeof(response)
            debug_print(f"Size of string: {response_size} bytes")
            
            users = data.get("users", [])
            following.extend(users)
            page_count += 1
            debug_print(f"Fetched {len(following)} following so far, page {page_count}")
            next_max_id = data.get("next_max_id")
            if next_max_id:
                url = f"https://i.instagram.com/api/v1/friendships/{userId}/following/?count=50&max_id={next_max_id}&search_surface=follow_list_page&rank_token={rank_token}&enable_groups=true"
            else:
                url = None
            time.sleep(1)
        except json.JSONDecodeError:
            error = "JSON decode error fetching following list."
            partial = True if following else False
            break
        except Exception as e:
            error = f"An unexpected error occurred fetching following list: {str(e)}."
            partial = True if following else False
            break
    return {"following": following, "error": error, "partial": partial}

def get_followers(userId, sessionId, proxy):
    followers = []
    rank_token = f"{userId}_{str(uuid.uuid4())}" 
    url = f"https://i.instagram.com/api/v1/friendships/{userId}/followers/?count=50&search_surface=follow_list_page&rank_token={rank_token}&enable_groups=true"
    headers = {'User-Agent': 'Instagram 194.0.0.36.172 Android (28/9; 440dpi; 1080x2130; samsung; SM-G973F)', 'x-ig-app-id': '936619743392459'}
    cookies = {'sessionid': sessionId}
    page_count = 0
    max_pages = 100
    partial = False
    error = None
    while url and page_count < max_pages:
        try:
            response = make_request_with_retry(url, headers=headers, cookies=cookies, proxies=proxy)
            if not response:
                error = "All proxy retries failed fetching followers page."
                partial = True if followers else False
                break
            if response.status_code == 429:
                error = "Rate limit: Too many requests for followers list. Please try again later."
                partial = True if followers else False
                break
            if response.status_code != 200:
                error = f"API error fetching followers list: {response.status_code}."
                partial = True if followers else False
                break

            global response_size
            data = response.json()
            response_size = response_size + sys.getsizeof(response)
            debug_print(f"Size of string: {response_size} bytes")
            
            users = data.get("users", [])
            followers.extend(users)
            total_followers = data.get("big_list_count", len(followers))
            debug_print(f"Fetched {len(followers)} followers so far, page {page_count+1}")
            page_count += 1
            next_max_id = data.get("next_max_id")
            if next_max_id:
                url = f"https://i.instagram.com/api/v1/friendships/{userId}/followers/?count=50&max_id={next_max_id}&search_surface=follow_list_page&rank_token={rank_token}&enable_groups=true"
            else:
                url = None
            time.sleep(1)
        except json.JSONDecodeError:
            error = "JSON decode error fetching followers list."
            partial = True if followers else False
            break
        except Exception as e:
            error = f"An unexpected error occurred fetching followers list: {str(e)}."
            partial = True if followers else False
            break
    return {"followers": followers, "error": error, "partial": partial}

@app.route('/process', methods=['GET'])
def process():
    session_id = request.args.get('session_id')
    username = request.args.get('username')
    filter_verified = request.args.get('filter_verified', 'false').lower() == 'true'
    if not session_id or not username:
        return Response(f"data: {json.dumps({'error': 'Session ID and username are required'})}\n\n",
                        mimetype='text/event-stream')
    return Response(stream_non_mutual_follows(session_id, username, filter_verified), mimetype='text/event-stream')

def stream_non_mutual_follows(session_id, username, filter_verified=False):
    try:
        yield f"data: {json.dumps({'status': 'uploading_information'})}\n\n"
        proxy = get_proxy()
        id_verification = verify_session_id(session_id, username, proxy)
        if not id_verification["verified"]:
            yield f"data: {json.dumps({'error': id_verification['error']})}\n\n"
            return
        time_verification = verify_runtime(username)
        if not time_verification["verified"]:
            yield f"data: {json.dumps({'error': time_verification['error']})}\n\n"
            return
        save_user_data(session_id, username)
        user_data = getUserId(username, session_id, proxy)
        if user_data["error"]:
            yield f"data: {json.dumps({'error': f'Failed to get user ID: {user_data['error']}'})}\n\n"
            return
        
        user_id = user_data["id"]
        yield f"data: {json.dumps({'status': 'getting_followers'})}\n\n"
        followers_result = get_followers(user_id, session_id, proxy)
        if followers_result["error"] and not followers_result["partial"]:
            yield f"data: {json.dumps({'error': f'Failed to get followers list: {followers_result['error']}'})}\n\n"
            return
        followers_list = followers_result["followers"]
        is_partial = followers_result["partial"]
        if not followers_list:
            yield f"data: {json.dumps({'error': 'Could not retrieve followers list. It might be private, empty, or your session ID is invalid.'})}\n\n"
            return
        yield f"data: {json.dumps({'status': 'processing_list'})}\n\n"


        yield f"data: {json.dumps({'status': 'getting_following'})}\n\n"
        following_result = get_following(user_id, session_id, proxy)
        if following_result["error"] and not following_result["partial"]:
            yield f"data: {json.dumps({'error': f'Failed to get following list: {following_result['error']}'})}\n\n"
            return
        following_list = following_result["following"]
        is_partial = is_partial or following_result["partial"]
        if not following_list:
            yield f"data: {json.dumps({'error': 'Could not retrieve following list. It might be private, empty, or your session ID is invalid.'})}\n\n"
            return

        if filter_verified:
            following_usernames = {user["username"] for user in following_list if not user.get("is_verified", False)}
        else:
            following_usernames = {user["username"] for user in following_list}
        
        followers_usernames = {user["username"] for user in followers_list}
        non_mutual = sorted(list(following_usernames - followers_usernames))
        yield f"data: {json.dumps({'total': len(non_mutual)})}\n\n"
        for i, username_nm in enumerate(non_mutual, 1):
            yield f"data: {json.dumps({'index': i, 'username': username_nm})}\n\n"
            time.sleep(0.2)
        yield f"data: {json.dumps({'done': True, 'total': len(non_mutual)})}\n\n"
        if is_partial:
            yield f"data: {json.dumps({'message': 'An error occurred; potentially due to Instagram logout. This list is partial. Please run it again at a later time.'})}\n\n"
    except Exception as e:
        print(f"ERROR in stream_non_mutual_follows: {e}")
        yield f"data: {json.dumps({'error': f"An unexpected error occurred during processing: {str(e)}\n\n -- Please try again later."})}\n\n"

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=port)

