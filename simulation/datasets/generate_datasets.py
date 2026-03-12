#!/usr/bin/env python3
"""Generate conversation datasets of various sizes for simulation testing."""
import json
import uuid
from pathlib import Path

TOPICS = [
    ("project setup", "setting up development environment and project structure"),
    ("code review", "reviewing code changes and suggesting improvements"),
    ("debugging", "finding and fixing bugs in the application"),
    ("architecture", "discussing system design and architecture decisions"),
    ("testing", "writing and running tests for the application"),
    ("deployment", "deploying the application to production"),
    ("documentation", "writing and maintaining documentation"),
    ("performance", "optimizing application performance"),
    ("security", "implementing security best practices"),
    ("database", "working with databases and data models"),
]


def generate_message(index: int, role: str, topic: tuple[str, str], size: str = "normal") -> dict:
    """Generate a single message."""
    topic_name, topic_desc = topic
    
    if size == "small":
        content_length = 50
    elif size == "large":
        content_length = 2000
    else:
        content_length = 200
    
    if role == "user":
        base = f"I have a question about {topic_name}. "
        detail = f"Specifically regarding {topic_desc}. " * (content_length // 50)
    else:
        base = f"Let me help you with {topic_name}. "
        detail = f"Here's what you need to know about {topic_desc}. " * (content_length // 60)
    
    content = (base + detail)[:content_length]
    
    return {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "role": role,
        "content": content,
    }


def generate_conversation(num_messages: int, size: str = "normal") -> list[dict]:
    """Generate a conversation with the specified number of messages."""
    messages = []
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        topic = TOPICS[i % len(TOPICS)]
        messages.append(generate_message(i, role, topic, size))
    return messages


def generate_dataset(name: str, num_messages: int, size: str = "normal") -> dict:
    """Generate a complete dataset."""
    return {
        "data": {"dataset_id": name},
        "namespace": "simulation",
        "user_id": "sim-user",
        "messages": generate_conversation(num_messages, size),
    }


def main():
    output_dir = Path(__file__).parent
    
    datasets = [
        ("medium_conversation", 50, "normal"),
        ("long_conversation", 200, "normal"),
        ("very_long_conversation", 500, "normal"),
        ("large_messages_conversation", 50, "large"),
    ]
    
    for name, num_messages, size in datasets:
        dataset = generate_dataset(name, num_messages, size)
        output_file = output_dir / f"{name}.json"
        output_file.write_text(json.dumps(dataset, indent=2))
        print(f"Generated {output_file}: {num_messages} messages ({size} size)")


if __name__ == "__main__":
    main()

