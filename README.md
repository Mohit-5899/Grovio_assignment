# Grovio Discord Bot and Admin Dashboard

A Discord bot and admin dashboard integration for Grovio, an AI-powered autonomous growth engine for Web3 and gaming communities.

## Features

- Discord message integration with AI-generated replies
- Streamlit admin dashboard for message review and management
- Two operating modes:
  - **Passive Mode**: Draft replies for admin review
  - **Active Mode**: Auto-send replies without human intervention
- Dynamic configuration reloading (no restarts needed)
- Persistent message tracking
- Offline queue processing
- Reliable IPC between dashboard and bot

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a config.yaml file (use config.sample.yaml as a template)
4. Run the Discord bot:
   ```
   python discord_bot.py
   ```
5. Run the admin dashboard:
   ```
   streamlit run admin_dashboard.py
   ```

## Configuration

Create a `config.yaml` file based on the sample:

```yaml
channel: discord
debug_retrieval: false
discord_token: YOUR_DISCORD_TOKEN_HERE
max_risk: 0.1
min_confidence: 0.85
mode: passive
model: gpt-4o-mini
openai_api_key: YOUR_OPENAI_API_KEY_HERE
semantic_weight: 0.7
top_k_context: 4
```

## Usage

- The Discord bot will capture messages and process them through the LLM
- In passive mode, responses are stored for review in the admin dashboard
- In active mode, responses are automatically sent to Discord
- You can switch modes in the admin dashboard or by editing config.yaml (no restart required)
