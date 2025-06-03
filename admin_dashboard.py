import streamlit as st
import yaml
import json
import time
from pathlib import Path
from datetime import datetime, timezone

# Import policy generator module
try:
    import policy_generator
except ImportError:
    print("Policy generator module not found")

CONFIG_PATH = "config.yaml"
LOG_PATH = "store.jsonl"

# ---------- Helpers ---------------------------------------------------------

# Track last modification time of config file
last_config_mtime = 0
config_cache = None

def load_config() -> dict:
    """Read YAML config (create defaults if file is missing), with file change detection."""
    global last_config_mtime, config_cache
    
    defaults = {
        "mode": "passive",          # passive | active
        "min_confidence": 0.85,
        "max_risk": 0.20,
    }
    
    config_file = Path("config.yaml")
    
    if config_file.exists():
        current_mtime = config_file.stat().st_mtime
        
        # If we have a cached config and the file hasn't changed, return the cache
        if config_cache and current_mtime <= last_config_mtime:
            return config_cache
            
        # Otherwise load the config from file
        try:
            with open(config_file, "r") as f:
                config = yaml.safe_load(f)
            if config is None:
                config = defaults
            
            # Update cache and modification time
            config_cache = {**defaults, **config}
            last_config_mtime = current_mtime
            return config_cache
        except Exception as e:
            st.error(f"Error loading config: {e}")
            return defaults
    else:
        # Create default config if not exists
        config = defaults
        with open("config.yaml", "w") as f:
            yaml.dump(config, f)
        
        # Update cache and modification time
        config_cache = config
        last_config_mtime = config_file.stat().st_mtime
        return config


def save_config(cfg: dict) -> None:
    """Persist YAML config."""
    Path(CONFIG_PATH).write_text(yaml.dump(cfg))


def reset_data() -> None:
    """Clear all stored messages and logs."""
    # Clear main log file
    if Path(LOG_PATH).exists():
        Path(LOG_PATH).write_text("")
    
    # Clear Discord messages
    discord_path = "discord_messages.jsonl"
    if Path(discord_path).exists():
        Path(discord_path).write_text("")
        
    return True


