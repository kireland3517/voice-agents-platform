with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '"threshold": 0.4,',
    '"threshold": 0.5,'
)

content = content.replace(
    '"silence_duration_ms": 700',
    '"silence_duration_ms": 1200'
)

content = content.replace(
    '"prefix_padding_ms": 400,',
    '"prefix_padding_ms": 300,'
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✅ Updated successfully!')
