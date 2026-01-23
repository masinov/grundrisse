import os
import shutil
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import random

def resolve_chrome_binary():
    env_path = os.environ.get("CHROME_BINARY") or os.environ.get("CHROME_PATH")
    if env_path:
        return env_path

    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path

    user = os.environ.get("WIN_USERNAME") or os.environ.get("USERNAME") or os.environ.get("USER")
    candidates = [
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]
    if user:
        candidates.append(f"/mnt/c/Users/{user}/AppData/Local/Google/Chrome/Application/chrome.exe")

    for path in candidates:
        if os.path.exists(path):
            return path

    return None

class GoogleQuerySystem:
    def __init__(self):
        # Configure options for the stealth browser
        options = uc.ChromeOptions()
        options.add_argument("--headless")  # Run in background (no GUI). Set to False for debugging.
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # User agent to look like a standard Chrome browser on Windows
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        chrome_binary = resolve_chrome_binary()
        if not chrome_binary:
            raise RuntimeError(
                "Chrome binary not found. Set CHROME_BINARY to the full path of chrome.exe "
                "or ensure chrome is on PATH."
            )

        options.binary_location = str(chrome_binary)
        self.driver = uc.Chrome(options=options)
        
    def search(self, query, num_results=10):
        """
        Executes a search and returns a list of results.
        """
        url = f"https://www.google.com/search?q={query}&num={num_results}"
        
        try:
            print(f"Searching for: '{query}'...")
            self.driver.get(url)
            
            # Wait for the results container to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "search"))
            )
            
            # Random sleep to mimic human behavior
            time.sleep(random.uniform(1.5, 3.5))
            
            # Get the page source and parse with BeautifulSoup
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")
            
            results = []
            
            # Google puts results in divs with class 'g'
            search_blocks = soup.find_all('div', class_='g')
            
            for block in search_blocks:
                result = self._parse_result_block(block)
                if result:
                    results.append(result)
            
            return results

        except Exception as e:
            print(f"Error during search: {e}")
            return []

    def _parse_result_block(self, block):
        """
        Helper to extract title, link, and snippet from a single result block.
        """
        try:
            # Title and Link are usually in an <a> tag inside an <h3>
            title_tag = block.find('h3')
            if not title_tag:
                return None
                
            link_tag = title_tag.find_parent('a')
            title = title_tag.get_text()
            link = link_tag.get('href') if link_tag else "No Link"
            
            # Snippet/Description is usually in a div with specific styling classes
            # This selector targets the common text snippet class
            snippet_tag = block.find('div', {'data-snf': 'nke7rc'})
            # Fallback if class changes (common with Google)
            if not snippet_tag:
                 snippet_tag = block.find('span', class_='st') 
            
            snippet = snippet_tag.get_text() if snippet_tag else "No description available."
            
            return {
                "title": title,
                "link": link,
                "snippet": snippet
            }
        except Exception:
            return None

    def close(self):
        self.driver.quit()

# --- Usage Example ---
if __name__ == "__main__":
    gqs = GoogleQuerySystem()
    
    try:
        query_term = "Python web scraping tutorials"
        data = gqs.search(query_term)
        
        print(f"\nFound {len(data)} results:\n")
        for i, item in enumerate(data, 1):
            print(f"{i}. {item['title']}")
            print(f"   Link: {item['link']}")
            print(f"   Info: {item['snippet'][:100]}...")
            print("-" * 50)
            
    finally:
        gqs.close()
