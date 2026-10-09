from playwright.sync_api import sync_playwright

def run_cuj(page):
    page.goto("http://127.0.0.1:8081/")
    page.wait_for_timeout(500)

    # In setup flow we'll be redirected to setup.html if first run
    if "setup" in page.url:
        page.locator("#setup-email").fill("admin@example.com")
        page.locator("#setup-password").fill("password123")
        page.locator("#setup-confirm").fill("password123")
        page.get_by_role("button", name="Create administrator account").click()
        page.wait_for_timeout(1000)

        page.goto("http://127.0.0.1:8081/")
        page.wait_for_timeout(1000)

    # Try logging in if form is there
    if page.locator("#login-email").is_visible():
        page.locator("#login-email").fill("admin@example.com")
        page.locator("#login-password").fill("password123")
        page.locator("#login-form button[type='submit']").click()
        page.wait_for_timeout(2000)

    # Find settings button
    page.locator("#profile-button").click()
    page.wait_for_timeout(500)
    page.locator("#admin-link").click()
    page.wait_for_timeout(1000)

    page.locator("#check-update").click()
    page.wait_for_timeout(2000)

    page.screenshot(path="/home/jules/verification/screenshots/verification.png")
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    import os
    os.makedirs("/home/jules/verification/videos", exist_ok=True)
    os.makedirs("/home/jules/verification/screenshots", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir="/home/jules/verification/videos"
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()
