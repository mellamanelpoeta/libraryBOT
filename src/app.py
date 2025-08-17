# app.py
import os
import re
import time
import logging
from datetime import datetime

from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
)

from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ======================
# Driver / Helpers
# ======================
def make_driver():
    """Create a resilient Chrome WebDriver ready for CI headless usage."""
    headless = os.getenv("HEADLESS", "1")  # set HEADLESS=0 locally to see the browser
    options = Options()
    if headless == "1":
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1000")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--lang=es-MX")

    # Reduce automation signals (helps with some sites)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    # Stable UA (optional)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )

    if os.getenv("CHROME_BIN"):  # respected in CI
        options.binary_location = os.getenv("CHROME_BIN")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Hide webdriver flag
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
        )
    except Exception:
        pass

    return driver


def wait_page_ready(driver, timeout=30):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def wait_for_url_change(driver, old_url, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.current_url != old_url)
    except TimeoutException:
        # Some apps update content via AJAX without URL change—just ensure DOM is ready
        wait_page_ready(driver, timeout=5)


def safe_click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)


def accept_cookies_if_any(driver):
    """Dismiss common cookie/consent banners in ES/EN if present."""
    labels = [
        "Aceptar todo", "Aceptar", "Acepto", "Entendido",
        "OK", "Accept all", "Accept", "Allow", "I agree"
    ]
    for txt in labels:
        elems = driver.find_elements(
            By.XPATH, f"//button[contains(., '{txt}')]|//a[contains(., '{txt}')]"
        )
        if elems:
            try:
                safe_click(driver, elems[0])
                time.sleep(2)
                return True
            except Exception:
                continue
    return False


def find_in_any_frame(driver, locator, timeout=20):
    """
    Try to find an element by locator in default content and then inside iframes.
    Returns the element and leaves the driver focused on the frame where it was found.
    """
    driver.switch_to.default_content()
    try:
        return WebDriverWait(driver, min(5, timeout)).until(EC.presence_of_element_located(locator))
    except TimeoutException:
        pass

    frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    for frame in frames:
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame(frame)
        except Exception:
            continue
        try:
            el = WebDriverWait(driver, min(5, timeout)).until(EC.presence_of_element_located(locator))
            return el
        except TimeoutException:
            # Try nested one level deep
            nested = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            for n in nested:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(frame)
                    driver.switch_to.frame(n)
                    el = WebDriverWait(driver, min(5, timeout)).until(EC.presence_of_element_located(locator))
                    return el
                except Exception:
                    continue

    driver.switch_to.default_content()
    raise TimeoutException(f"Element not found in any frame for locator: {locator}")


def find_and_click_mi_cuenta(driver, wait):
    """Find and click 'Mi cuenta' whether in the top document or an iframe."""
    xpaths = [
        "//a[contains(normalize-space(.), 'Mi cuenta')]",
        "//a[contains(translate(normalize-space(.), 'CUENTA', 'cuenta'), 'mi cuenta')]",
        "//a[@href and (contains(., 'Mi cuenta') or contains(., 'Cuenta'))]",
        "//button[contains(normalize-space(.), 'Mi cuenta')]",
    ]

    driver.switch_to.default_content()
    for xp in xpaths:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            safe_click(driver, el)
            return True
        except TimeoutException:
            pass
        except Exception:
            pass

    frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    for frame in frames:
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame(frame)
        except Exception:
            continue
        for xp in xpaths:
            els = driver.find_elements(By.XPATH, xp)
            if els:
                safe_click(driver, els[0])
                return True

    driver.switch_to.default_content()
    return False


def resilient_click_locator(driver, locator, timeout=20, attempts=4, search_in_frames=True):
    """
    Re-find and click a locator, retrying on staleness or transient timeouts.
    Leaves the driver focused in the frame where the element was clicked.
    """
    last_exc = None
    for i in range(attempts):
        try:
            if search_in_frames:
                el = find_in_any_frame(driver, locator, timeout=min(6, timeout))
            else:
                driver.switch_to.default_content()
                el = WebDriverWait(driver, min(6, timeout)).until(EC.presence_of_element_located(locator))

            # Make sure it's clickable in the current context
            try:
                WebDriverWait(driver, 6).until(EC.element_to_be_clickable(locator))
            except TimeoutException:
                pass

            safe_click(driver, el)
            return True
        except (StaleElementReferenceException, TimeoutException) as e:
            last_exc = e
            time.sleep(0.5 * (i + 1))  # small backoff; DOM might be re-rendering
            continue
    if last_exc:
        raise last_exc
    return False


