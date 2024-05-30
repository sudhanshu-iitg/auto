from flask import Flask, request, jsonify
import os
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
# from main import send_tasks
# from file1 import send_tasks_1

NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('DATABASE_ID')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')

client = WebClient(token=SLACK_TOKEN)
userId_dic = {}
channelId_dic = {}
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
                task["properties"]["Slack User IDs"]["rich_text"][0]["plain_text"],
                task["id"]
            )
            for task in data["results"]
        ]
        return tasks_and_user_ids
    else:
        # logger.error(f"Error fetching data from Notion API: {response.text}")
        return []
    
def send_task(task, user_id, notion_page_id):
    result = client.chat_postMessage(channel=user_id, text=task)
    userId_dic[task] = result["message"]["ts"]
    channelId_dic[user_id] = result["channel"]
        
        # url = f"https://api.notion.com/v1/pages/{notion_page_id}"
        # response = requests.patch(
        #     url,
        #     json={"properties": {"Reply": {"type": "rich_text", "rich_text": [{"text": {"content": task}}]}}},
        #     headers=headers
        # )


def send_tasks():
    tasks_and_user_ids = get_tasks_and_user_ids()
    for task, user_id, notion_page_id in tasks_and_user_ids:
        send_task(task, user_id, notion_page_id)


app = Flask(__name__)

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
            
            return jsonify({"message": "Webhook received!", "data": data}), 200

@app.route('/slack', methods=['POST'])
def slack():
    if request.method == 'POST':
        data1 = request.json
        # Process the data here
        if data1.get("challenge") is not None:
            # send_tasks_1()
            challenge = data1.get("challenge")
            return challenge, 200
        else:
            # Handle other webhook events here
            # send_task(str(data),"D072S7M51QE","abc")
            response = requests.post("https://lynks-n8n.up.railway.app/webhook/auto-task", data={"body":str(data1['event']['text']) })
            return jsonify({"message": "Webhook received !", "data": data1}), 200
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)