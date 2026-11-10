import os
import re
import json
import requests
from playwright.sync_api import sync_playwright

# --- ⚙️ CONFIGURATION SETTINGS ⚙️ ---
TARGET_URL = "https://hasulivephoto.utoniq.com/gachas/wVmHBS26KrLVpN9Pdvul/items"

# 🚨 Threshold to trigger the rate alert (0.1072%)
UR_THRESHOLD_RATE = 0.001072    

# Read secrets from environment variables
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_USER_ID = os.getenv("DISCOR_USER_ID", "")

STATE_FILE = "state.json"


def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get("previous_ur_count")
        except Exception as e:
            print(f"Failed to read state file: {e}")
    return None


def save_current_state(ur_count):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"previous_ur_count": ur_count}, f)
    except Exception as e:
        print(f"Failed to save state file: {e}")


def send_discord_heartbeat(live_rate, ur_count, pool_count):
    """Sends the status line directly to Discord without any pings on every check."""
    rate_percentage = live_rate * 100
    message = f"UR Pool Index: {ur_count}/{pool_count} | Live Rate: {rate_percentage:.4f}%"
    
    payload = {
        "content": message
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code in (200, 204):
            print("Successfully sent routine status update to Discord.")
        else:
            print(f"⚠️ Discord Webhook rejected heartbeat request with status code: {response.status_code}")
    except Exception as e:
        print(f"Failed to post heartbeat webhook: {e}")


def send_discord_alert(live_rate, ur_count, pool_count, pulled_amount=0, reason="threshold"):
    """Sends a structured rich embed notification card with a user ping when an event occurs."""
    rate_percentage = live_rate * 100
    threshold_percentage = UR_THRESHOLD_RATE * 100
    
    if reason == "ur_pulled":
        title = "🎉 UR Item Pulled!"
        description = f"**{pulled_amount}** UR item(s) were pulled from the pool since the last check!"
        color = 16766720  # Gold Accent
        mention_text = f"<@{DISCORD_USER_ID}> 🎉 **UR Pulled Alert!**" if DISCORD_USER_ID else "🎉 **UR Pulled Alert!**"
    else:
        title = "🎰 HasuNoSora Gacha Pool Update!"
        description = "The calculated Ultra Rare drop rate has climbed above the baseline threshold due to trash item dilution."
        color = 15158332  # Crimson Red Accent
        mention_text = f"<@{DISCORD_USER_ID}> 🚨 **UR Pull Rate Threshold Exceeded!**" if DISCORD_USER_ID else "🚨 **UR Pull Rate Threshold Exceeded!**"
    
    payload = {
        "content": mention_text,
        "embeds": [
            {
                "title": title,
                "description": description,
                "url": TARGET_URL,
                "color": color,
                "fields": [
                    {
                        "name": "📈 Live UR Rate",
                        "value": f"`{rate_percentage:.4f}%`",
                        "inline": True
                    },
                    {
                        "name": "🎯 Target Threshold",
                        "value": f"`> {threshold_percentage:.4f}%`",
                        "inline": True
                    },
                    {
                        "name": "📊 Remaining Inventory",
                        "value": f"**UR Stock:** {ur_count} items left\n**Total Pool:** {pool_count} items left",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "HasuLivePhoto Automated Monitoring Service"
                }
            }
        ]
    }
    
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code in (200, 204):
            print(f"Successfully broadcasted {reason} alert payload card to Discord channel.")
        else:
            print(f"⚠️ Discord Webhook rejected request with status code: {response.status_code}")
    except Exception as e:
        print(f"Failed to post webhook event packet: {e}")


def fetch_and_calculate_rate():
    total_remaining_pool = 0
    total_remaining_ur = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Connecting to live metadata DOM tree...")
        try:
            page.goto(TARGET_URL, wait_until="networkidle")
            page.wait_for_selector("text=/\\d+\\/\\d+/", timeout=15000)
            page_text = page.locator("body").inner_text()
        except Exception as err:
            print(f"⚠️ Playwright extraction error: {err}")
            page_text = ""
        finally:
            browser.close()
        
    pattern = re.compile(r"([^\s]+)\s+([A-Z0-9]+)\s+(\d+)/(\d+)")
    matches = pattern.findall(page_text)
    
    if not matches:
        print("⚠️ Parsing structural layout anomaly detected. Verify target element strings.")
        return None

    for match in matches:
        _, item_code, remaining, _ = match
        remaining = int(remaining)
        
        total_remaining_pool += remaining
        if "UR" in item_code:
            total_remaining_ur += remaining

    if total_remaining_pool == 0:
        return None
        
    live_ur_rate = total_remaining_ur / total_remaining_pool
    return live_ur_rate, total_remaining_ur, total_remaining_pool


def main():
    print("🚀 Gacha Pool Check Triggered.")
    
    previous_ur_count = load_previous_state()
    result = fetch_and_calculate_rate()
    
    if result:
        live_rate, ur_count, pool_count = result
        print(f"UR Pool Index: {ur_count}/{pool_count} | Live Rate: {live_rate * 100:.4f}%")
        
        # 1. Send text status line every time it runs successfully
        send_discord_heartbeat(live_rate, ur_count, pool_count)
        
        # 2. Check if a UR item was pulled since last run
        if previous_ur_count is not None and ur_count < previous_ur_count:
            pulled_amount = previous_ur_count - ur_count
            print(f"🎉 Detected UR pull! {pulled_amount} item(s) drawn.")
            send_discord_alert(live_rate, ur_count, pool_count, pulled_amount=pulled_amount, reason="ur_pulled")
        
        # 3. Check if live rate exceeds threshold
        if live_rate > UR_THRESHOLD_RATE:
            send_discord_alert(live_rate, ur_count, pool_count, reason="threshold")
        
        # Save state for the next run
        save_current_state(ur_count)
    else:
        print("Execution finished without parsing result.")


if __name__ == "__main__":
    main()