def _dump_debug(driver, tag, enable=False):
    """Save screenshot + HTML to inspect what the headless browser saw."""
    if enable:
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            png = f"debug_{tag}_{ts}.png"
            html = f"debug_{tag}_{ts}.html"
            driver.save_screenshot(png)
            with open(html, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logging.info(f"Saved debug artifacts: {png} / {html}")
        except Exception as e:
            logging.warning(f"Could not save debug artifacts: {e}")


# ======================
# Flows
# ======================
def login(driver, username, password, wait):
    try:
        logging.info("Navigating to library website...")
        driver.get("https://hercules.itam.mx/")
        wait_page_ready(driver)
        accept_cookies_if_any(driver)

        logging.info("Looking for 'Mi cuenta' link...")
        if not find_and_click_mi_cuenta(driver, wait):
            raise TimeoutException("Could not locate 'Mi cuenta' (maybe behind a modal or inside an iframe).")

        logging.info("Entering credentials...")
        user_el = find_in_any_frame(driver, (By.ID, "bor_id"), timeout=25)
        pass_el = find_in_any_frame(driver, (By.ID, "bor_verification"), timeout=25)

        user_el.clear(); user_el.send_keys(username)
        pass_el.clear(); pass_el.send_keys(password)

        logging.info("Submitting login form...")
        try:
            pass_el.send_keys(Keys.RETURN)
        except Exception:
            driver.execute_script("arguments[0].form && arguments[0].form.submit();", pass_el)

        driver.switch_to.default_content()
        wait_page_ready(driver, timeout=30)
        time.sleep(1)

        # Some portals require clicking “Mi cuenta” again
        find_and_click_mi_cuenta(driver, wait)

        logging.info("Login successful")

    except TimeoutException as e:
        _dump_debug(driver, "login-timeout")
        logging.error(f"Login failed - timeout waiting for element: {e}")
        raise
    except Exception as e:
        _dump_debug(driver, "login-exception")
        logging.error(f"Login failed with unexpected error: {e}")
        raise


def renew_loans(driver, wait):
    try:
        logging.info("Accessing account page...")
        driver.switch_to.default_content()
        find_and_click_mi_cuenta(driver, wait)

        logging.info("Checking for loans...")
        prestamos_dd = find_in_any_frame(
            driver,
            (By.XPATH, "//dt[normalize-space()='Préstamos']/following-sibling::dd[1]//a"),
            timeout=25,
        )

        num_txt = prestamos_dd.text.strip()
        m = re.search(r"\d+", num_txt)
        num_loans = int(m.group(0)) if m else (0 if num_txt == "0" else 1)

        if num_loans == 0:
            logging.info("No active loans found")
            return

        logging.info(f"Found {num_loans} loan(s). Navigating to loans page...")

        old_url = driver.current_url
        # Click the link and wait for staleness / url change (prevents stale next)
        safe_click(driver, prestamos_dd)
        try:
            WebDriverWait(driver, 10).until(EC.staleness_of(prestamos_dd))
        except TimeoutException:
            pass
        wait_for_url_change(driver, old_url, timeout=10)
        wait_page_ready(driver, timeout=20)
        driver.switch_to.default_content()
        time.sleep(2)

        logging.info("Looking for 'Renovar todos' button...")

        renovar_candidates = [
            (By.LINK_TEXT, "Renovar todos"),
            (By.PARTIAL_LINK_TEXT, "Renovar"),
            (By.CSS_SELECTOR, "a.btn-renovar-todos"),
            (By.XPATH, "//a[contains(., 'Renovar todos') or contains(., 'Renovar todo')]"),
        ]

        clicked = False
        for by, sel in renovar_candidates:
            try:
                resilient_click_locator(driver, (by, sel), timeout=20, attempts=4, search_in_frames=True)
                clicked = True
                break
            except (TimeoutException, StaleElementReferenceException):
                continue

        if not clicked:
            logging.info("No 'Renovar todos' control found; perhaps items are not renewable or UI changed.")
            return

        logging.info("Clicked 'Renovar todos'")

        logging.info("Waiting for confirmation popup...")
        try:
            popup = WebDriverWait(driver, 15).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".swal2-popup.swal2-show"))
            )
            # Message might be in #swal2-content or #swal2-html-container depending on version
            msg = ""
            try:
                msg = driver.find_element(By.ID, "swal2-content").text
            except NoSuchElementException:
                try:
                    msg = driver.find_element(By.ID, "swal2-html-container").text
                except NoSuchElementException:
                    msg = popup.text
            logging.info(f"Renewal result: {msg}")

            ok_btn = driver.find_element(By.CSS_SELECTOR, "button.swal2-confirm")
            safe_click(driver, ok_btn)
            logging.info("Confirmed renewal dialog")
        except TimeoutException:
            logging.info("No confirmation popup detected; continuing.")

    except TimeoutException as e:
        _dump_debug(driver, "renew-timeout")
        logging.warning(f"Could not complete loan renewal - element not found: {e}")
        logging.info("This might mean: no loans available, loans section unavailable, or page structure changed")
    except NoSuchElementException as e:
        _dump_debug(driver, "renew-noselem")
        logging.warning(f"Loan renewal interface not found: {e}")
    except Exception as e:
        _dump_debug(driver, "renew-exception")
        logging.error(f"Unexpected error during loan renewal: {e}")


