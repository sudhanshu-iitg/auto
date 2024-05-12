import os
from dotenv import load_dotenv
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
import schedule
import time

load_dotenv()

NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('DATABASE_ID')
SLACK_TOKEN = os.environ.get('SLACK_TOKEN')

client = WebClient(token=SLACK_TOKEN)
userId_dic = {}
channelId_dic = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

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
        logger.error(f"Error fetching data from Notion API: {response.text}")
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

def update_notion_reply(task, notion_page_id):
    url = f"https://api.notion.com/v1/comments"
    response = requests.post(
        url,
        json={"parent": {"page_id": notion_page_id },"rich_text": [
        {"text": {"content": task}}]},headers=headers
    )
    

def send_tasks_and_check_last_message():
    tasks_and_user_ids = get_tasks_and_user_ids()
    for task, user_id, notion_page_id in tasks_and_user_ids:
        channel_id = channelId_dic.get(user_id)
        conversation_id = userId_dic.get(task)
        try:
            result = client.conversations_replies(channel=channel_id, ts= conversation_id)
            conversation_history = result["messages"]
            last_message = conversation_history[-1]
            last_message_text = last_message.get("text", "")
            last_message_ts = last_message.get("ts", "")
            if conversation_id != last_message_ts:
                # send_task(last_message_text, user_id, notion_page_id)
                update_notion_reply(last_message_text,notion_page_id)
            logger.info("{} messages found in {}".format(len(conversation_history), channel_id))
        except SlackApiError as e:
            logger.error("Error creating conversation: {}".format(e))

schedule.every().day.at("10:00").do(send_tasks)
schedule.every().minute.do(send_tasks_and_check_last_message)

while True:
    schedule.run_pending()
    time.sleep(60)
