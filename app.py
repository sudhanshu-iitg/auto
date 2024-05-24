from flask import Flask, request, jsonify

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)