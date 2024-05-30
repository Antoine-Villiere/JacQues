import os
import json

def load_and_combine_data(base_dir):
    combined_data = []

    for root, _, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith('.json'):
                try:
                    with open(file_path, 'r', encoding='utf8') as f:
                        data = json.load(f)
                        messages = data.get("messages", [])
                        if messages:
                            parsed_text = "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages)
                            combined_data.append(parsed_text)
                except (json.JSONDecodeError, KeyError, IOError) as e:
                    print(f"Error processing JSON file {file_path}: {e}")
            elif file.endswith('.md'):
                try:
                    with open(file_path, 'r', encoding='utf8') as f:
                        combined_data.append(f.read())
                except IOError as e:
                    print(f"Error reading markdown file {file_path}: {e}")

    return "\n\n".join(combined_data)

# Usage example
combined_data_str = load_and_combine_data(base_dir="/Users/antoinevilliere/Desktop/Jarvis/pythonProject/chat_sessions")
print(combined_data_str)
# Now you can save combined_data_str to a file if needed
