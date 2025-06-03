"""
Policy Generator for Grovio

This module analyzes past conversations between users and the Grovio bot,
identifies patterns and common topics, and generates suggested policy updates
based on those interactions. These suggestions can then be reviewed by admins
before being incorporated into the policy files.
"""

import json
import yaml
import time
from pathlib import Path
from datetime import datetime
import numpy as np
from openai import OpenAI
from utils import embed, cosine_sim

# Constants
CONFIG_PATH = "config.yaml"
STORE_PATH = "store.jsonl"
DISCORD_MESSAGES_PATH = "discord_messages.jsonl"
POLICIES_PATH = "context/policies.md"
SUGGESTED_POLICIES_PATH = "suggested_policies.jsonl"

def load_config():
    """Load configuration from YAML file."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {"mode": "passive", "model": "gpt-4o-mini"}

def load_conversations(limit=100):
    """
    Load recent conversations from both store.jsonl and discord_messages.jsonl.
    
    Args:
        limit (int): Maximum number of conversations to load
        
    Returns:
        list: List of conversation entries
    """
    conversations = []
    
    # Load from store.jsonl
    if Path(STORE_PATH).exists():
        try:
            with open(STORE_PATH, "r") as f:
                lines = f.readlines()
                for line in reversed(lines[:limit]):  # Process most recent first
                    try:
                        entry = json.loads(line)
                        conversations.append({
                            "ts": entry.get("ts", 0),
                            "user": entry.get("user", ""),
                            "reply": entry.get("reply", ""),
                            "source": "store"
                        })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error loading store data: {e}")
    
    # Load from discord_messages.jsonl
    if Path(DISCORD_MESSAGES_PATH).exists():
        try:
            with open(DISCORD_MESSAGES_PATH, "r") as f:
                lines = f.readlines()
                for line in reversed(lines[:limit]):  # Process most recent first
                    try:
                        entry = json.loads(line)
                        # Only include messages that have been responded to
                        if entry.get("responded", False):
                            conversations.append({
                                "ts": entry.get("ts", 0),
                                "user": entry.get("content", ""),
                                "author": entry.get("author", "Unknown"),
                                "reply": entry.get("reply", ""),
                                "source": "discord"
                            })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error loading discord messages: {e}")
    
    # Sort by timestamp, newest first
    conversations.sort(key=lambda x: x.get("ts", 0), reverse=True)
    
    # Limit to requested number
    return conversations[:limit]

def load_current_policies():
    """Load the current policies from the policies.md file."""
    try:
        if Path(POLICIES_PATH).exists():
            return Path(POLICIES_PATH).read_text()
        return ""
    except Exception as e:
        print(f"Error loading policies: {e}")
        return ""

def analyze_conversations(conversations, current_policies, client):
    """
    Analyze conversations to identify patterns and generate policy suggestions.
    
    Args:
        conversations (list): List of conversation entries
        current_policies (str): Current policies text
        client (OpenAI): OpenAI client
        
    Returns:
        dict: Policy suggestions with categories and confidence scores
    """
    if not conversations:
        return None
    
    # Prepare conversation data for analysis
    conversation_text = []
    for conv in conversations[:20]:  # Limit to recent 20 for analysis
        user_msg = conv.get("user", "")
        reply = conv.get("reply", "")
        if "author" in conv:
            conversation_text.append(f"User ({conv['author']}): {user_msg}\nBot: {reply}")
        else:
            conversation_text.append(f"User: {user_msg}\nBot: {reply}")
    
    conversation_history = "\n\n".join(conversation_text)
    
    # Use the LLM to analyze conversations and suggest policy updates
    prompt = f"""
    You are an AI policy analyst for Grovio, an AI-powered community growth platform.
    
    CURRENT POLICIES:
    {current_policies}
    
    RECENT CONVERSATIONS:
    {conversation_history}
    
    Based on the above conversations between users and the Grovio bot, identify:
    1. Common questions or topics that aren't well addressed by current policies
    2. Frequent misunderstandings that could be clarified with policy updates
    3. New use cases or features mentioned that should be reflected in policies
    4. Inconsistencies in responses that could be standardized
    
    For each identified issue, suggest specific policy updates that would address it.
    Format your response as JSON with the following structure:
    {{
        "suggestions": [
            {{
                "category": "Privacy Policy"|"Terms & Conditions"|"$GROV Token Policy"|"New Category",
                "issue": "Brief description of the issue identified",
                "suggestion": "The specific policy text you suggest adding",
                "confidence": 0.0-1.0,
                "reasoning": "Why you think this policy should be added"
            }}
        ]
    }}
    
    Only include high-quality suggestions with clear reasoning. If no significant policy gaps are identified, return an empty suggestions list.
    """
    
    try:
        response = client.chat.completions.create(
            model=load_config().get("model", "gpt-4o-mini"),
            messages=[{"role": "system", "content": prompt}],
            temperature=0.7,
            max_tokens=2000
        )
        
        response_text = response.choices[0].message.content
        
        # Extract JSON from response
        try:
            # Find JSON part (between { and })
            import re
            json_match = re.search(r'({.*})', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
            
            suggestions = json.loads(response_text)
            return suggestions
        except json.JSONDecodeError as e:
            print(f"Error parsing suggestion JSON: {e}")
            print(f"Raw response: {response_text}")
            return {"suggestions": []}
            
    except Exception as e:
        print(f"Error generating policy suggestions: {e}")
        return {"suggestions": []}

def save_policy_suggestions(suggestions):
    """
    Save generated policy suggestions to file for later review.
    
    Args:
        suggestions (dict): Policy suggestions to save
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create a record with timestamp
        record = {
            "ts": time.time(),
            "suggestions": suggestions.get("suggestions", []),
            "status": "pending"  # pending, approved, rejected
        }
        
        # Write to file
        with open(SUGGESTED_POLICIES_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
        
        return True
    except Exception as e:
        print(f"Error saving policy suggestions: {e}")
        return False

def load_pending_suggestions():
    """
    Load pending policy suggestions for admin review.
    
    Returns:
        list: List of pending policy suggestion records
    """
    pending = []
    
    if not Path(SUGGESTED_POLICIES_PATH).exists():
        return pending
    
    try:
        with open(SUGGESTED_POLICIES_PATH, "r") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("status") == "pending":
                        pending.append(record)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error loading policy suggestions: {e}")
    
    return pending

def update_suggestion_status(timestamp, status, approved_suggestions=None):
    """
    Update the status of a policy suggestion.
    
    Args:
        timestamp (float): Timestamp of the suggestion to update
        status (str): New status ('approved' or 'rejected')
        approved_suggestions (list): List of approved suggestions if status is 'approved'
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not Path(SUGGESTED_POLICIES_PATH).exists():
        return False
    
    try:
        # Read all records
        records = []
        with open(SUGGESTED_POLICIES_PATH, "r") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue
        
        # Update the matching record
        updated = False
        for record in records:
            if abs(record.get("ts", 0) - timestamp) < 0.001:  # Small float comparison tolerance
                record["status"] = status
                if status == "approved" and approved_suggestions:
                    record["approved_suggestions"] = approved_suggestions
                updated = True
                break
        
        if not updated:
            return False
        
        # Write back all records
        with open(SUGGESTED_POLICIES_PATH, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        
        return True
    except Exception as e:
        print(f"Error updating policy suggestion status: {e}")
        return False

def apply_approved_suggestions(approved_suggestions):
    """
    Apply approved policy suggestions to the policies.md file.
    
    Args:
        approved_suggestions (list): List of approved suggestions to apply
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not approved_suggestions:
        return False
    
    try:
        # Load current policies
        current_policies = load_current_policies()
        
        # Group suggestions by category
        categories = {}
        for suggestion in approved_suggestions:
            category = suggestion.get("category")
            if category not in categories:
                categories[category] = []
            categories[category].append(suggestion.get("suggestion", ""))
        
        # Apply updates by category
        for category, suggestions in categories.items():
            # Check if this is a new category
            category_header = f"## {category}"
            if category_header not in current_policies and "New Category" not in category:
                # Add new category at the end
                current_policies += f"\n\n## {category}\n\n"
                for suggestion in suggestions:
                    current_policies += f"- {suggestion}\n"
            else:
                # For existing categories, add suggestions at the end of the section
                import re
                
                # Clean category name for regex
                clean_category = category.replace("$", r"\$").replace("&", r"\&")
                
                # Find the section
                pattern = rf"## {clean_category}.*?(?=\n\n## |$)"
                match = re.search(pattern, current_policies, re.DOTALL)
                
                if match:
                    section = match.group(0)
                    updated_section = section
                    
                    # Add each suggestion as a new bullet point
                    for suggestion in suggestions:
                        updated_section += f"\n\n- {suggestion}"
                    
                    # Replace the old section with the updated one
                    current_policies = current_policies.replace(section, updated_section)
                else:
                    # If category specified in suggestion doesn't match exactly
                    # Add as a new category
                    current_policies += f"\n\n## {category}\n\n"
                    for suggestion in suggestions:
                        current_policies += f"- {suggestion}\n"
        
        # Write updated policies back to file
        with open(POLICIES_PATH, "w") as f:
            f.write(current_policies)
        
        return True
    except Exception as e:
        print(f"Error applying policy suggestions: {e}")
        return False

def generate_policy_suggestions():
    """
    Main function to generate policy suggestions based on conversation analysis.
    
    Returns:
        dict: Generated suggestions or None if error
    """
    try:
        # Load config and initialize OpenAI client
        cfg = load_config()
        client = OpenAI(api_key=cfg.get("openai_api_key"))
        
        # Load data
        conversations = load_conversations(limit=50)
        current_policies = load_current_policies()
        
        # Analyze conversations
        suggestions = analyze_conversations(conversations, current_policies, client)
        
        # Save suggestions for later review
        if suggestions and suggestions.get("suggestions"):
            save_policy_suggestions(suggestions)
            return suggestions
        
        return None
    except Exception as e:
        print(f"Error generating policy suggestions: {e}")
        return None

if __name__ == "__main__":
    # Test the policy generator
    suggestions = generate_policy_suggestions()
    if suggestions:
        print(f"Generated {len(suggestions.get('suggestions', []))} policy suggestions")
    else:
        print("No policy suggestions generated")