def load_logs() -> list[dict]:
    """Return list of logged exchanges sorted newest‒first.
    Shows only Discord messages for editing, filtering out duplicates."""
    
    combined_entries = []
    
    # Load Discord messages if they exist
    discord_path = "discord_messages.jsonl"
    if Path(discord_path).exists():
        with open(discord_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    msg = json.loads(line)
                    # Skip messages that have already been responded to
                    if msg.get("responded", False):
                        continue
                        
                    # Convert Discord message to format compatible with regular logs
                    combined_entries.append({
                        "ts": msg.get("ts", 0),
                        "user": f"[Discord] {msg.get('author', 'Unknown')}",
                        "content": msg.get("content", ""),
                        "reply": msg.get("reply", ""),
                        "risk": msg.get("risk", 0.0),
                        "conf": msg.get("conf", 0.0),
                        "is_discord": True,
                        "message_id": msg.get("message_id", ""),
                        "responded": msg.get("responded", False)
                    })
                except Exception as e:
                    print(f"Error parsing Discord message: {e}")
    
    # Only display Discord messages in the admin dashboard
    # This avoids the duplicate display issue entirely
    
    return sorted(combined_entries, key=lambda x: x.get("ts", 0), reverse=True)


def format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ---------- UI --------------------------------------------------------------

st.set_page_config(page_title="AI‑Agent Admin", layout="wide")

cfg = load_config()

# Sidebar – global settings
st.sidebar.header("Agent Settings")
mode = st.sidebar.selectbox("Mode", ["passive", "active"], index=["passive", "active"].index(cfg.get("mode", "passive")))

# Add a divider and Reset Data section
st.sidebar.markdown("---")
st.sidebar.header("Data Management")

# Add reset data button with confirmation
reset_confirmed = False
if st.sidebar.button("🗑️ Reset All Data"):
    reset_confirmed = st.sidebar.checkbox("⚠️ I confirm I want to delete all messages and logs")
    
    if reset_confirmed:
        if reset_data():
            st.sidebar.success("✅ All data has been cleared!")
            # Force page refresh to update UI
            st.rerun()
        else:
            st.sidebar.error("❌ Failed to reset data")
    else:
        st.sidebar.warning("⚠️ Please confirm deletion by checking the box above")
min_conf = st.sidebar.slider("Minimum confidence threshold", 0.0, 1.0, float(cfg["min_confidence"]), 0.01)
max_risk = st.sidebar.slider("Maximum risk threshold", 0.0, 1.0, float(cfg["max_risk"]), 0.01)

if st.sidebar.button("💾 Save settings"):
    cfg.update({"mode": mode, "min_confidence": min_conf, "max_risk": max_risk})
    save_config(cfg)
    st.sidebar.success("Settings saved!  ✓")

# Create tabs for different sections
tab1, tab2, tab3 = st.tabs(["📨 Messages", "⚙️ Settings", "📋 Policy Suggestions"])

# Messages Tab
with tab1:
    st.title("📨 Draft Queue & Activity Log")

# Load & split logs
actions = load_logs()
drafts = [a for a in actions if not a.get("active", False)]
sent   = [a for a in actions if a.get("active", False)]

col1, col2 = st.columns(2)

# Draft review panel ---------------------------------------------------------
with col1:
    st.subheader(f"Pending Drafts ({len(drafts)})") 
    if not drafts:
        st.info("No drafts waiting for review.")
    for idx, item in enumerate(drafts):
        # Handle different types of drafts (regular AI responses vs Discord messages)
        is_discord = item.get('is_discord', False)
        
        if is_discord:
            # Discord message that needs a response
            with st.expander(f"Discord Message #{idx+1} · {format_ts(item['ts'])}"):
                # Extract message content from user field if needed
                user_text = item['user']
                content = item.get('content', '')
                
                # If content is empty but user field has Discord format, extract content from there
                if not content and '[Discord]' in user_text:
                    try:
                        # Format is typically "[Discord] Username: Content"
                        content = user_text.split(':', 1)[1].strip()
                        author = user_text.split(':', 1)[0].strip()
                        st.markdown(f"**From Discord:** {author}")
                        st.markdown(f"**Message:** {content}")
                    except:
                        # If splitting fails, just show the user field
                        st.markdown(f"**From Discord:** {user_text}")
                else:
                    # Normal case with separate content field
                    st.markdown(f"**From Discord:** {user_text}")
                    if content:
                        st.markdown(f"**Message:** {content}")
                
                # Display LLM-generated reply (if available) and allow editing
                ai_reply = item.get('reply', '')
                
                # Determine if this message didn't meet thresholds despite active mode
                cfg = load_config()
                min_confidence = cfg.get("min_confidence", 0.85)
                max_risk = cfg.get("max_risk", 0.20)
                confidence = item.get("conf", 0.0)
                risk = item.get("risk", 0.0)
                
                # Highlight messages that didn't meet thresholds in active mode
                active_mode = cfg.get("mode", "passive") == "active"
                thresholds_met = (confidence >= min_confidence and risk <= max_risk)
                
                if active_mode and not thresholds_met:
                    st.warning(f"⚠️ This message requires review despite active mode because it didn't meet thresholds:\n" +
                               f"Confidence: {confidence:.2f} (minimum: {min_confidence})\n" +
                               f"Risk: {risk:.2f} (maximum: {max_risk})")
                    
                discord_reply = st.text_area("AI Response (Edit if needed):", value=ai_reply, key=f"discord_reply_{idx}")
        
                # Display risk and confidence scores if available
                if 'risk' in item and 'conf' in item:
                    risk_color = "red" if item['risk'] > 0.2 else "orange" if item['risk'] > 0.1 else "green"
                    conf_color = "red" if item['conf'] < 0.7 else "orange" if item['conf'] < 0.85 else "green"
                    st.markdown(f"**Risk:** <span style='color:{risk_color}'>{item['risk']:.2f}</span> | **Confidence:** <span style='color:{conf_color}'>{item['conf']:.2f}</span>", unsafe_allow_html=True)
                
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✅ Send to Discord", key=f"send_discord_{idx}"):
                        if discord_reply.strip():
                            # Get the message ID for this Discord message
                            message_id = item.get('message_id', '')
                            if message_id:
                                # Call the discord_bot's respond_to_message function directly
                                try:
                                    import discord_bot
                                    success = discord_bot.respond_to_message(message_id, discord_reply)
                                    if success:
                                        st.success(f"Reply saved and will be sent to Discord when bot is running!")
                                        # Mark as responded
                                        drafts.remove(item)
                                        st.rerun()
                                    else:
                                        st.warning("Reply saved to database, but Discord bot is not running to send it immediately.")
                                        # Still mark as responded in the drafts so it disappears from queue
                                        drafts.remove(item)
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"Error sending to Discord: {e}")
                            else:
                                st.error("No message ID found for this Discord message")
                        else:
                            st.error("Please enter a reply first")
                with col_b:
                    if st.button("🗑️ Delete", key=f"del_discord_{idx}"):
                        drafts.remove(item)
                        st.rerun()
        else:
            # Regular AI-generated draft
            with st.expander(f"Draft #{idx+1} · {format_ts(item['ts'])}"):
                st.markdown(f"**User:** {item['user']}")
                st.markdown(f"**Proposed reply:** {item['reply']}")
                st.caption(f"Confidence: {item['conf']:.2f} | Risk: {item['risk']:.2f}")
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✅ Send", key=f"send_{idx}"):
                        # Placeholder – integrate with your send‑to‑channel fn
                        st.success("Sent (simulated).")
                with col_b:
                    if st.button("🗑️ Delete", key=f"del_{idx}"):
                        drafts.remove(item)
                        st.rerun()

