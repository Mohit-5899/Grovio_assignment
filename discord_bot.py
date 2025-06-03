# discord_bot.py
import discord
import yaml
import json
import time
from pathlib import Path
from discord.ext import commands
import json
import time
import threading
import asyncio
from pathlib import Path
import yaml
import sys
import io

# Track last config file modification time
last_config_mtime = 0
cfg = {}

# Load configuration from yaml with file change detection
def reload_config():
    global cfg, last_config_mtime
    
    config_file = Path("config.yaml")
    if config_file.exists():
        # Check if the file has been modified
        current_mtime = config_file.stat().st_mtime
        if current_mtime > last_config_mtime:
            with open(config_file, "r") as f:
                new_cfg = yaml.safe_load(f)
                if new_cfg:
                    old_mode = cfg.get('mode', 'passive')
                    new_mode = new_cfg.get('mode', 'passive')
                    cfg = new_cfg
                    last_config_mtime = current_mtime
                    if old_mode != new_mode:
                        print(f"Mode changed from {old_mode} to {new_mode}")
                    return True  # Config was reloaded
        return False  # No change in config
    else:
        # Default configuration
        default_cfg = {
            "discord_token": "",
            "openai_api_key": "",
            "model": "gpt-3.5-turbo",
            "mode": "passive"
        }
        if cfg != default_cfg:
            cfg = default_cfg
            last_config_mtime = 0
            return True  # Config was reset to defaults
        return False  # Already using defaults

# Initial config load
reload_config()

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True  # Needed to read message content

bot = commands.Bot(command_prefix='!', intents=intents)

# Dictionary to keep track of message IDs and their channels
message_map = {}

# Path to persist message map and message queue
MESSAGE_MAP_FILE = "discord_message_map.json"
MESSAGE_QUEUE_FILE = "discord_message_queue.jsonl"

# Check queue every 5 seconds
QUEUE_CHECK_INTERVAL = 5

# Load message map from disk if it exists
def load_message_map():
    global message_map
    try:
        if Path(MESSAGE_MAP_FILE).exists():
            with open(MESSAGE_MAP_FILE, 'r') as f:
                message_map = json.load(f)
                print(f"Loaded message map with {len(message_map)} entries")
    except Exception as e:
        print(f"Error loading message map: {e}")
        message_map = {}

# Save message map to disk
def save_message_map():
    try:
        with open(MESSAGE_MAP_FILE, 'w') as f:
            json.dump(message_map, f)
    except Exception as e:
        print(f"Error saving message map: {e}")

# Load the message map at startup
load_message_map()

async def check_message_queue():
    await bot.wait_until_ready()
    print("Started message queue monitoring task")
    while not bot.is_closed():
        try:
            # Reload config to check for mode changes
            if reload_config():
                print("Config has been updated, new mode:", cfg.get('mode', 'passive'))
        except Exception as e:
            print(f"Error reloading config: {e}")
        
        # Check the message queue file for messages to respond to
        queue_file = Path(MESSAGE_QUEUE_FILE)
        messages_to_process = []
        
        if queue_file.exists() and queue_file.stat().st_size > 0:
            try:
                with open(queue_file, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        print(f"Found {len(lines)} message(s) in queue to process")
                        messages_to_process = [json.loads(line) for line in lines]
                
                # Clear the queue file immediately to avoid reprocessing
                with open(queue_file, 'w') as f:
                    f.write("")
                    
                # Process each queued response
                for entry in messages_to_process:
                    message_id = entry.get('message_id')
                    response = entry.get('response')
                    
                    if message_id and response:
                        print(f"Processing queued response for message {message_id}")
                        try:
                            # Use the async response function directly since we're already in an async context
                            await _respond_to_message(message_id, response)
                            print(f"Successfully sent queued response to {message_id}")
                        except Exception as e:
                            print(f"Error sending queued response: {e}")
                            import traceback
                            traceback.print_exc()
            except Exception as e:
                print(f"Error processing message queue: {e}")
                import traceback
                traceback.print_exc()
        
        # Wait before checking again
        await asyncio.sleep(QUEUE_CHECK_INTERVAL)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})')
    print('------')
    # Start the background task to check for queued messages
    bot.loop.create_task(check_message_queue())

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Process commands (if any were defined with @bot.command())
    await bot.process_commands(message)
    
    # Don't respond to commands
    if message.content.startswith(bot.command_prefix):
        return
        
    # Log the received message for debugging
    print(f"Received Discord message from {message.author}: {message.content}")
    
    try:
        # Create a thread to handle the message processing
        # This prevents blocking the Discord event loop
        thread = threading.Thread(target=store_discord_message, args=(message,))
        thread.daemon = True
        thread.start()
    except Exception as e:
        print(f"Error starting processing thread: {e}")
        import traceback
        traceback.print_exc()

