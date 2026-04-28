import os

emojis_to_remove = [
    '📁', '🧠', '👥', '🐾', '🏜️', '⚡', '🔬', '🕐', '🟢', '🌙', '⚙️', '⏱️', 
    '🖼️', '🌅', '✏️', '✔️', '⭐', '🎨', '🚪', '👋', '📸', '📄', '💖', '📂', 
    '☀️', '🌐', '🔍', '📌', '🏷️', '✂️', '💾', '🔄', '🔌', '❌', '📍', '🚨', '👤'
]

files_to_edit = ['index.html', 'script.js']

for file in files_to_edit:
    if not os.path.exists(file):
        continue
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for emoji in emojis_to_remove:
        # Also remove any space after the emoji if it exists to avoid double spaces,
        # but let's just do a simple replace first. Actually, `emoji + ' '` might be better.
        content = content.replace(emoji + ' ', '')
        content = content.replace(emoji, '')
        
    with open(file, 'w', encoding='utf-8') as f:
        f.write(content)

print("Emojis removed.")
