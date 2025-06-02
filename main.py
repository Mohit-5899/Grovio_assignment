# main.py
import json, yaml, time
from pathlib import Path
from openai import OpenAI
import numpy as np
from rank_bm25 import BM25Okapi
from utils import embed, cosine_sim      # 6–8 LOC helpers

cfg = yaml.safe_load(open("config.yaml"))
client = OpenAI(api_key=cfg["openai_api_key"])

# 1. load & embed context once
chunks = []
embeds = []
chunk_tokens = []

for p in Path("context").glob("*.md"):
    text = p.read_text()
    for chunk in text.split("\n\n"):
        chunks.append(chunk)
        embeds.append(embed(chunk, client))
        # Tokenize for BM25
        tokens = chunk.lower().split()
        chunk_tokens.append(tokens)

# Create BM25 index
bm25 = BM25Okapi(chunk_tokens)

# Track last config file modification time
last_config_mtime = 0

# Reload configuration from yaml
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
                    cfg.update(new_cfg)
                    last_config_mtime = current_mtime
                    if old_mode != new_mode:
                        print(f"[main.py] Mode changed from {old_mode} to {new_mode}")
                    return True  # Config was reloaded
        return False  # No change in config
    else:
        return False  # Config file doesn't exist

def handle(text):
    # Reload config to get the latest mode setting
    reload_config()
    # 1. Semantic search with embeddings
    q_emb = embed(text, client)
    semantic_scores = [cosine_sim(q_emb, e) for e in embeds]
    
    # 2. Keyword search with BM25
    query_tokens = text.lower().split()
    bm25_scores = bm25.get_scores(query_tokens)
    
    # 3. Normalize both score arrays
    if max(semantic_scores) > 0:
        semantic_scores = np.array(semantic_scores) / max(semantic_scores)
    if max(bm25_scores) > 0:
        bm25_scores = bm25_scores / max(bm25_scores)
    
    # 4. Combine scores (weighted average)
    semantic_weight = cfg.get("semantic_weight", 0.7)  # Default 70% semantic, 30% keyword
    combined_scores = semantic_weight * semantic_scores + (1 - semantic_weight) * bm25_scores
    
    # 5. Get top k context chunks
    top_indices = np.argsort(combined_scores)[-cfg["top_k_context"]:]
    top_indices = top_indices[::-1]  # Reverse to get descending order
    ctx = [chunks[i] for i in top_indices]
    
    # Log scores for debugging/tuning
    if cfg.get("debug_retrieval", False):
        print(f"Top retrieved chunks with scores:")
        for i in top_indices:
            print(f"Chunk {i}: Semantic: {semantic_scores[i]:.4f}, BM25: {bm25_scores[i]:.4f}, Combined: {combined_scores[i]:.4f}")
            print(f"Content: {chunks[i][:100]}...\n")
    
    prompt = f"""
    You are the brand assistant...
    ### Context ###
    {'\n'.join(ctx)}
    ### User ###
    {text}
    ### Reply ###
    """

    assistant_msg = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": prompt}],
    ).choices[0].message.content.strip()

    # risk / confidence
    moderation_response = client.moderations.create(input=assistant_msg)
    # Extract the risk score (using the highest category score for simplicity)
    risk = 0.0
    if moderation_response.results and len(moderation_response.results) > 0:
        # Get the maximum category score as the overall risk
        category_scores = moderation_response.results[0].category_scores
        if category_scores:
            # Filter out None values before calling max()
            values = [v for v in category_scores.__dict__.values() if v is not None]
            if values:  # Only call max if we have values
                risk = max(values)
    conf_prompt = f"""Rate your confidence in this answer on a scale of 0 to 1.
    Answer with ONLY a number between 0 and 1, with no explanation or additional text.
    
    Answer: {assistant_msg}"""
    
    # Get confidence and handle potential parsing issues
    try:
        conf_response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": "You must respond with ONLY a number between 0 and 1. No text before or after the number."},
                {"role": "user", "content": conf_prompt}
            ],
        ).choices[0].message.content.strip()
        
        # Extract just the first number found in the response
        import re
        number_match = re.search(r'0\.\d+|1\.0|0|1', conf_response)
        if number_match:
            conf = float(number_match.group())
        else:
            # Fallback if no number found
            print(f"Warning: Could not extract confidence number from: {conf_response}")
            conf = 0.5  # Default to medium confidence
    except Exception as e:
        print(f"Error getting confidence: {e}")
        conf = 0.5  # Default to medium confidence

    # decide
    # Only two modes: passive and active
    active = (cfg["mode"] == "active")

    if active:
        print(f"[SENT] {assistant_msg}")
        # send_to_discord(assistant_msg)  # opt-in
    else:
        print(f"[DRAFT] {assistant_msg}")

    with open("store.jsonl", "a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "user": text,
            "reply": assistant_msg,
            "risk": float(risk),  # Ensure it's a float
            "conf": float(conf),  # Ensure it's a float
            "active": active,
        }) + "\n")

if __name__ == "__main__":
    while True:
        user_in = input("User: ")
        handle(user_in)
