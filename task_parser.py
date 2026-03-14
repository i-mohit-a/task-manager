import re


def parse_task_input(text):
    """
    Parse task input with inline syntax:
    - Flags: [flag] extracted and removed from title
    - Priority: critical or major or minor (default: minor)
    - Effort: -4h or -2h (number followed by h)

    Example: "Build login page [frontend] [auth] major -8h"
    Returns: {"title": "Build login page", "priority": "major", "effort_hours": 8, "flags": ["frontend", "auth"]}
    """
    result = {
        "title": "",
        "priority": "minor",
        "effort_hours": 0,
        "flags": [],
        "start_date": None,
        "due_date": None
    }

    # Extract flags [something]
    flags = re.findall(r'\[([^\[\]]+)\]', text)
    result["flags"] = [f.strip() for f in flags if f.strip()]
    text = re.sub(r'\[[^\[\]]+\]', '', text)

    # Extract priority: !critical, !major, !minor (! prefix required)
    priority_match = re.search(r'!(critical|major|minor)\b', text, re.IGNORECASE)
    if priority_match:
        result["priority"] = priority_match.group(1).lower()
        text = re.sub(r'!(critical|major|minor)\b', '', text, flags=re.IGNORECASE)

    # Extract effort ~4h
    effort_match = re.search(r'~(\d+\.?\d*)h\b', text, re.IGNORECASE)
    if effort_match:
        result["effort_hours"] = int(float(effort_match.group(1)))
        text = re.sub(r'~(\d+\.?\d*)h\b', '', text, flags=re.IGNORECASE)

    # Extract start date >YYYY-MM-DD
    start_match = re.search(r'>(\d{4}-\d{2}-\d{2})', text)
    if start_match:
        result["start_date"] = start_match.group(1)
        text = re.sub(r'>(\d{4}-\d{2}-\d{2})', '', text)

    # Extract due date <YYYY-MM-DD
    due_match = re.search(r'<(\d{4}-\d{2}-\d{2})', text)
    if due_match:
        result["due_date"] = due_match.group(1)
        text = re.sub(r'<(\d{4}-\d{2}-\d{2})', '', text)

    # Clean up title
    result["title"] = ' '.join(text.split()).strip()

    return result