# Activity log panel ---------------------------------------------------------
with col2:
    st.subheader("Recent Activity (last 100)")
    if actions:
        log_view = [{
            "Time": format_ts(a["ts"]),
            "User": a["user"][:60],
            "Reply": a["reply"][:60] + ("…" if len(a["reply"])>60 else ""),
            "Mode": "sent" if a.get("active") else "draft",
            "Conf": round(a["conf"],2),
            "Risk": round(a["risk"],2),
        } for a in actions[:100]]
        st.dataframe(log_view, use_container_width=True, hide_index=True)
    else:
        st.info("No logs yet – send a message to generate data.")

st.markdown("---")
st.caption("Streamlit admin MVP – adjust thresholds, review drafts, monitor activity. Integrate real send actions by wiring the ✅ button to your channel adapter.")

# Settings Tab
with tab2:
    st.title("⚙️ Settings")
    
    # Settings form
    with st.form("settings_form"):
        st.header("Bot Configuration")
        
        # Load current settings
        current_cfg = load_config()
        
        # Model settings
        model = st.selectbox(
            "LLM Model",
            ["gpt-3.5-turbo", "gpt-4o-mini", "gpt-4o", "claude-3-opus-20240229"],
            index=["gpt-3.5-turbo", "gpt-4o-mini", "gpt-4o", "claude-3-opus-20240229"].index(
                current_cfg.get("model", "gpt-4o-mini")
            )
        )
        
        # Context settings
        col1, col2 = st.columns(2)
        with col1:
            top_k = st.number_input(
                "Top k context chunks", 
                min_value=1, 
                max_value=10, 
                value=current_cfg.get("top_k_context", 4)
            )
            
        with col2:
            semantic_weight = st.slider(
                "Semantic weight", 
                min_value=0.0, 
                max_value=1.0, 
                value=current_cfg.get("semantic_weight", 0.7),
                step=0.1,
                help="Weight for semantic search vs keyword search (BM25). Higher value gives more importance to semantic meaning."
            )
        
        # Debugging options
        debug_retrieval = st.checkbox(
            "Debug retrieval", 
            value=current_cfg.get("debug_retrieval", False),
            help="Show detailed logs about context retrieval"
        )
        
        # Submit button
        submitted = st.form_submit_button("Save Settings")
        
        if submitted:
            # Update config with new values
            current_cfg.update({
                "model": model,
                "top_k_context": top_k,
                "semantic_weight": semantic_weight,
                "debug_retrieval": debug_retrieval,
            })
            
            # Save updated config
            save_config(current_cfg)
            st.success("Settings saved successfully!")

