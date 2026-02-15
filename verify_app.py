from playwright.sync_api import sync_playwright
import sys
import os

def run():
    print("Starting verification...")
    try:
        with sync_playwright() as p:
            print("Launching browser...")
            # Try chromium first, then firefox
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                print("Chromium failed, trying Firefox...")
                browser = p.firefox.launch(headless=True)

            page = browser.new_page()
            print("Navigating to app...")
            response = page.goto("http://127.0.0.1:8080")

            print(f"Status: {response.status}")
            print(f"Title: {page.title()}")

            # Check for redirect to login
            if "/auth/login" in page.url:
                print("Redirected to login page as expected.")

            page.screenshot(path="verification_screenshot.png")
            print("Screenshot saved to verification_screenshot.png")
            print("SUCCESS")
            browser.close()
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()
