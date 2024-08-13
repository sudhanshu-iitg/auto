from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS
import os
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from supabase import create_client, Client 
from libgen_api import LibgenSearch
from bs4 import BeautifulSoup
from requests.exceptions import ChunkedEncodingError, ConnectionError
import time
# from main import send_tasks
# from file1 import send_tasks_1

NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('DATABASE_ID')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')
SLACK_USER_TOKEN = os.environ.get('SLACK_USER_TOKEN')
url: str = os.environ.get('SUPABASE_URL')
key: str = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(url, key)

client = WebClient(token=SLACK_TOKEN)
userId_dic = {}
channelId_dic = {}
notionId_dic={}
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def get_tasks_and_user_ids():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    response = requests.post(url, json={"page_size": 100}, headers=headers)
    if response.status_code == 200:
        data = response.json()
        tasks_and_user_ids = [
            (
                task["properties"]["Task"]["title"][0]["text"]["content"],
                task["properties"]['Task owner']['people'][0]['name'],
                task["id"],
                task["properties"]['Status']['select']['name']
            )
            for task in data["results"]
        ]
        return tasks_and_user_ids
    else:
        # logger.error(f"Error fetching data from Notion API: {response.text}")
        return []
    
def send_task(task, user_id, notion_page_id,user_name):
    result = client.chat_postMessage(channel=user_id, text=f"Good evening, {user_name}! Could you please provide an update on the progress of {task} today? Thank you!")
    userId_dic[task] = result["message"]["ts"]
    channelId_dic[user_id] = result["channel"]
    notionId_dic[result["message"]["ts"]] = notion_page_id