def check_loan_status(driver):
    try:
        logging.info("Checking current loan status...")
        driver.switch_to.default_content()
        rows = driver.find_elements(By.CSS_SELECTOR, "table.tabla_no_renovados tbody tr")

        if not rows:
            logging.info("No loan status table found")
            return

        now = datetime.now()
        logging.info(f"Current time: {now.strftime('%d/%m/%y %H:%M')}")

        for i, row in enumerate(rows, 1):
            cells = row.find_elements(By.TAG_NAME, "td")
            if not cells:
                logging.warning(f"Row {i} has no cells - skipping")
                continue

            title = cells[0].text.strip()
            due_txt = cells[2].text.strip()

            try:
                due_date = datetime.strptime(due_txt, "%d/%m/%y %H:%M")
                estado = "⚠️ OVERDUE" if due_date < now else "✅ On time"
                logging.info(f"📚 {title} → Due: {due_txt} → {estado}")
            except ValueError as e:
                logging.error(f"Could not parse due date '{due_txt}' for '{title}': {e}")

    except Exception as e:
        _dump_debug(driver, "status-exception")
        logging.error(f"Error checking loan status: {e}")


# ======================
# Main
# ======================
def main():
    logging.info("Starting library renewal script...")
    driver = None
    try:
        load_dotenv()
        username = os.getenv("LIBRARY_USERNAME")
        password = os.getenv("LIBRARY_PASSWORD")

        if not username or not password:
            logging.error("Missing credentials - set LIBRARY_USERNAME and LIBRARY_PASSWORD (env or GitHub Secrets).")
            return

        logging.info("Initializing browser...")
        driver = make_driver()
        wait = WebDriverWait(driver, 30)

        login(driver, username, password, wait)
        renew_loans(driver, wait)
        check_loan_status(driver)

        logging.info("Script completed successfully")

    except WebDriverException as e:
        _dump_debug(driver, "webdriver-exception")
        logging.error(f"Browser/WebDriver error: {e}")
        logging.error("Make sure Chrome is installed; versions are handled by webdriver-manager.")
    except Exception as e:
        _dump_debug(driver, "main-exception")
        logging.error(f"Script failed with error: {e}")
    finally:
        try:
            if driver:
                driver.quit()
            logging.info("Browser closed")
        except Exception:
            logging.warning("Could not close browser cleanly")


if __name__ == "__main__":
    main()
