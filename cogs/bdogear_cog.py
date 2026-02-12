import json
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

def test_parser():
    print("--- ЗАПУСК ТЕСТУ ---")
    options = Options()
    # Залишаємо вікно відкритим, щоб ви бачили процес
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # Ваші затримки (для тесту візьмемо першу)
    base_delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
    channel_url = "https://discord.com/channels/1323454227816906802/1358443998603120824"

    try:
        driver.get(channel_url)
        print("У вас є 20 секунд, щоб залогінитися (якщо вікно порожнє)...")
        time.sleep(20)

        garmoth_pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'
        
        # Шукаємо повідомлення
        messages = driver.find_elements(By.XPATH, "//li[contains(@class, 'messageListItem')]")
        
        found = False
        for msg in messages:
            text = msg.text # Беремо весь текст повідомлення для простоти тесту
            links = re.findall(garmoth_pattern, text)
            
            if links:
                try:
                    # Пробуємо витягнути нікнейм
                    author_element = msg.find_element(By.XPATH, ".//span[contains(@class, 'username')]")
                    nickname = author_element.text
                except:
                    nickname = "Unknown_User"

                print(f"\n[УСПІХ] Знайдено дані:")
                print(f"Користувач: {nickname}")
                print(f"Посилання: {links[0]}")
                
                # Тестове збереження
                test_data = {nickname: links[0]}
                with open("test_gear.json", "w", encoding="utf-8") as f:
                    json.dump(test_data, f, ensure_ascii=False, indent=4)
                
                wait_time = base_delays[0]
                print(f"Імітація затримки: {wait_time} секунд...")
                time.sleep(5) # У тесті почекаємо 5 сек замість 20 для швидкості
                
                found = True
                break # Зупиняємося після першого знайденого
        
        if not found:
            print("\n[УВАГА] Посилань на Garmoth не знайдено на видимій частині екрана.")
            print("Спробуйте прокрутити чат вгору вручну, поки відкрите вікно браузера.")

    finally:
        print("\nТест завершено. Перевірте файл test_gear.json")
        driver.quit()

if __name__ == "__main__":
    test_parser()