def get_id_from_name(user_name):
    url = f"https://slack.com/api/users.list"
    response = requests.get(
        url,
        headers={"Authorization":f"Bearer {SLACK_USER_TOKEN}"}
    )
    if response.json()['members'] is not None:
        member_list = []
        for member in response.json()['members']:
            member_list.append(member['name'])
            if user_name.lower().strip() in member['name'].lower().strip() :
                return member['id']
        send_task(f"Couldn't find the user -  {member_list}", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
    else:
        return "U03GP4QD0MU"


def send_tasks():
    try:
        tasks_and_user_ids = get_tasks_and_user_ids()
        for task, user_name, notion_page_id, status in tasks_and_user_ids:
            if status == 'in progress':
                user_id = get_id_from_name(user_name)
                if user_name is None:
                    send_task("really fucked up", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
                else:
                    if user_id is None:
                        send_task(f"Couldn't find the user -  {user_name}", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d",'sid')
                    else:
                        send_task(task, user_id, notion_page_id,user_name)     
    except Exception as e:
        print(f"An error occurred: {e}")

def update_notion_reply(reply, notion_page_id):
    url = f"https://api.notion.com/v1/comments"
    response = requests.post(
        url,
        json={"parent": {"page_id": notion_page_id },"rich_text": [
        {"text": {"content": reply}}]},headers=headers
    )

def download_pdf(url, save_path, max_retries=3):
    # Attempt to download with retries
    for attempt in range(max_retries):
        try:
            # Send GET request with stream=True to download in chunks
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Open the file in write-binary mode
            with open(save_path, 'wb') as file:
                # Write the content in chunks to avoid large memory usage
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        file.write(chunk)
            print(f"PDF downloaded successfully and saved to {save_path}")
            break  # Exit the loop if the download was successful
        except (ChunkedEncodingError, ConnectionError) as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
            if attempt + 1 == max_retries:
                print("Max retries reached. Failed to download PDF.")
            else:
                print("Retrying...")   

app = Flask(__name__)
CORS(app, resources={r"/search*": {"origins": ["http://localhost:3000", "https://the-book-app2.onrender.com"]}})
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        # Process the data here
        if data.get("challenge") is not None:
            challenge = data.get("challenge")
            return challenge, 200
        else:
            # Handle other webhook events here
            print(f"Received webhook data: {data}")
            send_tasks()
            return jsonify({"message": "Webhook received!", "data": data}), 200

@app.route('/slack', methods=['POST'])
def slack():
    if request.method == 'POST':
        data1 = request.json
        # send_task(f"Received webhook data: {data1} ", "U03GP4QD0MU", "19e80f31c3fb499ea1b01e96203fb72d")
        # Process the data here
        if data1.get("challenge") is not None:
            # send_tasks_1()
            challenge = data1.get("challenge")
            return challenge, 200
        else:
            # Handle other webhook events here
            data, count = supabase.table('Request logs').insert({ "Request": data1["event"]}).execute()
            if "thread_ts" in data1["event"]:
                id = notionId_dic.get(data1["event"]["thread_ts"], 'test')
                update_notion_reply(data1["event"]["text"],id)
            # response = requests.post("https://smee.io/xK7FU4adUFN3EO8", data={"body":str(data1),"id":id })
            
            return jsonify({"message": "Webhook received !", "data": data1}), 200

@app.route('/search', methods=['GET'])
def search():
    if request.method == 'GET':
        key = request.args.get("key")
        if key is not None:
            # send_tasks_1()
            s = LibgenSearch()
            results = s.search_title(key)
            count = 0
            new_results = []
            for result in results:
                if result['Extension'] == 'epub':
                    result["download_links"] = result['Mirror_2']
                    new_results.append(result)
                    count += 1
                    if count >= 10:
                        break
            return jsonify({"message": "returned successfully!", "docs": new_results}), 200
            # return challenge, 200
        else:
            return jsonify({"message": "Missing 'key' parameter"}), 400 
@app.route('/store', methods=['GET'])
def store():
    if request.method == 'GET':
        key = request.args.get("key")
        if key is not None:
            retries=5
            for attempt in range(retries):
                try:
                    
                        MIRROR_SOURCES = ["GET"]
                        headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
                        page = requests.get(key, headers=headers)
                        
                        if page.status_code != 200:
                            raise Exception(f"Failed to fetch the page. Status code: {page} {key}")
                        

                        soup = BeautifulSoup(page.text, "html.parser")
                        links = soup.find_all("a", string=MIRROR_SOURCES)
                        
                        if not links:
                            raise Exception("No links found with the specified string.")

                        download_links = {link.string: link["href"] for link in links}
                        
                        if 'GET' in download_links:
                            final_links = 'http://libgen.li/' + download_links['GET']
                            print(final_links)
                            download_pdf(final_links, "book2.epub")
                        else: 
                            print("download links are not available")
                            print(soup)

                        return jsonify({"message": "returned successfully!"}), 200

                    

                except Exception as e:
                    print(f"Attempt {attempt + 1} failed: {e}")
                    if attempt < retries - 1:
                        print("Retrying...")
                        time.sleep(2)  # Optional: Wait before retrying
                    else:
                        return jsonify({"All retries failed. Exiting."}), 400 
                        
                    # return challenge, 200
    else:
        return jsonify({"Wrong method detected. Exiting."}), 400
                

# @app.route('/summarize', methods=['GET'])
# def summarize():
#     if request.method == 'GET':
#         key = request.args.get("key")
#         if key is not None:
#             # send_tasks_1()
#             MIRROR_SOURCES = ["GET"]
#             page = requests.get(key)
#             soup = BeautifulSoup(page.text, "html.parser")
# # print(soup)
#             links = soup.find_all("a", string=MIRROR_SOURCES)
#             download_links = {link.string: link["href"] for link in links}
#             links = soup.find_all("a", string=MIRROR_SOURCES)
#             download_links = {link.string: link["href"] for link in links}
#             final_links = 'http://libgen.li'+ download_links['GET']
#             return jsonify({"message": "returned successfully!", "docs": new_results}), 200
#             # return challenge, 200
#         else:
#             return jsonify({"message": "Missing 'key' parameter"}), 400 

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# Schedule the send_tasks function to run at 11:10 every day
# schedule.every().day.at("23:30").do(send_tasks)

# # Run the scheduled tasks
# while True:
#     schedule.run_pending()
#     time.sleep(6000)

