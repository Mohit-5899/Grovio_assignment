"""
Helper utilities for embedding and similarity comparison.
"""
import numpy as np

def embed(text, client):
    """
    Generate embeddings for text using OpenAI's embedding model.
    
    Args:
        text (str): The text to embed
        client (OpenAI): OpenAI client instance
        
    Returns:
        np.array: The embedding vector
    """
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"  # You can change this to another embedding model if needed
    )
    return np.array(response.data[0].embedding)

def cosine_sim(a, b):
    """
    Calculate cosine similarity between two vectors.
    
    Args:
        a (np.array): First vector
        b (np.array): Second vector
        
    Returns:
        float: Cosine similarity score between 0 and 1
    """
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