# Process and store Discord messages for review
def store_discord_message(message):
    # Reload config to check for mode changes
    reload_config()
    # Create a unique ID for this message
    message_id = f"discord_{message.id}"
    
    # Store mapping of message_id -> channel/message for later response
    message_map[message_id] = {
        "channel_id": message.channel.id,
        "message_id": message.id
    }
    # Save the message map to disk for persistence
    save_message_map()
    
    # First process the message through the LLM pipeline
    try:
        import main
        import sys
        import io
        import yaml
        user_input = message.content
        
        # Capture the print output from main.handle (it prints the response)
        old_stdout = sys.stdout
        new_stdout = io.StringIO()
        sys.stdout = new_stdout
        
        # Process the message through main.py handle function
        main.handle(user_input)
        
        # Get the printed output and restore stdout
        output = new_stdout.getvalue()
        sys.stdout = old_stdout
        
        # Extract AI response from printed output (format is usually "AI: response")
        reply_text = ""
        if "AI:" in output:
            reply_text = output.split("AI:", 1)[1].strip()
        
        # Get additional metadata from store.jsonl
        store_file = Path("store.jsonl")
        risk = 0.0
        conf = 0.0
        active_mode = False
        
        if store_file.exists():
            with open(store_file, "r") as f:
                lines = f.readlines()
                if lines:
                    latest_entry = json.loads(lines[-1])
                    # Only use the reply from store.jsonl if we couldn't extract it from stdout
                    if not reply_text:
                        reply_text = latest_entry.get("reply", "")
                    risk = latest_entry.get("risk", 0.0)
                    conf = latest_entry.get("conf", 0.0)
                    active_mode = latest_entry.get("active", False)
        
        print(f"Generated response: {reply_text[:50]}...")
        print(f"Active mode: {active_mode}")
        
        # Store the message information in discord_messages.jsonl
        discord_msg_file = Path("discord_messages.jsonl")
        
        # Check if we're in active mode and should auto-respond
        responded = False
        
        # Get the confidence and risk thresholds from config
        min_confidence = cfg.get("min_confidence", 0.7)
        max_risk = cfg.get("max_risk", 0.2)
        
        # Check if we're in active mode AND the message meets our confidence/risk thresholds
        thresholds_met = (conf >= min_confidence and risk <= max_risk)
        
        if active_mode and reply_text:
            if thresholds_met:
                try:
                    # Create a queue entry to be processed by the background task
                    queue_entry = {
                        "message_id": message_id,
                        "response": reply_text,
                        "timestamp": time.time()
                    }
                    
                    # Write to the message queue file for the bot to pick up
                    with open(MESSAGE_QUEUE_FILE, "a") as f:
                        f.write(json.dumps(queue_entry) + "\n")
                    
                    print(f"Auto-responding to message {message_id} (active mode, thresholds met: conf={conf:.2f}, risk={risk:.2f})")
                    responded = True
                except Exception as e:
                    print(f"Error auto-responding to message: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # Active mode but thresholds not met - send to admin review
                print(f"Message sent to admin review despite active mode (thresholds not met: conf={conf:.2f}<{min_confidence} or risk={risk:.2f}>{max_risk})")
                # We don't set responded=True here because we want the admin to review it
        
        entry = {
            "ts": time.time(),
            "message_id": message_id,
            "author": str(message.author),
            "content": message.content,
            "reply": reply_text,
            "risk": risk,
            "conf": conf,
            "processed": True,
            "responded": responded
        }
        
        with open(discord_msg_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        print(f"Processed Discord message with LLM and stored for review: {message_id}")
        
    except Exception as e:
        print(f"Error processing message through LLM: {e}")
        import traceback
        traceback.print_exc()
        
        # Even if there's an error, store a minimal entry
        discord_msg_file = Path("discord_messages.jsonl")
        entry = {
            "ts": time.time(),
            "message_id": message_id,
            "author": str(message.author),
            "content": message.content,
            "reply": "",
            "risk": 0.0,
            "conf": 0.0,
            "processed": False,
            "responded": False
        }
        
        with open(discord_msg_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

# Command to respond to a specific message by ID
@bot.command(name="respond")
async def respond_to_message(ctx, message_id, *, response):
    if message_id in message_map:
        info = message_map[message_id]
        channel = bot.get_channel(info["channel_id"])
        if channel:
            original_message = await channel.fetch_message(info["message_id"])
            await original_message.reply(response)
            await ctx.send(f"Response sent to message {message_id}")
        else:
            await ctx.send(f"Channel not found for message {message_id}")
    else:
        await ctx.send(f"Message ID {message_id} not found in tracking map")

# Function to respond to a message from external code (like admin dashboard)
async def _respond_to_message(message_id, response):
    if message_id in message_map:
        info = message_map[message_id]
        channel = bot.get_channel(info["channel_id"])
        if channel:
            try:
                original_message = await channel.fetch_message(info["message_id"])
                await original_message.reply(response)
                print(f"Response sent to message {message_id}")
                
                # Update the message in discord_messages.jsonl to mark as responded
                discord_msg_file = Path("discord_messages.jsonl")
                if discord_msg_file.exists():
                    # Read all messages
                    with open(discord_msg_file, "r") as f:
                        messages = [json.loads(line) for line in f]
                    
                    # Update the responded status
                    updated = False
                    for msg in messages:
                        if msg.get("message_id") == message_id:
                            msg["responded"] = True
                            updated = True
                    
                    if updated:
                        # Write back all messages
                        with open(discord_msg_file, "w") as f:
                            for msg in messages:
                                f.write(json.dumps(msg) + "\n")
                return True
            except Exception as e:
                print(f"Error responding to Discord message: {e}")
                return False
        else:
            print(f"Channel not found for message {message_id}")
            return False
    else:
        print(f"Message ID {message_id} not found in tracking map")
        return False

# Non-async wrapper function for the admin dashboard to call
def respond_to_message(message_id, response):
    """Send a response to a Discord message.
    
    This function is called from the admin dashboard to respond to Discord messages.
    It updates the message status in the database and adds the message to a queue
    that will be processed by the Discord bot if it's running.
    
    Args:
        message_id (str): The Discord message ID to respond to
        response (str): The response text
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Update the message in discord_messages.jsonl to mark as responded
        discord_msg_file = Path("discord_messages.jsonl")
        if discord_msg_file.exists():
            # Read all messages
            with open(discord_msg_file, "r") as f:
                messages = [json.loads(line) for line in f]
            
            # Update the responded status
            updated = False
            for msg in messages:
                if msg.get("message_id") == message_id:
                    msg["responded"] = True
                    msg["reply"] = response  # Update the reply
                    updated = True
            
            if updated:
                # Write back all messages
                with open(discord_msg_file, "w") as f:
                    for msg in messages:
                        f.write(json.dumps(msg) + "\n")
                print(f"Marked message {message_id} as responded in database")
            else:
                print(f"Message {message_id} not found in database")
        
        # Add the response to the message queue for the Discord bot to process
        queue_entry = {
            "message_id": message_id,
            "response": response,
            "timestamp": time.time()
        }
        
        # Write to the message queue file for the bot to pick up
        with open(MESSAGE_QUEUE_FILE, "a") as f:
            f.write(json.dumps(queue_entry) + "\n")
        
        print(f"Added response to message queue for {message_id}")
        return True
    except Exception as e:
        print(f"Error in respond_to_message: {e}")
        import traceback
        traceback.print_exc()
        return False

# Run the bot
def run_discord_bot():
    while True:
        try:
            print("Starting Discord bot...")
            print(f"Bot will store messages for review in the admin dashboard")
            bot.run(cfg["discord_token"])
        except Exception as e:
            print(f"Error starting Discord bot: {e}")
            import traceback
            traceback.print_exc()
            print("Will attempt to reconnect in 30 seconds...")

            # Process any messages in the queue that were added while we were disconnected
            try:
                process_offline_queue()
            except Exception as queue_error:
                print(f"Error processing offline queue: {queue_error}")
                traceback.print_exc()

            # Wait before attempting to reconnect
            time.sleep(30)

# Process message queue when offline
def process_offline_queue():
    # Check the message queue file for messages to respond to
    queue_file = Path(MESSAGE_QUEUE_FILE)
    if queue_file.exists() and queue_file.stat().st_size > 0:
        print("Processing message queue while offline...")
        try:
            # Read the queue
            with open(queue_file, 'r') as f:
                lines = f.readlines()
                if lines:
                    print(f"Found {len(lines)} message(s) in queue")

            # Clear the queue immediately
            with open(queue_file, 'w') as f:
                f.write("")

            # Mark all messages in discord_messages.jsonl as responded
            discord_msg_file = Path("discord_messages.jsonl")
            if discord_msg_file.exists():
                # Read all messages
                with open(discord_msg_file, "r") as f:
                    messages = [json.loads(line) for line in f]

                # Update messages that match the queue IDs
                message_ids = [json.loads(line).get('message_id') for line in lines]
                updated = False
                for msg in messages:
                    if msg.get("message_id") in message_ids and not msg.get("responded", False):
                        msg["responded"] = True
                        updated = True
                        print(f"Marked message {msg['message_id']} as responded in database (offline mode)")

                if updated:
                    # Write back all messages
                    with open(discord_msg_file, "w") as f:
                        for msg in messages:
                            f.write(json.dumps(msg) + "\n")
        except Exception as e:
            print(f"Error processing offline queue: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    run_discord_bot()
