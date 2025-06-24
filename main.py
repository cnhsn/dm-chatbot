import redis
import httpx
from fastapi import FastAPI, Request, Response

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_API_BASE,
    OPENROUTER_MODEL,
    INSTAGRAM_ACCESS_TOKEN,
    WEBHOOK_VERIFY_TOKEN,
)

app = FastAPI()

# Redis connection
r = redis.Redis(decode_responses=True)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/webhook")
def webhook_verification(request: Request):
    """Webhook verification endpoint."""
    if request.query_params.get("hub.mode") == "subscribe" and request.query_params.get("hub.challenge"):
        if not request.query_params.get("hub.verify_token") == WEBHOOK_VERIFY_TOKEN:
            return Response(content="Verification token mismatch", status_code=403)
        return Response(content=request.query_params["hub.challenge"])
    return Response(content="Failed to verify webhook", status_code=400)

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook endpoint to handle incoming messages."""
    data = await request.json()
    if data["object"] == "instagram":
        for entry in data["entry"]:
            for messaging_event in entry["messaging"]:
                if messaging_event.get("message"):
                    sender_id = messaging_event["sender"]["id"]
                    message_text = messaging_event["message"]["text"]
                    handle_message(sender_id, message_text)
    return Response(content="ok", status_code=200)

def handle_message(sender_id, message_text):
    """Handle incoming message, get response from OpenRouter and send it back."""
    # Get conversation history from Redis
    history = r.lrange(sender_id, 0, -1)
    history.append(f"User: {message_text}")

    # Get response from OpenRouter
    try:
        response = httpx.post(
            f"{OPENROUTER_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": "\n".join(history)}]
            }
        )
        response.raise_for_status()
        bot_response = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        print(f"Error calling OpenRouter API: {e}")
        bot_response = "Sorry, I'm having trouble connecting to the AI. Please try again later."

    # Send message to user
    send_message(sender_id, bot_response)

    # Save conversation history to Redis with 24-hour expiration
    r.lpush(sender_id, f"User: {message_text}", f"Bot: {bot_response}")
    r.expire(sender_id, 86400)

def send_message(recipient_id, message_text):
    """Send message to user using Instagram Graph API."""
    params = {"access_token": INSTAGRAM_ACCESS_TOKEN}
    headers = {"Content-Type": "application/json"}
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    try:
        response = httpx.post("https://graph.facebook.com/v13.0/me/messages", params=params, headers=headers, json=data)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"Error sending message to Instagram: {e}")