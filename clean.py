import sys
import os
import re

def clean_code(content):
    # 1. Remove comment dividers: lines like '# ── ... ──'
    content = re.sub(r'^[ \t]*#\s*─+.*?─*[ \t]*\n', '', content, flags=re.MULTILINE)
    
    # 2. Shorten long module/class/function docstrings
    def shorten_docstring(m):
        doc = m.group(1)
        # Find all lines that actually have words
        lines = [line.strip() for line in doc.split('\n') if line.strip() and not set(line.strip()).issubset(set('-─_=#* '))]
        if not lines: return '""""""'
        
        # We want to pick a descriptive line. If line is just a filename, skip it
        descriptive = lines[0]
        for l in lines[:3]:
            if not l.endswith('.py') and '/' not in l and '\\' not in l:
                descriptive = l
                break
                
        # Keep just the first sentence
        first_sentence = descriptive.split('.')[0] + '.' if '.' in descriptive else descriptive
        
        # For multiline docstrings that were very long, this reduces them to one line
        return f'"""{first_sentence}"""'
        
    content = re.sub(r'\"\"\"(.*?)\"\"\"', shorten_docstring, content, flags=re.DOTALL)
    
    # 3. Strip consecutive blank lines that might result from removals
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    return content

if __name__ == "__main__":
    base_dir = r'd:\KULIAH\SEMESTER 4\Network Programming\Final Project\g04-final-project-d-ngechatt'
    for root, dirs, files in os.walk(base_dir):
        if '.git' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py') and file != 'clean.py':
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                new_content = clean_code(content)
                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f'Cleaned {file}')
    print('Done.')
