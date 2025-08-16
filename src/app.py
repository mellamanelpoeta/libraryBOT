import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def login(driver, username, password, wait):
    try:
        logging.info("Navigating to library website...")
        driver.get("https://hercules.itam.mx/")
        
        logging.info("Looking for 'Mi cuenta' link...")
        mi_cuenta = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Mi cuenta")))
        mi_cuenta.click()
        logging.info("Clicked 'Mi cuenta'")

        logging.info("Entering credentials...")
        user_el = wait.until(EC.element_to_be_clickable((By.ID, "bor_id")))
        user_el.clear()
        user_el.send_keys(username)

        pass_el = wait.until(EC.element_to_be_clickable((By.ID, "bor_verification")))
        pass_el.clear()
        pass_el.send_keys(password)
        
        logging.info("Submitting login form...")
        pass_el.send_keys(Keys.RETURN)
        
        time.sleep(5)
        mi_cuenta = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Mi cuenta")))
        mi_cuenta.click()

        logging.info("Login successful")
        
    except TimeoutException as e:
        logging.error(f"Login failed - timeout waiting for element: {e}")
        raise
    except Exception as e:
        logging.error(f"Login failed with unexpected error: {e}")
        raise

def renew_loans(driver, wait):
    try:
        logging.info("Accessing account page...")
        mi_cuenta = wait.until(
        EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Mi cuenta"))
        )
        mi_cuenta.click()
        
        logging.info("Checking for loans...")
        prestamos_link = wait.until(
            EC.presence_of_element_located((By.XPATH, "//dt[normalize-space()='Préstamos']/following-sibling::dd/a"))
        )
        
        num_loans = prestamos_link.text.strip()
        if num_loans == "0":
            logging.info("No active loans found")
            return

        logging.info(f"Found {num_loans} loan(s). Navigating to loans page...")
        prestamos_link.click()

        logging.info("Looking for 'Renovar todos' button...")
        renovar_link = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Renovar todos")))
        renovar_link.click()
        logging.info("Clicked 'Renovar todos'")

        logging.info("Waiting for confirmation popup...")
        popup = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".swal2-popup.swal2-show")))
        msg = driver.find_element(By.ID, "swal2-content").text
        logging.info(f"Renewal result: {msg}")

        ok_btn = driver.find_element(By.CSS_SELECTOR, "button.swal2-confirm")
        ok_btn.click()
        logging.info("Confirmed renewal dialog")
        
    except TimeoutException as e:
        logging.warning(f"Could not complete loan renewal - element not found: {e}")
        logging.info("This might mean: no loans available, loans section unavailable, or page structure changed")
    except NoSuchElementException as e:
        logging.warning(f"Loan renewal interface not found: {e}")
    except Exception as e:
        logging.error(f"Unexpected error during loan renewal: {e}")

def check_loan_status(driver):
    try:
        logging.info("Checking current loan status...")
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
        logging.error(f"Error checking loan status: {e}")

def main():
    logging.info("Starting library renewal script...")
    
    try:
        load_dotenv()
        username = os.getenv("LIBRARY_USERNAME")
        password = os.getenv("LIBRARY_PASSWORD")
        
        if not username or not password:
            logging.error("Missing credentials - check LIBRARY_USERNAME and LIBRARY_PASSWORD in .env file")
            return

        logging.info("Initializing browser...")
        driver = webdriver.Chrome()
        driver.set_window_size(1125, 870)
        wait = WebDriverWait(driver, 20)

        login(driver, username, password, wait)
        renew_loans(driver, wait)
        check_loan_status(driver)
        
        logging.info("Script completed successfully")
        
    except WebDriverException as e:
        logging.error(f"Browser/WebDriver error: {e}")
        logging.error("Make sure ChromeDriver is installed and accessible")
    except Exception as e:
        logging.error(f"Script failed with error: {e}")
    finally:
        try:
            driver.quit()
            logging.info("Browser closed")
        except:
            logging.warning("Could not close browser cleanly")

if __name__ == "__main__":
    main()