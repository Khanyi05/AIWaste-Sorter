import requests
from bs4 import BeautifulSoup
import re

camera_ip = "192.168.1.67"
url = f"http://{camera_ip}"

try:
    response = requests.get(url, timeout=5)
    print(f"✅ Connected to {url}")

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Find possible links
    possible_links = []

    # Look at <a> tags
    for link in soup.find_all("a", href=True):
        possible_links.append(link['href'])

    # Look at <img> tags (some cams use mjpeg)
    for img in soup.find_all("img", src=True):
        possible_links.append(img['src'])

    # Look for JS or inline text containing RTSP/HTTP streams
    streams = re.findall(r"(rtsp://[^\s'\"]+|http://[^\s'\"]+\.(mjpg|cgi|jpg))", response.text)
    for s in streams:
        possible_links.append(s[0])

    # Print results
    if possible_links:
        print("🔍 Possible video/stream links found:")
        for link in set(possible_links):
            if link.startswith("http") or link.startswith("rtsp"):
                print("  ", link)
            else:
                print("  ", f"http://{camera_ip}/{link.lstrip('/')}")
    else:
        print("⚠️ No direct stream links found. The page may require login.")

except Exception as e:
    print(f"❌ Could not connect to {url}: {e}")