# Policy Suggestions Tab
with tab3:
    st.title("📋 Policy Suggestions")
    
    # Load pending policy suggestions
    if 'policy_generator' in globals() or 'policy_generator' in locals():
        try:
            pending_suggestions = policy_generator.load_pending_suggestions()
            
            if pending_suggestions:
                st.success(f"Found {len(pending_suggestions)} pending policy suggestion(s)")
                
                for idx, suggestion_record in enumerate(pending_suggestions):
                    with st.expander(f"Suggestion Set #{idx+1} - {datetime.fromtimestamp(suggestion_record['ts']).strftime('%Y-%m-%d %H:%M')}"):
                        suggestions = suggestion_record.get("suggestions", [])
                        
                        if not suggestions:
                            st.warning("This suggestion set is empty.")
                            continue
                        
                        # Create a form for each suggestion set
                        with st.form(f"suggestion_form_{idx}"):
                            approved_suggestions = []
                            
                            for i, item in enumerate(suggestions):
                                st.subheader(f"Suggestion {i+1}: {item.get('category', 'Uncategorized')}")
                                st.markdown(f"**Issue:** {item.get('issue', 'No issue specified')}")
                                st.markdown(f"**Suggestion:** {item.get('suggestion', 'No suggestion text')}")
                                st.markdown(f"**Reasoning:** {item.get('reasoning', 'No reasoning provided')}")
                                st.markdown(f"**Confidence:** {item.get('confidence', 0.0):.2f}")
                                
                                # Checkbox to approve each individual suggestion
                                approve = st.checkbox(f"Approve this suggestion", key=f"approve_{idx}_{i}")
                                
                                if approve:
                                    approved_suggestions.append(item)
                                
                                st.markdown("---")
                            
                            # Action buttons
                            col1, col2 = st.columns(2)
                            with col1:
                                approve_btn = st.form_submit_button("Apply Selected Suggestions")
                            with col2:
                                reject_btn = st.form_submit_button("Reject All Suggestions")
                            
                            if approve_btn and approved_suggestions:
                                # Apply approved suggestions
                                if policy_generator.apply_approved_suggestions(approved_suggestions):
                                    # Update suggestion status
                                    policy_generator.update_suggestion_status(
                                        suggestion_record.get("ts", 0),
                                        "approved",
                                        approved_suggestions
                                    )
                                    st.success("✅ Policy updates applied successfully!")
                                    time.sleep(1)  # Give time for the success message to be seen
                                    st.rerun()  # Refresh to update the UI
                                else:
                                    st.error("❌ Failed to apply policy updates.")
                            
                            elif reject_btn:
                                # Update suggestion status to rejected
                                if policy_generator.update_suggestion_status(
                                    suggestion_record.get("ts", 0),
                                    "rejected"
                                ):
                                    st.success("Suggestions rejected.")
                                    time.sleep(1)  # Give time for the success message to be seen
                                    st.rerun()  # Refresh to update the UI
                                else:
                                    st.error("Failed to update suggestion status.")
            else:
                st.info("No pending policy suggestions available. Generate new suggestions using the button below.")
                
                # Show a button to generate suggestions
                if st.button("Generate New Policy Suggestions"):
                    with st.spinner("Analyzing conversations and generating suggestions..."):
                        suggestions = policy_generator.generate_policy_suggestions()
                        if suggestions and suggestions.get("suggestions"):
                            st.success(f"✅ Generated {len(suggestions.get('suggestions', []))} policy suggestions!")
                            st.rerun()  # Refresh to show the new suggestions
                        else:
                            st.info("No significant policy suggestions found from recent conversations.")
        except Exception as e:
            st.error(f"Error loading policy suggestions: {e}")
            import traceback
            st.error(traceback.format_exc())
    else:
        st.error("Policy generator module not available.")
        st.info("Make sure the policy_generator.py file is in the same directory as this script.")

if __name__ == "__main__":
    # Run the Streamlit app
    # This is only necessary for debugging, as streamlit run handles this normally
    pass
