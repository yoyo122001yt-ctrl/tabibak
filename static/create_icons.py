svg_192 = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="40" fill="#0ea5e9"/><text x="96" y="130" font-family="Arial" font-weight="bold" font-size="110" fill="white" text-anchor="middle">T</text></svg>'

svg_512 = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="100" fill="#0ea5e9"/><text x="256" y="360" font-family="Arial" font-weight="bold" font-size="300" fill="white" text-anchor="middle">T</text></svg>'

with open('static/icon-192.svg', 'w') as f:
    f.write(svg_192)

with open('static/icon-512.svg', 'w') as f:
    f.write(svg_512)

print('Icons created!')