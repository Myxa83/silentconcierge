import subprocess

# Запуск окремих ботів
def start_bots():
    # Запуск бота для рейдів
    subprocess.Popen(["python", "bot_raid.py"])
    subprocess.Popen(["python", "bot_timezone.py"])
    # subprocess.Popen(["python", "bot_vell.py"])
    subprocess.Popen(["python", "bot_welcome.py"])

if __name__ == "__main__":
    start_bots()
