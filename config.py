import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
BS_API_KEY: str = os.getenv("BS_API_KEY", "")
CR_API_KEY: str = os.getenv("CR_API_KEY", "")
COC_API_KEY: str = os.getenv("COC_API_KEY", "")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot.db")

BS_API_BASE = "https://api.brawlstars.com/v1"
CR_API_BASE = "https://api.clashroyale.com/v1"
COC_API_BASE = "https://api.clashofclans.com/v1"

LOLZ_BASE = "https://lolz.live"
FUNPAY_BASE = "https://funpay.com"

VALIDITY_CHECK_INTERVAL = 300   # 5 minutes
ORDER_CHECK_INTERVAL = 30        # 30 seconds
BUMP_INTERVAL = 10800            # 3 hours

MAX_LOT_ERRORS = 3
